"""HTTP-транспорт для режима ``chat_completions`` (OpenAI-совместимый)."""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

from prokop.providers.profile import ProviderProfile
from prokop.transport.base import ModelResponse, ModelTransport, TransportConfig

DEFAULT_TIMEOUT = 120.0


class ChatCompletionsTransport(ModelTransport):
    """Транспорт поверх ``POST /chat/completions``."""

    def __init__(
        self,
        profile: ProviderProfile,
        *,
        api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(profile)
        self.api_key = api_key or self._key_from_env()
        self.timeout = timeout
        self._client = client

    def _key_from_env(self) -> Optional[str]:
        for var in self.profile.env_vars:
            value = os.environ.get(var)
            if value:
                return value
        return None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(self.profile.default_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def call(self, config: TransportConfig) -> ModelResponse:
        """Выполнить вызов; ошибки провайдера пробрасываются для ретраев."""
        body = self.prepare_request(config)
        client = await self._get_client()
        url = f"{(self.profile.base_url or '').rstrip('/')}/chat/completions"
        response = await client.post(url, headers=self._headers(), json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code}: {response.text[:500]}")
        data = response.json()
        return self._parse(data)

    def _parse(self, data: dict) -> ModelResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        reasoning = message.get("reasoning") or message.get("reasoning_content")
        tool_calls = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": raw.get("id"), "name": fn.get("name"), "arguments": args})
        return ModelResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            reasoning=reasoning,
            finish_reason=choice.get("finish_reason"),
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )

    async def health_check(self) -> bool:
        if not self.profile.supports_health_check:
            return False
        try:
            client = await self._get_client()
            url = f"{(self.profile.base_url or '').rstrip('/')}/models"
            response = await client.get(url, headers=self._headers())
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

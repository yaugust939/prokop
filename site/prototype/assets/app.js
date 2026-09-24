/* Копирование блока установки в один клик.
   Внешних запросов нет: только Clipboard API браузера. */
(function () {
  'use strict';

  var button = document.querySelector('[data-copy]');
  if (!button) return;

  var target = document.getElementById(button.getAttribute('data-copy'));
  if (!target) return;

  if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
    button.disabled = true;
    button.textContent = 'Копирование недоступно';
    return;
  }

  button.addEventListener('click', function () {
    navigator.clipboard.writeText(target.textContent).then(function () {
      var original = button.textContent;
      button.textContent = 'Скопировано';
      window.setTimeout(function () { button.textContent = original; }, 1600);
    }).catch(function () {
      button.disabled = true;
      button.textContent = 'Не удалось скопировать';
    });
  });
})();

#!/usr/bin/env node
/**
 * Приёмка лендинга — семь пунктов раздела 8 ТЗ.
 * Запуск: node tools/accept.mjs          (с пересборкой dist/)
 *         node tools/accept.mjs --no-build
 *
 * Скрипт ничего не «оценивает на глаз»: всё, что можно посчитать, считается здесь,
 * а несочислимое печатается списком для ручной проверки.
 */

import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE_ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const DIST = path.join(SITE_ROOT, 'dist');
const TOOLS = path.join(SITE_ROOT, 'tools');

const SITE = 'https://prokopii.ru';
const REPO = 'https://github.com/yaugust939/prokop';
const AIARTEL = 'https://aiartel.ru';

const TEXT_EXTENSIONS = new Set(['.html', '.css', '.js']);
const REQUIRED_DIST = [
  'index.html', '404.html', 'robots.txt', 'sitemap.xml', 'healthz',
  'tokens.css', 'fonts', 'logo', 'assets',
];

const findings = [];
const failures = [];

function log(line = '') { process.stdout.write(`${line}\n`); }
function ok(text) { log(`  ✓ ${text}`); }
function bad(text) { log(`  ✗ ${text}`); failures.push(text); }
function finding(text) { log(`  ! ${text}`); findings.push(text); }

async function walk(dir, base = dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walk(full, base)));
    else if (entry.isFile()) out.push(path.relative(base, full));
  }
  return out;
}

/* ------------------------------------------------------------------ цвета */

const WHITE = { r: 255, g: 255, b: 255 };

function parseColor(value) {
  const hex = value.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!hex) return null;
  let body = hex[1];
  if (body.length === 3) body = body.split('').map((c) => c + c).join('');
  return {
    r: parseInt(body.slice(0, 2), 16),
    g: parseInt(body.slice(2, 4), 16),
    b: parseInt(body.slice(4, 6), 16),
  };
}

function luminance({ r, g, b }) {
  const channel = (v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function ratio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

function mixSrgb(colorA, percent, colorB) {
  const w = percent / 100;
  return {
    r: Math.round(colorA.r * w + colorB.r * (1 - w)),
    g: Math.round(colorA.g * w + colorB.g * (1 - w)),
    b: Math.round(colorA.b * w + colorB.b * (1 - w)),
  };
}

/** Разбор tokens.css: области :root (тёмная) и [data-theme="light"] (светлая). */
function readTokens(css) {
  const scopes = { dark: {}, light: {} };
  for (const block of blocksOf(css)) {
    const selector = block.selector;
    const target = selector.includes('data-theme="light"') ? 'light' : selector.includes(':root') ? 'dark' : null;
    if (!target) continue;
    for (const decl of block.declarations) {
      if (decl.name.startsWith('--')) scopes[target][decl.name] = decl.value.trim();
    }
  }
  const light = { ...scopes.dark, ...scopes.light };
  return { dark: scopes.dark, light };
}

function resolveColor(raw, scope, seen = new Set()) {
  let value = raw.trim();
  const asVar = value.match(/^var\((--[a-z0-9-]+)\)$/i);
  if (asVar) {
    if (seen.has(asVar[1])) return null;
    seen.add(asVar[1]);
    if (!(asVar[1] in scope)) return null;
    return resolveColor(scope[asVar[1]], scope, seen);
  }
  const direct = parseColor(value);
  if (direct) return direct;
  const mix = value.match(/^color-mix\(in srgb,\s*([^,]+?)\s+(\d+(?:\.\d+)?)%\s*,\s*(.+?)\)$/i);
  if (mix) {
    const a = resolveColor(mix[1], scope, seen);
    const b = resolveColor(mix[3], scope, seen);
    if (a && b) return mixSrgb(a, Number(mix[2]), b);
    return null;
  }
  return null;
}

/** Разбор CSS на блоки: selector + объявления, включая вложенные в @media. */
function blocksOf(css) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const blocks = [];
  let i = 0;
  let start = 0;
  const stack = [];
  // Группирующие at-правила — только обёртки; @font-face и подобные остаются блоками.
  const wrapper = /^@(media|supports|layer|container)\b/i;
  while (i < clean.length) {
    const ch = clean[i];
    if (ch === '{') {
      const selector = clean.slice(start, i).trim();
      stack.push({ selector, bodyStart: i + 1, grouped: wrapper.test(selector) });
      start = i + 1;
    } else if (ch === '}') {
      const top = stack.pop();
      if (top && !top.grouped) {
        const body = clean.slice(top.bodyStart, i);
        blocks.push({ selector: top.selector, body, declarations: declarationsOf(body) });
      }
      start = i + 1;
    }
    i += 1;
  }
  return blocks;
}

function declarationsOf(body) {
  const out = [];
  for (const part of body.split(';')) {
    const idx = part.indexOf(':');
    if (idx === -1) continue;
    const name = part.slice(0, idx).trim().toLowerCase();
    const value = part.slice(idx + 1).trim();
    if (name && value) out.push({ name, value });
  }
  return out;
}

/** Крупный текст по WCAG: минимум кегля не ниже 24px (жирный — 18.66px). */
function isLargeText(fontSizeValue, fontWeightValue, scope) {
  const raw = fontSizeValue ?? '';
  const numbers = [...raw.matchAll(/(-?\d*\.?\d+)(px|rem)/g)].map((m) => {
    const value = Number(m[1]);
    return m[2] === 'rem' ? value * 16 : value;
  });
  if (!numbers.length) return false;
  const smallest = Math.min(...numbers);
  const bold = Number(fontWeightValue ?? 400) >= 700;
  return bold ? smallest >= 18.66 : smallest >= 24;
}

/* --------------------------------------------------------------- проверки */

async function checkExternal(files) {
  log('\n1. Внешние запросы в dist/');
  const allowed = [
    { pattern: SITE, why: 'canonical, og, sitemap' },
    { pattern: REPO, why: 'ссылки на репозиторий' },
    { pattern: 'http://www.w3.org/2000/svg', why: 'xmlns у SVG' },
  ];
  let scanned = 0;
  const violations = [];
  const exceptions = [];
  for (const rel of files) {
    if (!TEXT_EXTENSIONS.has(path.extname(rel))) continue;
    scanned += 1;
    const text = await readFile(path.join(DIST, rel), 'utf8');
    const lines = text.split('\n');
    lines.forEach((line, index) => {
      for (const match of line.matchAll(/https?:\/\/[^\s"'`)>]+|\/\/cdn[^\s"'`)>]*|@import/g)) {
        const hit = match[0];
        if (hit === '@import') {
          violations.push(`${rel}:${index + 1} @import`);
          continue;
        }
        if (allowed.some((a) => hit.startsWith(a.pattern))) continue;
        if (hit.startsWith(AIARTEL)) { exceptions.push(`${rel}:${index + 1} ${hit}`); continue; }
        violations.push(`${rel}:${index + 1} ${hit}`);
      }
    });
  }
  log(`  просканировано файлов: ${scanned}`);
  if (violations.length) {
    for (const v of violations.slice(0, 20)) bad(`внешний адрес: ${v}`);
  } else {
    ok('посторонних внешних адресов нет');
  }
  for (const e of exceptions) {
    finding(`исключение по копии (§4 ТЗ требует ссылку на артель): ${e} — ссылка <a href>, запроса не делает`);
  }
  const canon = await readFile(path.join(DIST, 'index.html'), 'utf8');
  if (canon.includes(`<link rel="canonical" href="${SITE}/"`)) ok(`canonical на ${SITE}/`);
  else bad('canonical не найден или указывает не туда');
  return files.length;
}

async function checkContrast() {
  log('\n2. Контрасты WCAG 2.x');
  const tokensCss = await readFile(path.join(DIST, 'tokens.css'), 'utf8');
  const appCss = await readFile(path.join(DIST, 'assets/app.css'), 'utf8');
  const scopes = readTokens(tokensCss);

  const allTextRoles = ['--text', '--text-2', '--muted', '--accent-text', '--accent-2-text',
    '--gold-text', '--link', '--warn', '--ok', '--danger', '--on-accent', '--on-gold'];
  // --on-accent и --on-gold живут только на заливках, на фон страницы не попадают.
  const fillTextRoles = new Set(['--on-accent', '--on-gold']);
  const textRoles = allTextRoles.filter((role) => !fillTextRoles.has(role));
  // Поверхности страницы: на них текст лежит наследованием.
  const pageSurfaces = ['--bg', '--bg-subtle', '--surface', '--surface-2'];
  // Заливки: встречаются только там, где правило задаёт и цвет текста.
  const fills = ['--accent', '--accent-2', '--gold'];

  const pageBackgrounds = (scope) => pageSurfaces
    .map((role) => ({ role, color: resolveColor(`var(${role})`, scope) }))
    .filter((entry) => entry.color);

  let pairsChecked = 0;
  const rows = [];

  for (const [themeName, scope] of [['тёмная', scopes.dark], ['светлая', scopes.light]]) {
    const backgrounds = pageBackgrounds(scope);
    const rules = [...blocksOf(tokensCss), ...blocksOf(appCss)];
    for (const rule of rules) {
      const colorDecl = rule.declarations.find((d) => d.name === 'color');
      const bgDecl = rule.declarations.find((d) => d.name === 'background' || d.name === 'background-color');
      if (!colorDecl || !bgDecl) continue;
      const color = resolveColor(colorDecl.value, scope);
      if (!color) continue;
      const targets = [];
      const bgColor = resolveColor(bgDecl.value, scope);
      if (bgColor) targets.push({ name: bgDecl.value, color: bgColor });
      else if (/transparent|none/i.test(bgDecl.value)) {
        for (const entry of backgrounds) targets.push({ name: `сквозь → var(${entry.role})`, color: entry.color });
      } else if (/color-mix/.test(bgDecl.value)) {
        targets.push({ name: bgDecl.value.replace(/var\(|\)/g, ''), color: resolveColor(bgDecl.value, scope) ?? color });
      }
      const fontDecl = rule.declarations.find((d) => d.name === 'font-size');
      const weightDecl = rule.declarations.find((d) => d.name === 'font-weight');
      const large = isLargeText(fontDecl?.value, weightDecl?.value, scope);
      const limit = large ? 3 : 4.5;
      // WCAG 1.4.3 не требует контраста у неактивных элементов управления.
      const exempt = /:disabled|\[aria-disabled/.test(rule.selector);
      for (const target of targets) {
        if (color.r === target.color.r && color.g === target.color.g && color.b === target.color.b) continue;
        if (!target.color) continue;
        const value = ratio(color, target.color);
        pairsChecked += 1;
        rows.push({ themeName, selector: rule.selector, text: colorDecl.value, bg: target.name, value, limit, large, exempt });
      }
    }
  }

  log(`  пар «текст/фон» из правил с обеими декларациями: ${pairsChecked}`);
  log('');
  log('  тема     пара                                              отношение  порог  итог');
  for (const row of rows) {
    const verdict = row.exempt ? 'норма' : row.value >= row.limit ? 'ок' : 'НИЖЕ';
    log(`  ${row.themeName.padEnd(8)} ${`${row.text} на ${row.bg}`.padEnd(50)} ${row.value.toFixed(2).padStart(8)}  ${String(row.limit).padStart(4)}  ${verdict}`);
    if (verdict === 'НИЖЕ') bad(`контраст ниже порога: ${row.selector} — ${row.text} на ${row.bg} = ${row.value.toFixed(2)}:1 (${row.large ? 'крупный' : 'мелкий'} текст, порог ${row.limit})`);
    if (row.exempt && row.value < row.limit) log(`           ^ неактивный элемент управления — из-под требования 1.4.3 выведен, число показано честно`);
  }

  // Контрольная сетка: роли текста против поверхностей страницы, включая наследование.
  // Берутся только роли, которые app.css действительно использует.
  const usedTokens = new Set([...appCss.matchAll(/var\((--[a-z0-9-]+)\)/gi)].map((m) => m[1]));
  let gridChecked = 0;
  const gridFailures = [];
  const skipped = textRoles.filter((role) => !usedTokens.has(role));
  for (const [themeName, scope] of [['тёмная', scopes.dark], ['светлая', scopes.light]]) {
    for (const textRole of textRoles) {
      if (!usedTokens.has(textRole)) continue;
      const color = resolveColor(`var(${textRole})`, scope);
      if (!color) continue;
      for (const surfaceRole of pageSurfaces) {
        if (!usedTokens.has(surfaceRole)) continue;
        const bg = resolveColor(`var(${surfaceRole})`, scope);
        if (!bg) continue;
        gridChecked += 1;
        const value = ratio(color, bg);
        if (value < 4.5) {
          gridFailures.push(`${themeName}: ${textRole} на ${surfaceRole} = ${value.toFixed(2)}:1`);
        }
      }
    }
  }
  log('');
  log(`  контрольная сетка «роль текста × поверхность страницы»: ${gridChecked} пар, ниже 4.5:1 — ${gridFailures.length}`);
  if (skipped.length) log(`  вне сетки: роли, не используемые в app.css: ${skipped.join(', ')}`);
  for (const failure of gridFailures) log(`    · ${failure}`);
  const usedFills = fills.map((role) => `${role} = ${(resolveColor(`var(${role})`, scopes.dark) ? 'заливка' : '—')}`).join(', ');
  log(`  заливки (${usedFills}) считаются только с текстом из того же правила`);

  const declared = rows.filter((row) => row.value < row.limit).length;
  if (!declared) ok('все пары из правил проходят свои пороги');
  return { pairsChecked, gridChecked, gridFailures: gridFailures.length };
}

async function checkNarrow() {
  log('\n3. Горизонтальный скролл при 390px (расчёт по app.css)');
  const css = await readFile(path.join(DIST, 'assets/app.css'), 'utf8');
  const narrowGutter = 20;               // --gutter-mobile
  const budget = 390 - narrowGutter * 2; // 350px полезной ширины
  const suspicious = [];
  let widthDecls = 0;
  let nowrap = [];
  let insideMedia = 0;

  for (const block of blocksOf(css)) {
    const narrow = /max-width:\s*(6[0-4][0-9]|5[0-9][0-9]|4[0-9][0-9]|390)px/.test(block.selector);
    for (const decl of block.declarations) {
      if (/^width$|^min-width$/.test(decl.name)) {
        widthDecls += 1;
        const px = [...decl.value.matchAll(/(-?\d*\.?\d+)px/g)].map((m) => Number(m[1]));
        const rem = [...decl.value.matchAll(/(-?\d*\.?\d+)rem/g)].map((m) => Number(m[1]) * 16);
        const biggest = Math.max(0, ...px, ...rem);
        if (decl.name === 'min-width' && biggest > budget && !narrow) {
          suspicious.push(`${block.selector} { ${decl.name}: ${decl.value} } — минимум шире ${budget}px без узкого медиазапроса`);
        }
        if (block.selector === '.container' && decl.name === 'width' && /^100%$/.test(decl.value)) insideMedia += 1;
      }
      if (decl.name === 'white-space' && /nowrap/.test(decl.value)) {
        // nowrap безопасен, если блок тут же обрезается: 1px + overflow: hidden.
        const clipped = block.declarations.some((d) => d.name === 'overflow' && /hidden/.test(d.value));
        const tiny = block.declarations.some(
          (d) => /^(width|max-width)$/.test(d.name) && /^1px$/.test(d.value.trim()),
        );
        if (!(clipped && tiny)) nowrap.push(`${block.selector} { white-space: nowrap }`);
      }
    }
  }

  const containerOk = /\.container\s*\{[^}]*width:\s*100%[^}]*max-width:\s*var\(--container\)/s.test(css);
  log(`  объявлений width/min-width: ${widthDecls}; white-space: nowrap: ${nowrap.length}`);
  log(`  полезная ширина при 390px: 390 − 2×${narrowGutter} = ${budget}px`);
  if (containerOk) ok('контейнер: width 100% + max-width: var(--container) — не фиксирован');
  else bad('контейнер не ограничен через max-width');
  const fixed = [...css.matchAll(/(?:^|[;{]\s*)(width|min-width):\s*([0-9.]+)(px|rem)/g)]
    .map((m) => ({ prop: m[1], size: m[3] === 'rem' ? Number(m[2]) * 16 : Number(m[2]) }))
    .filter((entry) => entry.size > budget);
  if (fixed.length) {
    for (const entry of fixed) bad(`фиксированная ширина больше ${budget}px: ${entry.prop}: ${entry.size}px`);
  } else {
    ok(`фиксированных width/min-width больше ${budget}px нет`);
  }
  if (nowrap.length) for (const item of nowrap) bad(`nowrap без обрезки: ${item}`);
  else ok('white-space: nowrap встречается только в визуально скрытых блоках');
  if (suspicious.length) for (const s of suspicious) bad(s);
  const breakpoints = ['960px', '640px'].filter((bp) => css.includes(`max-width: ${bp}`));
  if (breakpoints.length === 2) ok('переломы 960px и 640px объявлены');
  else finding(`переломы: найдено ${breakpoints.join(', ') || 'ничего'}`);
  return { widthDecls, nowrap, breakpoints: breakpoints.length };
}

async function checkDistContents() {
  log('\n4. Состав dist/');
  const missing = REQUIRED_DIST.filter((name) => !existsSync(path.join(DIST, name)));
  if (missing.length) bad(`нет обязательного: ${missing.join(', ')}`);
  else ok(`на месте: ${REQUIRED_DIST.join(', ')}`);
  const files = await walk(DIST);
  ok(`всего файлов в dist/: ${files.length}`);
  return files;
}

function checkBuild() {
  log('\n5. Сборка node tools/build-dist.mjs');
  if (process.argv.includes('--no-build')) {
    finding('сборка пропущена по --no-build');
    return null;
  }
  const run = spawnSync(process.execPath, [path.join(TOOLS, 'build-dist.mjs')], { encoding: 'utf8' });
  const output = `${run.stdout ?? ''}${run.stderr ?? ''}`;
  const count = output.match(/файлов:\s*(\d+)/);
  if (run.status !== 0) bad(`сборка упала с кодом ${run.status}`);
  else if (!count) bad('сборка не напечатала число файлов');
  else ok(`сборка прошла, файлов: ${count[1]}, нарушений в выводе: ${/НАРУШЕНИЯ/.test(output) ? 'есть' : 'нет'}`);
  const tests = output.match(/тестов на странице:\s*(\d+)\s+— источник:\s*(.+)/);
  if (tests) ok(`число тестов на странице: ${tests[1]} (${tests[2]})`);
  return count ? Number(count[1]) : null;
}

async function checkFontFaces() {
  log('\n6. @font-face → файл в dist/fonts/');
  const css = await readFile(path.join(DIST, 'tokens.css'), 'utf8');
  const rows = [];
  for (const block of blocksOf(css)) {
    if (!block.selector.includes('@font-face')) continue;
    const family = block.declarations.find((d) => d.name === 'font-family');
    const src = block.declarations.find((d) => d.name === 'src');
    if (!family || !src) continue;
    const file = src.value.match(/url\('([^']+)'\)/)?.[1];
    if (!file) continue;
    const exists = existsSync(path.join(DIST, file));
    rows.push({ family: family.value.replace(/['"]/g, ''), file, exists });
  }
  let missing = 0;
  for (const row of rows) {
    log(`  ${row.exists ? 'есть' : 'НЕТ '}  ${row.family.padEnd(14)} ${row.file}`);
    if (!row.exists) { missing += 1; bad(`@font-face без файла: ${row.family} → ${row.file}`); }
  }
  if (!missing) ok(`все ${rows.length} объявлений находят файл`);
  return rows.length;
}

async function checkHtml() {
  log('\n7. Валидность dist/index.html');
  const html = await readFile(path.join(DIST, 'index.html'), 'utf8');
  const voidTags = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr', '!doctype']);
  const stack = [];
  const problems = [];
  const body = html.replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<!--[\s\S]*?-->/g, '');
  for (const match of body.matchAll(/<(\/?)([a-zA-Z!][a-zA-Z0-9-]*)([^>]*)>/g)) {
    const closing = match[1] === '/';
    const name = match[2].toLowerCase();
    const attrs = match[3];
    if (name === '!doctype' || voidTags.has(name) || attrs.trim().endsWith('/')) continue;
    if (!closing) stack.push(name);
    else {
      const last = stack.pop();
      if (last !== name) problems.push(`закрывается </${name}>, а открыт <${last ?? '—'}>`);
    }
  }
  if (stack.length) problems.push(`не закрыты: ${stack.join(', ')}`);
  if (problems.length) for (const p of problems.slice(0, 10)) bad(`разметка: ${p}`);
  else ok('незакрытых тегов нет');

  const imgs = [...html.matchAll(/<img\b[^>]*>/g)].map((m) => m[0]);
  const noAlt = imgs.filter((tag) => !/\balt\s*=/.test(tag));
  if (noAlt.length) bad(`<img> без alt: ${noAlt.length}`);
  else ok(`alt есть у всех <img> (${imgs.length})`);

  if (/<html\s+lang="ru"/.test(html)) ok('<html lang="ru">');
  else bad('нет <html lang="ru">');
  if (/data-theme="dark"/.test(html)) ok('тема по умолчанию: data-theme="dark"');
  else bad('нет data-theme="dark"');

  const order = ['rel="icon"', 'tokens.css', 'assets/app.css']
    .map((needle) => html.indexOf(needle));
  if (order.every((index) => index >= 0) && order[0] < order[1] && order[1] < order[2]) {
    ok('порядок подключения: иконка → tokens.css → assets/app.css');
  } else {
    bad('порядок подключения иконки, tokens.css и app.css нарушен');
  }
  const wrongOrder = ['fonts/', 'logo/'].filter((p) => html.includes(`src="../${p}`));
  if (!wrongOrder.length) ok('пути логотипа и иконки абсолютны внутри dist');
  return imgs.length;
}

async function main() {
  log('ПРИЁМКА ЛЕНДИНГА PROKOP — раздел 8 ТЗ');
  log(`каталог: ${DIST}`);
  const files = await walk(DIST).catch(() => []);
  if (!files.length) {
    bad('dist/ пуст — сначала соберите: node tools/build-dist.mjs');
    process.exitCode = 1;
    return;
  }
  await checkExternal(files);
  await checkContrast();
  await checkNarrow();
  await checkDistContents();
  checkBuild();
  await checkFontFaces();
  await checkHtml();

  log('\nИТОГО');
  log(`  нарушений: ${failures.length}`);
  log(`  замечаний (требуют решения человека): ${findings.length}`);
  for (const item of findings) log(`    · ${item}`);
  if (failures.length) process.exitCode = 1;
}

await main();

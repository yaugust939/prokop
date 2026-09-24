#!/usr/bin/env node
/**
 * Сборка dist/ лендинга prokop из prototype/ и design/.
 *
 * Минификации нет намеренно: файлы копируются, пути переписываются по глубине,
 * служебные файлы генерируются. Запуск: node tools/build-dist.mjs
 */

import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** Домен живёт одной константой — по файлам не разъезжается. */
const SITE = 'https://prokopii.ru';
const SITE_NAME = 'prokop';
const SITE_DESCRIPTION =
  'Открытое ядро агента на Python под лицензией MIT: цикл хода, инструменты, ' +
  'память между сессиями, хранилище сессий, провайдеры, планировщик, субагенты, ' +
  'терминальные бэкенды. Смена модели — настройкой, без правки кода.';

const SITE_ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const PROTOTYPE_DIR = path.join(SITE_ROOT, 'prototype');
const DESIGN_DIR = path.join(SITE_ROOT, 'design');
const DIST_DIR = path.join(SITE_ROOT, 'dist');
const TESTS_FILE = path.join(SITE_ROOT, 'tools', 'test-count.json');

/** Что не копируется из prototype/ в dist/. */
const EXCLUDED = new Set(['serve.py', '_backup']);

/** В этих файлах переписываются пути и подставляется число тестов. */
const TEXT_EXTENSIONS = new Set(['.html', '.css', '.js']);

/** Переписывание путей по глубине: из prototype/ в корень dist/. */
const REWRITES = [
  ['../design/tokens.css', 'tokens.css'],
  ['../design/fonts/', 'fonts/'],
  ['../design/logo/', 'logo/'],
  ['../assets/', 'assets/'],
];

const TESTS_TOKEN = /\{\{TESTS\}\}/g;

const problems = [];
const notes = [];

function log(line = '') {
  process.stdout.write(`${line}\n`);
}

async function walk(dir, base = dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...(await walk(full, base)));
    } else if (entry.isFile()) {
      out.push(path.relative(base, full));
    }
  }
  return out;
}

function depthOf(relativePath) {
  return relativePath.split(path.sep).length - 1;
}

function rewrite(text, depth) {
  const prefix = '../'.repeat(depth);
  let result = text;
  for (const [from, to] of REWRITES) {
    result = result.split(from).join(prefix + to);
  }
  return result;
}

/**
 * Число тестов — из одного места. Порядок источников:
 *   1. переменная окружения PROKOP_TESTS (перебивает всё);
 *   2. живой прогон pytest, если python и pytest доступны и рядом есть src/tests;
 *   3. tools/test-count.json — запись реального прогона с указанием способа.
 */
function resolveTestCount() {
  const fromEnv = process.env.PROKOP_TESTS;
  if (fromEnv && /^\d+$/.test(fromEnv.trim())) {
    return { count: Number(fromEnv.trim()), source: 'переменная окружения PROKOP_TESTS' };
  }

  const sourceDir = path.join(SITE_ROOT, '..', 'src');
  if (existsSync(path.join(sourceDir, 'tests'))) {
    for (const python of ['python3', 'python']) {
      const probe = spawnSync(python, ['-m', 'pytest', '--version'], { encoding: 'utf8' });
      if (probe.status !== 0) continue;
      const run = spawnSync(python, ['-m', 'pytest', '--collect-only', '-q'], {
        cwd: sourceDir,
        encoding: 'utf8',
      });
      const match = `${run.stdout}\n${run.stderr}`.match(/(\d+)\s+tests?\s+collected/);
      if (match) {
        return {
          count: Number(match[1]),
          source: `прогон pytest (--collect-only, ${python})`,
        };
      }
    }
    notes.push('pytest недоступен — число тестов взято из tools/test-count.json');
  }

  if (existsSync(TESTS_FILE)) {
    const saved = JSON.parse(readFile(TESTS_FILE, 'utf8'));
    notes.push(`источник числа тестов: ${saved.method}, ${saved.date}, коммит ${saved.ref}`);
    return { count: saved.count, source: `tools/test-count.json (${saved.method})` };
  }

  problems.push('число тестов не найдено: нет ни pytest, ни tools/test-count.json');
  return { count: 0, source: 'не найдено' };
}

/** Таблица «@font-face объявлен → файл есть». */
async function fontReport() {
  const css = await readFile(path.join(DIST_DIR, 'tokens.css'), 'utf8');
  const rows = [];
  for (const block of css.matchAll(/@font-face\s*\{([\s\S]*?)\}/g)) {
    const family = block[1].match(/font-family:\s*'([^']+)'/);
    const src = block[1].match(/url\('([^']+)'\)/);
    if (!family || !src) continue;
    const file = src[1];
    const exists = existsSync(path.join(DIST_DIR, file));
    rows.push({ family: family[1], file, exists });
    if (!exists) problems.push(`@font-face без файла: ${family[1]} → ${file}`);
  }
  return rows;
}

/** Скан dist/ на остатки путей prototype/. */
async function leftoverReport(files) {
  const hits = [];
  for (const rel of files) {
    if (!TEXT_EXTENSIONS.has(path.extname(rel))) continue;
    const text = await readFile(path.join(DIST_DIR, rel), 'utf8');
    for (const marker of ['../design/', '../assets/']) {
      if (text.includes(marker)) {
        hits.push(`${rel} → ${marker}`);
        break;
      }
    }
  }
  return hits;
}

function checkHead(html) {
  const required = [
    ['<meta charset="utf-8">', /<meta\s+charset="utf-8">/i],
    ['viewport', /<meta\s+name="viewport"/i],
    ['title', /<title>[^<]+<\/title>/i],
    ['description', /<meta\s+name="description"/i],
    ['canonical', new RegExp(`<link\\s+rel="canonical"\\s+href="${SITE}/"`)],
    ['og:type', /property="og:type"/],
    ['og:url', /property="og:url"/],
    ['og:title', /property="og:title"/],
    ['og:description', /property="og:description"/],
    ['og:site_name', /property="og:site_name"/],
    ['og:locale', /property="og:locale"/],
    ['favicon', /<link\s+rel="icon"[^>]*favicon\.svg/],
  ];
  for (const [name, pattern] of required) {
    if (!pattern.test(html)) problems.push(`в <head> dist/index.html нет: ${name}`);
  }
}

function page404({ tests }) {
  return `<!doctype html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Страница не найдена — ${SITE_NAME}</title>
<meta name="robots" content="noindex">
<link rel="icon" type="image/svg+xml" href="logo/favicon.svg">
<link rel="stylesheet" href="tokens.css">
<link rel="stylesheet" href="assets/app.css">
</head>
<body>
<main class="section">
  <div class="container hero-inner">
    <p class="label">404</p>
    <h1>Страница не найдена</h1>
    <p class="lead">Такого адреса на сайте нет.</p>
    <p><a class="btn btn-secondary" href="/">На главную</a></p>
  </div>
</main>
</body>
</html>
`;
}

function sitemap(pages) {
  const urls = pages
    .map((rel) => {
      const clean = rel === 'index.html' ? '' : rel.replace(/\.html$/, '');
      return `  <url>\n    <loc>${SITE}/${clean}</loc>\n  </url>`;
    })
    .join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`;
}

async function main() {
  const tests = resolveTestCount();

  await rm(DIST_DIR, { recursive: true, force: true });
  await mkdir(DIST_DIR, { recursive: true });

  // 1. prototype/ → dist/, кроме serve.py и _backup
  const prototypeFiles = (await walk(PROTOTYPE_DIR)).filter(
    (rel) => !rel.split(path.sep).some((part) => EXCLUDED.has(part)),
  );
  for (const rel of prototypeFiles) {
    const target = path.join(DIST_DIR, rel);
    await mkdir(path.dirname(target), { recursive: true });
    await cp(path.join(PROTOTYPE_DIR, rel), target);
  }

  // 2. дизайн-система в корень сайта
  await mkdir(path.join(DIST_DIR, 'fonts'), { recursive: true });
  await mkdir(path.join(DIST_DIR, 'logo'), { recursive: true });
  for (const rel of await walk(path.join(DESIGN_DIR, 'fonts'))) {
    await cp(path.join(DESIGN_DIR, 'fonts', rel), path.join(DIST_DIR, 'fonts', rel));
  }
  for (const rel of await walk(path.join(DESIGN_DIR, 'logo'))) {
    await cp(path.join(DESIGN_DIR, 'logo', rel), path.join(DIST_DIR, 'logo', rel));
  }
  await cp(path.join(DESIGN_DIR, 'tokens.css'), path.join(DIST_DIR, 'tokens.css'));

  // 3. служебные файлы
  const indexHtml = await readFile(path.join(DIST_DIR, 'index.html'), 'utf8');
  checkHead(indexHtml);

  await writeFile(path.join(DIST_DIR, '404.html'), page404({ tests }), 'utf8');
  await writeFile(path.join(DIST_DIR, 'healthz'), 'ok', 'utf8');
  await writeFile(
    path.join(DIST_DIR, 'robots.txt'),
    `User-agent: *\nAllow: /\nSitemap: ${SITE}/sitemap.xml\n`,
    'utf8',
  );

  const pages = (await walk(DIST_DIR)).filter(
    (rel) => path.extname(rel) === '.html' && path.basename(rel) !== '404.html',
  );
  await writeFile(path.join(DIST_DIR, 'sitemap.xml'), sitemap(pages), 'utf8');

  // 4. переписывание путей по глубине + подстановка числа тестов
  const distFiles = await walk(DIST_DIR);
  let rewritten = 0;
  for (const rel of distFiles) {
    if (!TEXT_EXTENSIONS.has(path.extname(rel))) continue;
    const full = path.join(DIST_DIR, rel);
    const before = await readFile(full, 'utf8');
    let after = rewrite(before, depthOf(rel));
    const filled = after.replace(TESTS_TOKEN, String(tests.count));
    if (filled !== before) {
      await writeFile(full, filled, 'utf8');
      rewritten += 1;
    }
    if (filled.includes('{{TESTS}}')) problems.push(`не подставлено число тестов: ${rel}`);
  }

  // 5. отчёт сборки
  const fonts = await fontReport();
  const leftovers = await leftoverReport(distFiles);
  for (const hit of leftovers) problems.push(`остался путь prototype/: ${hit}`);

  const sizes = await Promise.all(
    distFiles.map(async (rel) => (await stat(path.join(DIST_DIR, rel))).size),
  );
  const total = sizes.reduce((sum, size) => sum + size, 0);

  log(`dist/ собран: ${SITE}`);
  log(`файлов: ${distFiles.length}, объём: ${(total / 1024).toFixed(1)} КБ`);
  log(`переписано файлов: ${rewritten}`);
  log(`тестов на странице: ${tests.count} — источник: ${tests.source}`);
  log('');
  log('@font-face → файл:');
  for (const row of fonts) {
    log(`  ${row.exists ? 'есть' : 'НЕТ '}  ${row.family.padEnd(14)} ${row.file}`);
  }
  log('');
  if (notes.length) {
    for (const note of notes) log(`примечание: ${note}`);
    log('');
  }
  if (problems.length) {
    log('НАРУШЕНИЯ:');
    for (const problem of problems.slice(0, 10)) log(`  - ${problem}`);
    if (problems.length > 10) log(`  ... всего ${problems.length}`);
    process.exitCode = 1;
    return;
  }
  log('нарушений нет.');
}

await main();

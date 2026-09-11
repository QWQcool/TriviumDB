#!/usr/bin/env node
// TriviumDB WebUI 视觉回归基线 (visual-baseline)
//
// 目的：为 Web Console (crates/triviumdb-server/web/index.html) 提供可重复的
// 截图级回归防线。页内自检（selftest）验证状态与逻辑，但覆盖不了"像素与观感"
// ——历史上已三次出现"断言全绿、肉眼不对"的问题（白底浅线、节点聚成一团、
// 侧栏高亮不切换），本脚本把这些回归钉在截图上。
//
// 用法：
//   node scripts/visual-baseline.mjs              # 校验（无基线时降级为记录模式）
//   node scripts/visual-baseline.mjs --update     # 生成/更新本平台基线
//   node scripts/visual-baseline.mjs --record-only# 只截图不比对（CI 首轮用）
//   node scripts/visual-baseline.mjs --with-sigma # 额外拍 Sigma(WebGL) 图（本机专用）
//
// 设计要点：
//   * 确定性：reduced-motion（关 ambient 微动效与过渡）、固定视口/缩放、
//     隐藏光标、清空 toast、只用确定性布局（radial —— 纯函数；force 因物理
//     帧数依赖而排除，Sigma 因 GPU/驱动差异默认排除）
//   * 平台隔离：基线按 process.platform 分目录存放，跨平台字体/抗锯齿差异
//     不会造成误报；某平台无基线时自动降级为记录模式（不失败），
//     CI 可用 workflow_dispatch 生成 linux 基线后提交
//   * 依赖缺失时优雅跳过（退出码 0），与 ui-smoke.mjs 同约定：
//     npm i --no-save playwright pixelmatch pngjs && npx playwright install chromium
//
// 退出码：0 = 通过/跳过；1 = 比对失败（差异图写入 .tmp/visual-diff/）

import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP_DIR = path.join(ROOT, '.tmp');
const SHOT_DIR = path.join(TMP_DIR, 'visual-shots');
const DIFF_DIR = path.join(TMP_DIR, 'visual-diff');
const BASELINE_ROOT = path.join(ROOT, 'tests', 'visual', 'baseline');
const PLATFORM = process.platform; // win32 / linux / darwin
const BASELINE_DIR = path.join(BASELINE_ROOT, PLATFORM);
const DB_PATH = path.join(TMP_DIR, `visual-${process.pid}-${Date.now()}.tdb`);
const PORT_CANDIDATES = [8086, 8087, 8088, 8089, 8090];
const EXE = process.platform === 'win32'
  ? path.join(ROOT, 'target', 'debug', 'triviumdb-server.exe')
  : path.join(ROOT, 'target', 'debug', 'triviumdb-server');

const ARGS = new Set(process.argv.slice(2));
const MODE_UPDATE = ARGS.has('--update');
const MODE_RECORD_ONLY = ARGS.has('--record-only');
const WITH_SIGMA = ARGS.has('--with-sigma');
// 比对容差：跨机器抗锯齿差异容忍，但结构性变化（布局塌陷/面板消失/主题反转）
// 远超该比例
const PIXEL_THRESHOLD = 0.2;      // pixelmatch 单像素判定阈值
const MAX_DIFF_RATIO = 0.015;     // 允许差异像素占比 1.5%

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (msg) => console.log(`[visual] ${msg}`);

// ---------- 依赖探测（缺失即优雅跳过） ----------
function loadPlaywright() {
  const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const probe = spawnSync(npmCmd, ['root', '-g'], { encoding: 'utf8', shell: process.platform === 'win32' });
  const bases = [path.join(ROOT, 'noop.js')];
  if (probe.status === 0 && probe.stdout) {
    bases.push(path.join(probe.stdout.trim(), 'noop.js'));
    bases.push(path.join(probe.stdout.trim(), '@playwright', 'cli', 'node_modules', 'noop.js'));
  }
  for (const base of bases) {
    try {
      const requireFrom = createRequire(base);
      const pw = requireFrom('playwright');
      if (pw && pw.chromium) return { pw, base };
    } catch (_) { /* try next */ }
  }
  return null;
}
// 比对库解析：项目本地 node_modules 优先（npm i --no-save pixelmatch pngjs），
// 再回退 playwright 所在的 base（全局安装场景）
function loadDiffLibs(extraBase) {
  const bases = [path.join(ROOT, 'noop.js')];
  if (extraBase) bases.push(extraBase);
  for (const base of bases) {
    try {
      const requireFrom = createRequire(base);
      const pixelmatch = requireFrom('pixelmatch');
      const { PNG } = requireFrom('pngjs');
      if (pixelmatch && PNG) return { pixelmatch: pixelmatch.default || pixelmatch, PNG };
    } catch (_) { /* try next base */ }
  }
  return null;
}

// ---------- HTTP / 端口 / 清理（与 ui-smoke.mjs 同套路） ----------
function request(method, urlPath, { body, headers } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(`http://127.0.0.1:${PORT}${urlPath}`, { method, headers: headers || {} }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let json = null;
        try { json = JSON.parse(text); } catch (_) { /* keep null */ }
        resolve({ status: res.statusCode, json, text });
      });
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}
function findFreePort() {
  return new Promise((resolve) => {
    const tryPort = (idx) => {
      if (idx >= PORT_CANDIDATES.length) { resolve(null); return; }
      const srv = net.createServer();
      srv.once('error', () => tryPort(idx + 1));
      srv.listen(PORT_CANDIDATES[idx], '127.0.0.1', () => srv.close(() => resolve(PORT_CANDIDATES[idx])));
    };
    tryPort(0);
  });
}
async function waitForReady(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await request('GET', '/health/ready');
      if (res.status === 200 && res.json && res.json.status) return true;
    } catch (_) { /* not up yet */ }
    await sleep(300);
  }
  return false;
}

let serverProc = null;
let browser = null;
let cleaned = false;
async function cleanup(exitCode) {
  if (cleaned) return;
  cleaned = true;
  try { if (browser) await browser.close(); } catch (_) {}
  if (serverProc && serverProc.exitCode === null) {
    try { serverProc.kill(); } catch (_) {}
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 5000);
      serverProc.once('exit', () => { clearTimeout(timer); resolve(); });
    });
  }
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      for (const suffix of ['', '-wal', '-shm', '-lock']) rmSync(DB_PATH + suffix, { force: true });
      break;
    } catch (_) { await sleep(500); }
  }
  process.exit(exitCode);
}

// ---------- 确定性种子数据（链式 CREATE 建节点 + 边，与 ui-smoke 同语法） ----------
const SEED_QUERIES = [
  'CREATE ({name: "Alice", type: "person", citations: 150})-[:KNOWS]->({name: "Bob", type: "person", citations: 45})',
  'CREATE ({title: "TriviumDB Architecture", type: "paper", year: 2026})',
  'CREATE ({name: "Tri-Model DB", type: "topic"})',
];

// ---------- 截图清单（全部确定性；Sigma 需 --with-sigma） ----------
const SHOTS = [
  {
    // 用户报过的侧栏高亮场景：点击「图拓扑」后高亮须离开「文档」（视觉钉）
    name: '00-sidebar-graph-active',
    setup: async (page) => {
      await page.evaluate(() => { applyThemeAttributes('light'); });
      await page.evaluate(() => document.querySelector('.sidebar .nav-item[data-action="quick-match"]').click());
      await sleep(1500);
    },
  },
  {
    name: '01-light-canvas-radial',
    setup: async (page) => {
      await page.evaluate(() => { applyThemeAttributes('light'); });
      await page.evaluate(() => setGraphLayoutMode('radial'));
      await sleep(1400);
    },
  },
  {
    name: '02-dark-canvas-radial',
    setup: async (page) => {
      await page.evaluate(() => { applyThemeAttributes('dark'); });
      await sleep(1200);
    },
  },
  {
    name: '03-palette-open',
    setup: async (page) => {
      await page.evaluate(() => { applyThemeAttributes('light'); });
      await page.keyboard.press('Control+k');
      await sleep(600);
    },
  },
  {
    name: '04-panel-node-detail',
    setup: async (page) => {
      await page.keyboard.press('Escape');
      await sleep(300);
      const opened = await page.evaluate(() => {
        if (!graphNodes.length) return false;
        const n = graphNodes.find(x => x.label === 'Alice') || graphNodes[0];
        openNodeDrawer({ id: n.id, label: n.label, payload: n.payload, vector: n.vector || [] });
        return true;
      });
      if (!opened) throw new Error('图数据为空，无法生成节点详情截图（种子或查询步骤异常）');
      await sleep(900);
    },
  },
  {
    name: '05-panel-filter',
    setup: async (page) => {
      await page.evaluate(() => toggleGraphFilterPanel('graphFilterPanel'));
      await sleep(700);
    },
  },
  {
    name: '06-tutorial-step8',
    setup: async (page) => {
      await page.evaluate(() => { collapseUnifiedPanel(); document.getElementById('openTutorialBtn').click(); });
      await sleep(500);
      await page.evaluate(() => {
        const items = document.querySelectorAll('#tutorialStepsNav .tutorial-step-item');
        if (items.length) items[items.length - 1].click();
      });
      await sleep(600);
    },
  },
];
if (WITH_SIGMA) {
  SHOTS.push({
    name: '07-sigma-radial',
    setup: async (page) => {
      await page.evaluate(() => { document.getElementById('closeTutorialBtn').click(); });
      await page.evaluate(() => { document.getElementById('toggleWebGLBtn').click(); });
      await sleep(6000); // CDN 加载 + 实例化
      await page.evaluate(() => setGraphLayoutMode('radial'));
      await sleep(2500);
    },
  });
}

// ---------- 主流程 ----------
const pwInfo = loadPlaywright();
if (!pwInfo) {
  log('playwright 不可用，跳过视觉基线。安装：npm i --no-save playwright pixelmatch pngjs && npx playwright install chromium');
  process.exit(0);
}
const { pw, base: pwBase } = pwInfo;
const diffLibs = loadDiffLibs(pwBase);
if (!diffLibs && !MODE_UPDATE && !MODE_RECORD_ONLY) {
  log('pixelmatch/pngjs 不可用，无法比对（降级为记录模式）。安装：npm i --no-save pixelmatch pngjs');
}

if (!existsSync(EXE)) {
  console.error(`[visual] 未找到 server 可执行文件: ${EXE}（先 cargo build -p triviumdb-server）`);
  process.exit(1);
}
const PORT = await findFreePort();
if (!PORT) {
  console.error('[visual] 8086-8090 端口均被占用');
  process.exit(1);
}
mkdirSync(TMP_DIR, { recursive: true });
mkdirSync(SHOT_DIR, { recursive: true });
mkdirSync(DIFF_DIR, { recursive: true });
for (const f of readdirSync(TMP_DIR)) {
  if (/^visual-\d+-\d+\.tdb/.test(f)) { try { rmSync(path.join(TMP_DIR, f), { force: true }); } catch (_) {} }
}
log(`启动临时 server: 127.0.0.1:${PORT}`);
serverProc = spawn(EXE, ['--dim', '4', '--database', DB_PATH, '--listen', `127.0.0.1:${PORT}`], {
  cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
});
serverProc.stdout.on('data', () => {});
serverProc.stderr.on('data', () => {});
if (!(await waitForReady(30000))) {
  console.error('[visual] server 30s 内未就绪');
  await cleanup(1);
}
for (const q of SEED_QUERIES) {
  const res = await request('POST', '/v1/tql', { body: JSON.stringify({ query: q, mutation: true }), headers: { 'Content-Type': 'application/json' } });
  if (res.status !== 200) {
    console.error(`[visual] 种子写入失败: ${q}\n${res.text}`);
    await cleanup(1);
  }
}
const seedCheck = await request('POST', '/v1/tql', {
  body: JSON.stringify({ query: 'FIND {type: "person"} RETURN * LIMIT 10' }),
  headers: { 'Content-Type': 'application/json' },
});
if (!seedCheck.json || (seedCheck.json.rows || []).length < 2) {
  console.error('[visual] 种子校验失败：person 节点应 >= 2');
  await cleanup(1);
}

browser = await pw.chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1400, height: 860 },
  deviceScaleFactor: 1,
  reducedMotion: 'reduce',           // 关 ambient 微动效 / GSAP 过渡 / CSS 动画
});
await page.addInitScript(() => {
  // 关光标闪烁 + 固定滚动条表现（截图确定性）
  const style = document.createElement('style');
  style.textContent = '*{caret-color:transparent!important}html{scrollbar-width:thin}';
  document.addEventListener('DOMContentLoaded', () => document.head.appendChild(style));
});
await page.goto(`http://127.0.0.1:${PORT}/ui`, { waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => window.__TRIVIUM_APP_READY === true, null, { timeout: 15000 });
await sleep(800);
// 载入确定性图数据（FIND 有过滤条件，符合 TQL 约束）
await page.evaluate(() => setEditorValue('FIND {type: "person"} RETURN * LIMIT 25'));
await page.click('#runQueryBtn');
await page.waitForFunction(() => graphNodes.length >= 2, null, { timeout: 10000 });
await page.evaluate(() => document.querySelector('[data-view="graph"]').click());
await sleep(1500);

const results = [];
for (const shot of SHOTS) {
  await page.evaluate(() => { const s = document.getElementById('toastStack'); if (s) s.textContent = ''; });
  await shot.setup(page);
  await page.evaluate(() => { const s = document.getElementById('toastStack'); if (s) s.textContent = ''; });
  await sleep(250);
  const shotPath = path.join(SHOT_DIR, `${shot.name}.png`);
  await page.screenshot({ path: shotPath });
  results.push({ name: shot.name, shotPath });
  log(`已截图 ${shot.name}`);
}

// ---------- 更新 / 记录 / 比对 三种模式 ----------
const baselineExists = existsSync(BASELINE_DIR);
if (MODE_UPDATE) {
  mkdirSync(BASELINE_DIR, { recursive: true });
  for (const r of results) {
    writeFileSync(path.join(BASELINE_DIR, `${r.name}.png`), readFileSync(r.shotPath));
  }
  log(`基线已写入 ${path.relative(ROOT, BASELINE_DIR)}（${results.length} 张，platform=${PLATFORM}）`);
  await cleanup(0);
}
if (MODE_RECORD_ONLY || !diffLibs || !baselineExists) {
  if (!baselineExists) {
    log(`本平台（${PLATFORM}）暂无基线，本次为记录模式（不判定失败）。`);
    log('如需启用该平台门禁：node scripts/visual-baseline.mjs --update 生成基线并提交，或从 CI 产物取回。');
  } else {
    log('记录模式：仅截图，不比对。');
  }
  await cleanup(0);
}

// ---------- 比对 ----------
let failed = 0;
for (const r of results) {
  const basePath = path.join(BASELINE_DIR, `${r.name}.png`);
  if (!existsSync(basePath)) {
    log(`⚠ ${r.name}: 基线缺失（新增截图？先 --update 生成并提交）`);
    failed++;
    continue;
  }
  const imgA = diffLibs.PNG.sync.read(readFileSync(basePath));
  const imgB = diffLibs.PNG.sync.read(readFileSync(r.shotPath));
  if (imgA.width !== imgB.width || imgA.height !== imgB.height) {
    log(`✗ ${r.name}: 尺寸不一致 baseline=${imgA.width}x${imgA.height} actual=${imgB.width}x${imgB.height}`);
    failed++;
    continue;
  }
  const diff = new diffLibs.PNG({ width: imgA.width, height: imgA.height });
  const diffPixels = diffLibs.pixelmatch(imgA.data, imgB.data, diff.data, imgA.width, imgA.height, { threshold: PIXEL_THRESHOLD });
  const ratio = diffPixels / (imgA.width * imgA.height);
  if (ratio > MAX_DIFF_RATIO) {
    const diffPath = path.join(DIFF_DIR, `${r.name}.diff.png`);
    writeFileSync(diffPath, diffLibs.PNG.sync.write(diff));
    log(`✗ ${r.name}: 差异 ${(ratio * 100).toFixed(2)}% > 阈值 ${(MAX_DIFF_RATIO * 100).toFixed(2)}%（差异图 ${path.relative(ROOT, diffPath)}）`);
    failed++;
  } else {
    log(`✓ ${r.name}: 差异 ${(ratio * 100).toFixed(2)}%`);
  }
}

if (failed) {
  console.error(`[visual] ${failed}/${results.length} 张截图与基线不符。若为预期变更：node scripts/visual-baseline.mjs --update 后提交基线。`);
  await cleanup(1);
}
log(`全部 ${results.length} 张截图与基线一致（platform=${PLATFORM}）`);
await cleanup(0);

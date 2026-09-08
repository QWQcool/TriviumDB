#!/usr/bin/env node
// TriviumDB WebUI 冒烟脚本 (ui-smoke)
//
// 目的：为内置 Web Console (crates/triviumdb-server/web/index.html) 提供一条
// 可重复执行的端到端冒烟路径。脚本不属于 CI —— 依赖本机 cargo 与 playwright，
// 两者任一缺失时打印提示并以退出码 0 跳过，保证 `node scripts/ui-smoke.mjs`
// 在任何开发机上都不会误报失败。
//
// 流程：
//   1. cargo build -p triviumdb-server（HTML 经 include_str! 编译内嵌，必须先构建）
//   2. 启动临时 server（独立端口 8081+ 探测空闲，--database .tmp/smoke.tdb 临时库）
//   3. 通过 /v1/tql 注入少量种子数据（默认 FIND {type:"person"} 查询才有结果行）
//   4. Playwright 打开 /ui：运行默认查询出结果 → 打开节点抽屉 → 依次切三个标签
//   5. 打开 /ui?selftest=1：断言页内自检套件 0 failed
//   6. 清理：关闭浏览器、杀掉 server 进程、删除临时库文件
//
// 用法：node scripts/ui-smoke.mjs
// 环境变量：SMOKE_BROWSER=chromium|firefox|webkit（默认 chromium）

import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP_DIR = path.join(ROOT, '.tmp');
const DB_PATH = path.join(TMP_DIR, 'smoke.tdb');
const BROWSER = process.env.SMOKE_BROWSER || 'chromium';
const PORT_CANDIDATES = [8081, 8082, 8083, 8084, 8085];
const EXE = process.platform === 'win32'
  ? path.join(ROOT, 'target', 'debug', 'triviumdb-server.exe')
  : path.join(ROOT, 'target', 'debug', 'triviumdb-server');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function log(msg) { console.log(`[ui-smoke] ${msg}`); }

// cargo 解析：优先 PATH，回退 ~/.cargo/bin（shell 环境未加载 rustup PATH 时仍可工作）
function resolveCargo() {
  const isWin = process.platform === 'win32';
  const exeName = isWin ? 'cargo.exe' : 'cargo';
  const probe = (cmd) => spawnSync(cmd, ['--version'], { encoding: 'utf8', shell: isWin });
  if (probe(exeName).status === 0) return exeName;
  const full = path.join(os.homedir(), '.cargo', 'bin', exeName);
  if (existsSync(full) && probe(`"${full}"`).status === 0) return full;
  return null;
}

// ---------- playwright 可用性探测（缺失则跳过，exit 0） ----------
async function loadPlaywright() {
  // 1) 项目本地 node_modules
  try {
    return await import('playwright');
  } catch (_) { /* fallthrough */ }
  // 2) 全局 npm root（npm i -g playwright）
  // 注意：Windows 下 npm 为 .cmd，Node 新版本要求 shell:true 才能启动（否则 EINVAL）
  const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const probe = spawnSync(npmCmd, ['root', '-g'], {
    encoding: 'utf8',
    shell: process.platform === 'win32',
  });
  if (probe.status === 0 && probe.stdout) {
    const globalRoot = probe.stdout.trim();
    const candidates = [
      path.join(globalRoot, 'noop.js'),
      // playwright-cli (@playwright/cli) 内嵌的 playwright 副本
      path.join(globalRoot, '@playwright', 'cli', 'node_modules', 'noop.js'),
    ];
    for (const base of candidates) {
      try {
        const requireFrom = createRequire(base);
        const pw = requireFrom('playwright');
        if (pw && pw.chromium) return pw;
      } catch (_) { /* try next */ }
    }
  }
  return null;
}

// ---------- 端口探测 ----------
function findFreePort(preferred) {
  return new Promise((resolve) => {
    const tryPort = (idx) => {
      if (idx >= PORT_CANDIDATES.length) { resolve(null); return; }
      const port = PORT_CANDIDATES[idx];
      const srv = net.createServer();
      srv.once('error', () => tryPort(idx + 1));
      srv.listen(port, '127.0.0.1', () => {
        srv.close(() => resolve(port));
      });
    };
    tryPort(preferred ? Math.max(0, PORT_CANDIDATES.indexOf(preferred)) : 0);
  });
}

// ---------- HTTP 助手 ----------
function request(method, urlPath, { body, headers } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      `http://127.0.0.1:${PORT}${urlPath}`,
      { method, headers: headers || {} },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          let json = null;
          try { json = JSON.parse(text); } catch (_) { /* keep null */ }
          resolve({ status: res.statusCode, json, text });
        });
      }
    );
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

async function waitForReady(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await request('GET', '/health/ready');
      if (res.status === 200 && res.json && res.json.status) return true;
    } catch (_) { /* server not up yet */ }
    await sleep(300);
  }
  return false;
}

// ---------- 清理 ----------
let serverProc = null;
let browser = null;
let cleaned = false;

function cleanup(exitCode) {
  if (cleaned) return;
  cleaned = true;
  try { if (browser) { browser.close(); } } catch (_) {}
  try { if (serverProc && serverProc.exitCode === null) { serverProc.kill(); } } catch (_) {}
  try {
    for (const suffix of ['', '-wal', '-shm', '-lock']) {
      rmSync(DB_PATH + suffix, { force: true });
    }
  } catch (_) {}
  process.exit(exitCode);
}

// ---------- 主流程 ----------
const playwright = await loadPlaywright();
if (!playwright) {
  log('playwright 不可用（未安装本地/全局包）。跳过冒烟测试 —— 这不是失败。');
  log('如需启用：npm i -D playwright && npx playwright install chromium');
  process.exit(0);
}

log(`1/6 cargo build -p triviumdb-server (browser=${BROWSER})`);
// 构建前停掉运行中的 triviumdb-server：exe 被进程占用会导致链接器报 os error 5。
// 注意：这会连带停掉本机其它端口上的 dev server，属冒烟脚本的既定行为。
const killCmd = process.platform === 'win32' ? 'taskkill' : 'pkill';
const killArgs = process.platform === 'win32' ? ['/F', '/IM', 'triviumdb-server.exe'] : ['triviumdb-server'];
const killed = spawnSync(killCmd, killArgs, { stdio: 'ignore', shell: process.platform === 'win32' });
if (killed.status === 0) {
  log('  已停掉运行中的 triviumdb-server 进程 (释放 exe 锁)');
  await sleep(500);
}
const cargoCmd = resolveCargo();
if (!cargoCmd) {
  console.error('[ui-smoke] 未找到 cargo（PATH 与 ~/.cargo/bin 均无）。请先安装 Rust 工具链。');
  process.exit(1);
}
const build = spawnSync(cargoCmd, ['build', '-p', 'triviumdb-server'], {
  cwd: ROOT, stdio: 'inherit',
  shell: process.platform === 'win32',
});
if (build.status !== 0) {
  console.error('[ui-smoke] cargo build 失败');
  process.exit(1);
}
if (!existsSync(EXE)) {
  console.error(`[ui-smoke] 未找到 server 可执行文件: ${EXE}`);
  process.exit(1);
}

const PORT = await findFreePort();
if (!PORT) {
  console.error('[ui-smoke] 8081-8085 端口均被占用，无法启动临时 server');
  process.exit(1);
}
const BASE = `http://127.0.0.1:${PORT}`;

log(`2/6 启动临时 server: 127.0.0.1:${PORT}, db=${DB_PATH}`);
mkdirSync(TMP_DIR, { recursive: true });
for (const suffix of ['', '-wal', '-shm']) rmSync(DB_PATH + suffix, { force: true });
serverProc = spawn(EXE, ['--dim', '4', '--database', DB_PATH, '--listen', `127.0.0.1:${PORT}`], {
  cwd: ROOT,
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverStderr = '';
serverProc.stderr.on('data', (d) => { serverStderr += d.toString(); });
serverProc.on('exit', (code) => {
  if (!cleaned && code !== 0 && code !== null) {
    console.error(`[ui-smoke] server 提前退出 (code=${code})\n${serverStderr.slice(-2000)}`);
    cleanup(1);
  }
});
process.on('SIGINT', () => cleanup(1));
process.on('SIGTERM', () => cleanup(1));

log('3/6 等待 /health/ready 就绪');
if (!(await waitForReady(30000))) {
  console.error('[ui-smoke] server 30s 内未就绪\n' + serverStderr.slice(-2000));
  cleanup(1);
}

log('3/6 注入种子数据 (2 个 person 节点 + 1 条 KNOWS 边)');
const seed = (query) => request('POST', '/v1/tql', {
  body: JSON.stringify({ query, mutation: true }),
  headers: { 'Content-Type': 'application/json' },
});
const seedRes = await seed('CREATE ({name: "Smoke Alice", type: "person", citations: 10})-[:KNOWS]->({name: "Smoke Bob", type: "person", citations: 20})');
if (seedRes.status !== 200) {
  console.error('[ui-smoke] 种子数据写入失败: ' + seedRes.text);
  cleanup(1);
}

let failures = 0;

try {
  log(`4/6 打开 ${BASE}/ui 执行冒烟路径`);
  browser = await playwright[BROWSER].launch();
  const page = await browser.newPage();
  page.on('pageerror', (err) => {
    console.error('[ui-smoke] 页面 JS 异常: ' + err.message);
  });

  await page.goto(`${BASE}/ui`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForSelector('#runQueryBtn', { timeout: 10000 });

  // 冒烟 1：运行默认查询，表格应出现结果行
  await page.click('#runQueryBtn');
  await page.waitForFunction(
    () => document.querySelectorAll('#gridBody tr').length >= 1
      && document.getElementById('statusRowCount').textContent.includes('返回: 2 行'),
    null, { timeout: 15000 }
  );
  log('  ✓ 默认查询出结果 (2 行)');

  // 冒烟 2：点击节点行打开 360° 抽屉
  await page.click('#gridBody tr.row-clickable');
  await page.waitForSelector('#nodeDrawer.open', { timeout: 5000 });
  const drawerPayload = await page.textContent('#drawerNodePayload');
  if (!drawerPayload.includes('Smoke Alice')) throw new Error('抽屉 Payload 应包含 Smoke Alice');
  await page.click('#closeDrawerBtn');
  // 关闭后 .open class 被移除（元素仍在 DOM），用 hidden 状态等待而非 detached
  await page.waitForSelector('#nodeDrawer.open', { state: 'hidden', timeout: 5000 });
  log('  ✓ 节点 360° 抽屉打开/关闭');

  // 冒烟 3：依次切换三个主标签
  for (const tabId of ['graphExplorePane', 'vectorLabPane', 'queryPane']) {
    await page.click(`[data-tab="${tabId}"]`);
    await page.waitForSelector(`#${tabId}.active`, { timeout: 5000 });
  }
  log('  ✓ 三个主标签切换');

  log(`5/6 打开 ${BASE}/ui?selftest=1 断言自检套件`);
  await page.goto(`${BASE}/ui?selftest=1`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForSelector('#selftestBar', { timeout: 15000 });
  await page.waitForFunction(() => window.__selftestDone === true, null, { timeout: 60000 });
  const selftest = await page.evaluate(() => ({
    failed: window.__selftestFailedCount,
    results: window.__selftestResults,
  }));
  for (const item of selftest.results) {
    const mark = item.status === 'pass' ? '✓' : '✗';
    log(`  ${mark} [${item.group}] ${item.name}${item.error ? ' — ' + item.error : ''}`);
  }
  if (selftest.failed !== 0) {
    console.error(`[ui-smoke] 页内自检存在 ${selftest.failed} 条失败`);
    failures += selftest.failed;
  } else {
    log(`  ✓ 页内自检全部通过 (${selftest.results.length} 条)`);
  }
} catch (err) {
  console.error('[ui-smoke] 冒烟失败: ' + (err && err.message ? err.message : String(err)));
  failures += 1;
} finally {
  log('6/6 清理浏览器进程 / server 进程 / 临时库');
  cleanup(failures === 0 ? 0 : 1);
}

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
//   2. 启动临时 server（独立端口 8081+ 探测空闲，--database .tmp/smoke-<pid>-<ts>.tdb 唯一临时库）
//   3. 通过 /v1/tql 注入少量种子数据（默认 FIND {type:"person"} 查询才有结果行）
//   4. Playwright 打开 /ui：运行默认查询出结果 → 打开节点抽屉 → 依次切三个标签
//   5. 打开 /ui?selftest=1：断言页内自检套件 0 failed
//   6. 清理：关闭浏览器、杀掉 server 进程、删除本轮临时库（删除失败的残留由下轮启动前清扫）
//
// 用法：node scripts/ui-smoke.mjs
// 环境变量：SMOKE_BROWSER=chromium|firefox|webkit（默认 chromium）

import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP_DIR = path.join(ROOT, '.tmp');
// 每轮使用唯一库名：即使上轮进程句柄释放延迟导致删除失败，残留脏库也不会污染本轮
// （数据在 WAL 中，同名库会被重放）；历史残留由启动前的清扫兜底删除
const DB_PATH = path.join(TMP_DIR, `smoke-${process.pid}-${Date.now()}.tdb`);
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

async function cleanup(exitCode) {
  if (cleaned) return;
  cleaned = true;
  try { if (browser) { await browser.close(); } } catch (_) {}
  if (serverProc && serverProc.exitCode === null) {
    try { serverProc.kill(); } catch (_) {}
    // Windows 下 kill() 是异步的：必须等进程真正退出、释放库文件句柄后才能删除临时库
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 5000);
      serverProc.once('exit', () => { clearTimeout(timer); resolve(); });
    });
  }
  // 临时库删除：进程退出后句柄可能仍被短暂占用（Windows 文件锁/杀软扫描），重试至多 15s；
  // 即使最终失败也不影响后续轮次（每轮库名唯一）
  let lastRmError = null;
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      for (const suffix of ['', '-wal', '-shm', '-lock']) {
        rmSync(DB_PATH + suffix, { force: true });
      }
      lastRmError = null;
      break;
    } catch (err) {
      lastRmError = err;
      await sleep(500);
    }
  }
  if (lastRmError) {
    console.error(`[ui-smoke] 警告：临时库删除失败 (${lastRmError.code || lastRmError.message})，残留文件将由下一轮启动前清扫`);
  }
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
// 清扫历史残留的 smoke-*.tdb*（上轮删除失败遗留；当前轮文件名唯一，互不影响）
try {
  for (const f of readdirSync(TMP_DIR)) {
    if (/^smoke-\d+-\d+\.tdb/.test(f)) {
      try { rmSync(path.join(TMP_DIR, f), { force: true }); } catch (_) { /* 被占用则留给下轮 */ }
    }
  }
} catch (_) { /* .tmp 可能尚不存在 */ }
serverProc = spawn(EXE, ['--dim', '4', '--database', DB_PATH, '--listen', `127.0.0.1:${PORT}`], {
  cwd: ROOT,
  // stdout/stderr 均需持续消费：管道缓冲区 (64KB) 一旦写满，server 会阻塞在日志写入上
  // （规模注入会产生大量逐请求日志，不消费就会把整个 server 卡死）
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverStdout = '';
serverProc.stdout.on('data', (d) => {
  serverStdout += d.toString();
  if (serverStdout.length > 200000) serverStdout = serverStdout.slice(-100000);
});
let serverStderr = '';
serverProc.stderr.on('data', (d) => { serverStderr += d.toString(); });
serverProc.on('exit', (code) => {
  if (!cleaned && code !== 0 && code !== null) {
    console.error(`[ui-smoke] server 提前退出 (code=${code})\n${serverStderr.slice(-2000)}\n${serverStdout.slice(-2000)}`);
    cleanup(1);
  }
});
process.on('SIGINT', () => cleanup(1));
process.on('SIGTERM', () => cleanup(1));

log('3/6 等待 /health/ready 就绪');
if (!(await waitForReady(30000))) {
  console.error('[ui-smoke] server 30s 内未就绪\n' + serverStderr.slice(-2000));
  await cleanup(1);
}

log('3/6 注入种子数据 (2 个 person 节点 + 1 条 KNOWS 边)');
const seed = (query) => request('POST', '/v1/tql', {
  body: JSON.stringify({ query, mutation: true }),
  headers: { 'Content-Type': 'application/json' },
});
const seedRes = await seed('CREATE ({name: "Smoke Alice", type: "person", citations: 10})-[:KNOWS]->({name: "Smoke Bob", type: "person", citations: 20})');
if (seedRes.status !== 200) {
  console.error('[ui-smoke] 种子数据写入失败: ' + seedRes.text);
  await cleanup(1);
}
// 种子生效性检查：唯一全新库中恰好应有 2 个 person
const probeRows = await request('POST', '/v1/tql', {
  body: JSON.stringify({ query: 'FIND {type: "person"} RETURN * LIMIT 100' }),
  headers: { 'Content-Type': 'application/json' },
});
const seededCount = (probeRows.json && probeRows.json.rows ? probeRows.json.rows.length : 0);
if (seededCount !== 2) {
  console.error(`[ui-smoke] 种子数据校验失败（person=${seededCount}，应为 2）`);
  await cleanup(1);
}

let failures = 0;
let page = null;

try {
  log(`4/6 打开 ${BASE}/ui 执行冒烟路径`);
  browser = await playwright[BROWSER].launch();
  page = await browser.newPage();
  page.on('pageerror', (err) => {
    console.error('[ui-smoke] 页面 JS 异常: ' + err.message);
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.error('[ui-smoke] 页面 console.error: ' + msg.text().slice(0, 300));
  });
  page.on('requestfailed', (r) => {
    console.error('[ui-smoke] 请求失败: ' + r.url() + ' — ' + (r.failure() && r.failure().errorText));
  });

  await page.goto(`${BASE}/ui`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  // 等待应用初始化完成（DOMContentLoaded 监听器全部挂载后再交互，避免竞态）
  await page.waitForFunction(() => window.__TRIVIUM_APP_READY === true, null, { timeout: 10000 });
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

  // 冒烟 4：图规模护栏 —— 注入 700 节点，用 LIMIT 500 的 MATCH 出图验证不冻结：
  // >300 节点应自动暂停力学模拟（O(n²) tick 护栏）并显示提示条
  log('  注入 700 个规模节点 (350 次链式 CREATE)');
  for (let i = 0; i < 350; i++) {
    const res = await seed(`CREATE ({name: "ScaleA${i}", type: "person"})-[:KNOWS]->({name: "ScaleB${i}", type: "person"})`);
    if (res.status !== 200) throw new Error(`规模种子写入失败 (i=${i}): ` + res.text);
  }
  await page.evaluate(() => {
    setEditorValue('MATCH (a)-[]->(b) RETURN a, b LIMIT 500');
  });
  await page.click('#runQueryBtn');
  // 351 行 = 1 条种子 KNOWS 边 + 350 条注入边（MATCH 按边返回行）
  await page.waitForFunction(
    () => document.getElementById('statusRowCount').textContent.includes('返回: 351 行'),
    null, { timeout: 15000 }
  );
  const guard = await page.evaluate(() => ({
    gridRows: document.querySelectorAll('#gridBody tr').length,
    physicsBtn: document.getElementById('togglePhysicsBtn').textContent,
    noticeHidden: document.getElementById('graphScaleNotice').hidden,
    noticeText: document.getElementById('graphScaleNotice').textContent,
  }));
  // 虚拟滑窗（PR-12）：351 行 > 阈值 200 → DOM 只渲染可视窗口（远小于数据量）
  if (guard.gridRows >= 100) throw new Error('351 行应走虚拟滑窗（tbody DOM 行数 < 100），实际 ' + guard.gridRows);
  if (guard.physicsBtn !== '恢复力学') throw new Error('700 节点应自动暂停力学（按钮应为「恢复力学」），实际: ' + guard.physicsBtn);
  if (guard.noticeHidden) throw new Error('图规模提示条应显示');
  if (!guard.noticeText.includes('300')) throw new Error('图规模提示条应说明 300 阈值: ' + guard.noticeText);
  log('  ✓ 图规模护栏生效 (700 节点 → 力学暂停 + 提示条，页面未冻结)');

  // 冒烟 5：虚拟滑窗滚动 —— 滚到中部后窗口行号/内容必须正确（spacer 换算与实测行距一致）
  await page.evaluate(() => {
    const c = document.getElementById('viewGrid');
    c.scrollTop = 3000;
    c.dispatchEvent(new Event('scroll'));
  });
  await page.waitForFunction(
    () => {
      const tr = document.querySelector('#gridBody tr[data-row-index="90"]');
      return tr && tr.children[0].textContent === '91' && tr.textContent.length > 5;
    },
    null, { timeout: 5000 }
  );
  log('  ✓ 虚拟滑窗滚动正确 (351 行窗口化，滚动后行号 91 / 内容一致)');

  log(`5/6 打开 ${BASE}/ui?selftest=1 断言自检套件`);
  await page.goto(`${BASE}/ui?selftest=1`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForFunction(() => window.__TRIVIUM_APP_READY === true, null, { timeout: 10000 });
  await page.waitForSelector('#selftestBar', { timeout: 15000 });
  // 边界加固断言含万行网格分块渲染与万元素 JSON 树懒渲染，整体预算放宽到 120s
  await page.waitForFunction(() => window.__selftestDone === true, null, { timeout: 120000 });
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
  // 失败时转储页面关键状态，便于远程定位
  try {
    if (page) {
      const dump = await page.evaluate(() => ({
        url: location.href,
        appReady: window.__TRIVIUM_APP_READY === true,
        statusRowCount: document.getElementById('statusRowCount')?.textContent,
        statusQueryTime: document.getElementById('statusQueryTime')?.textContent,
        gridRows: document.querySelectorAll('#gridBody tr').length,
        gridHead: document.getElementById('gridBody')?.textContent?.slice(0, 200),
        connText: document.getElementById('connText')?.textContent,
      }));
      console.error('[ui-smoke] 页面状态: ' + JSON.stringify(dump, null, 2));
    }
  } catch (_) { /* page may be gone */ }
  failures += 1;
} finally {
  log('6/6 清理浏览器进程 / server 进程 / 临时库');
  await cleanup(failures === 0 ? 0 : 1);
}

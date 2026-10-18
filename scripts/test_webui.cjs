// 运行内置控制台的浏览器自检；测试仅使用本地静态页和页内模拟接口。
const { readFile } = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const html = await readFile(path.join(__dirname, '../crates/triviumdb-server/web/index.html'));
  const server = http.createServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    response.end(html);
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
        ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
    });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    // 禁止外网请求，确认基础控制台及回归测试可完全离线运行。
    await page.route('**/*', route => {
      if (new URL(route.request().url()).hostname === '127.0.0.1') return route.continue();
      return route.abort();
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/?selftest=1`);
    await page.waitForFunction(() => window.__selftestDone === true, null, { timeout: 60000 });
    const results = await page.evaluate(() => window.__selftestResults);
    const failed = results.filter(result => result.status !== 'pass');
    for (const failure of failed) console.error(`失败：${failure.name}：${failure.error}`);
    for (const error of pageErrors) console.error(`页面异常：${error}`);
    console.log(`控制台自检：${results.length - failed.length} 项通过，${failed.length} 项失败`);
    if (failed.length || pageErrors.length) process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(`控制台自检运行失败：${error.message}`);
  process.exitCode = 1;
});

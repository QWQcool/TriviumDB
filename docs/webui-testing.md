# Web Console（WebUI）测试与验收

WebUI 位于 `crates/triviumdb-server/web/index.html`，由 Server 通过 `include_str!` 内嵌，修改页面后必须重新构建 Server。当前文档对应 0.8.10 集成与发布验收。

## 验证范围

| 层级 | 入口 | 验证内容 |
| --- | --- | --- |
| 服务端契约 | `cargo test -p triviumdb-server` | HTTP、TQL 与图探索 API |
| 页内自检 | `/ui?selftest=1` | `window.__selftestResults` 中的状态、解析、布局、流式与回归断言 |
| 浏览器冒烟 | `scripts/ui-smoke.mjs` | 临时真实数据库、种子数据、图探索、AI 模拟、查询与抽屉；Chromium/WebKit 各执行一次 |
| 视觉回归 | `scripts/visual-baseline.mjs` | 固定视口、确定性布局和平台对应 PNG 基线的实际像素比对 |

全量渲染、增量并图、邻域与路径共用真实边解析：不能根据同一行中的节点顺序猜测关系，边以起点、终点和标签去重，并保留权重及元数据。默认 1500 节点渲染上限覆盖所有入口，星云模式才可显式放宽。路径补齐请求保留完整 u64 ID，禁止通过 JavaScript `Number` 舍入。页内自检包含上述反例，以及 WebGL 平行边与精确路径高亮检查。

## 本地运行

浏览器测试依赖固定版本，保证本地与视觉 CI 使用相同浏览器构建：

```bash
npm i --no-save --ignore-scripts playwright@1.64.1 pixelmatch@8.0.0 pngjs@7.0.0
npx playwright install chromium webkit
node scripts/test_webui.cjs
node scripts/ui-smoke.mjs
SMOKE_BROWSER=webkit node scripts/ui-smoke.mjs
node scripts/visual-baseline.mjs
```

PowerShell 使用 `$env:SMOKE_BROWSER='webkit'` 设置引擎，运行后移除该环境变量。依赖缺失时脚本返回失败，不能把没有执行的检查算作通过。

冒烟脚本默认使用 `target/webui-tests` 独立构建目录；显式设置 `CARGO_TARGET_DIR` 时使用该目录。视觉脚本读取同一目录的 Server；也可以先运行：

```bash
cargo build -p triviumdb-server --target-dir target/webui-tests
```

两个脚本都只终止自己创建的子进程，每轮数据库位于 `.tmp` 内的独占目录，清理仅涉及该目录的直接子文件。不得使用 `taskkill /IM`、`pkill` 或扫描删除其他轮次数据库来处理可执行文件占用。

## 视觉基线

基线按平台分目录，当前仓库维护 `tests/visual/baseline/win32/`。WebUI workflow 使用 Windows runner，与基线平台对应。固定视口 1400×860、缩放 1、减少动态效果，默认排除依赖 GPU 的 Sigma 截图；单像素阈值为 0.2，允许差异像素比例为 1.5%。

```bash
node scripts/visual-baseline.mjs               # 强制比对，缺失基线或比对依赖时失败
node scripts/visual-baseline.mjs --update      # 显式生成当前平台基线，必须审阅后提交
node scripts/visual-baseline.mjs --record-only # 显式只截图，不代表视觉回归通过
node scripts/visual-baseline.mjs --with-sigma  # 本地额外验证 WebGL 导出
```

截图写入 `.tmp/visual-shots/`，差异图写入 `.tmp/visual-diff/`。workflow 无论成功或失败都会上传截图；手动 `update_baseline=true` 还会上传新基线。基线变更须说明原因，并实际查看截图，不能通过自动覆盖基线掩盖布局或语义回归。

## 发布前要求

WebUI 专项验证补充而不替代 `CONTRIBUTING.md` 的全工作区、Clippy、hook 套件和绑定检查。平台限制应在验收记录中如实说明，不得用某台机器的环境限制豁免全项目门禁。完整证据绑定具体提交，候选阶段不打正式 tag；正式 tag 只创建在通过验收的 master 发布提交上。

# nightly WebUI 开发诊断

Server 与 WebUI 处于 nightly 快速迭代阶段，布局、主题、交互和 HTTP 接口随开发调整。开发者按需要选择服务端自测、浏览器交互检查和截图记录。嵌入式 Core、Rust/Python/Node SDK 与 CLI 使用各自的正式验收流程。

WebUI 位于 `crates/triviumdb-server/web/index.html`，由 Server 通过 `include_str!` 内嵌，页面修改后重新构建 Server。

## 按需运行

| 工具 | 入口 | 用途 |
| --- | --- | --- |
| Server 自测 | `cargo test -p triviumdb-server` | 当前 HTTP、TQL 与图探索实现 |
| 页内自测 | `/ui?selftest=1` | 当前页面的状态与逻辑诊断 |
| 离线浏览器检查 | `node scripts/test_webui.cjs` | 页面自测与离线交互 |
| 端到端检查 | `node scripts/ui-smoke.mjs` | 临时 Server、种子数据和当前交互流程 |
| 截图记录 | `node scripts/visual-baseline.mjs` | 保存当前界面截图 |

浏览器工具的安装和运行：

```bash
npm i --no-save --ignore-scripts playwright@1.64.1 pixelmatch@8.0.0 pngjs@7.0.0
npx playwright install chromium webkit
cargo build -p triviumdb-server --target-dir target/webui-tests

node scripts/visual-baseline.mjs
node scripts/test_webui.cjs
node scripts/ui-smoke.mjs
SMOKE_BROWSER=webkit node scripts/ui-smoke.mjs
```

PowerShell 使用 `$env:SMOKE_BROWSER='webkit'` 选择引擎。脚本默认使用独立构建目录 `target/webui-tests`，也可通过 `CARGO_TARGET_DIR` 指定目录。

## 可选的截图比对

设计调整时可以直接记录新界面，需要对照某个参考设计时再显式选择比对或更新：

```bash
node scripts/visual-baseline.mjs --record-only
node scripts/visual-baseline.mjs --compare
node scripts/visual-baseline.mjs --update
node scripts/visual-baseline.mjs --with-sigma
```

参考图按平台放在 `tests/visual/baseline/<platform>/`。截图写入 `.tmp/visual-shots/`，显式比对产生的差异图写入 `.tmp/visual-diff/`。现有参考图用于开发对照，随设计演进维护或替换。

## 手动 workflow

Actions 中的 **Nightly WebUI Diagnostics** 通过 `workflow_dispatch` 手动运行。默认记录截图；`run_smoke` 选择是否执行当前页面的交互自测，`visual_mode` 选择记录、比对或更新参考图。产物随该次诊断上传。

常规 PR/push 与嵌入式 beta/stable 发布执行 Core、SDK 和 CLI 验收。Server 使用独立 workflow 与按需自测入口。界面重做时，开发者同步调整相关诊断脚本即可。

脚本创建独立临时数据库，仅清理自身创建的子进程与文件。

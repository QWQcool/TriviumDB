# Web Console（WebUI）测试方案

WebUI 是 `crates/triviumdb-server/web/index.html` **单文件**（经 `include_str!` 编译内嵌，改后必须 `cargo build -p triviumdb-server` 才生效），零构建链、原生 JS。本文说明它的四层验证体系与运行方式。

## 四层验证体系

| 层 | 载体 | 覆盖 | 运行 |
| --- | --- | --- | --- |
| ① 服务端契约 | `cargo test -p triviumdb-server` | HTTP 契约、TQL 行为 | `cargo test -p triviumdb-server` |
| ② 页内自检 | `index.html` 内 `?selftest=1` IIFE | 状态/逻辑：渲染管线、流式、过滤器、布局纯函数、星云、深链、AI mock SSE 等（100+ 断言） | 打开 `/ui?selftest=1`，读 `window.__selftestResults` |
| ③ 端到端冒烟 | `scripts/ui-smoke.mjs` | 真实 server + 种子数据 + 独立临时库：查询→抽屉→并图→规模护栏→虚拟滑窗→WebGL→AI→星云→统一面板，双引擎 | `node scripts/ui-smoke.mjs`（`SMOKE_BROWSER=webkit` 跑第二引擎） |
| ④ 视觉回归 | `scripts/visual-baseline.mjs` | 像素级：主题×画布底色、面板/弹窗布局、侧栏高亮等确定性截图与基线比对 | `node scripts/visual-baseline.mjs` |

**为什么需要第 ④ 层**：②③ 验证的是状态与逻辑，覆盖不了"像素与观感"。历史上已三次出现"断言全绿、肉眼不对"：浅色主题下边线不可见、退化向量/度数布局聚成一点、侧栏高亮不切换。视觉基线把这些回归钉在截图上。

## 依赖与安装（按需，不写入 package.json）

```bash
npm i --no-save playwright pixelmatch pngjs
npx playwright install chromium          # 需要 webkit 时：chromium webkit
```

三个脚本在依赖缺失时**优雅跳过**（退出码 0），不会阻塞无前端的开发环境。

## 视觉基线用法

```bash
node scripts/visual-baseline.mjs               # 比对（无本平台基线时自动降级为记录模式）
node scripts/visual-baseline.mjs --update      # 生成/更新本平台基线
node scripts/visual-baseline.mjs --record-only # 只截图不判定（CI 首轮）
node scripts/visual-baseline.mjs --with-sigma  # 额外拍 Sigma(WebGL) 图（本机专用）
```

设计要点：

- **确定性**：`reducedMotion: 'reduce'`（关闭 ambient 微动效/GSAP 过渡/CSS 动画）、固定视口 1400×860、`deviceScaleFactor: 1`、隐藏光标、清空 toast、只使用**确定性布局**（`radial` 为纯函数；`force` 因物理帧数依赖被排除；Sigma 因 GPU/驱动差异默认排除，需 `--with-sigma`）。
- **平台隔离**：基线按平台分目录（`tests/visual/baseline/<win32|linux|darwin>/`），跨平台字体/抗锯齿差异不会误报。某平台无基线时降级为记录模式（不失败），截图上传为 CI 产物。
- **容差**：`pixelmatch` 单像素阈值 0.2，允许差异像素占比 1.5%（结构性变化——布局塌陷、面板消失、主题反转——远超此值）。
- **失败产物**：差异图写入 `.tmp/visual-diff/*.diff.png`，CI 失败时自动上传。
- 基线更新属**预期变更**：`--update` 后提交 `tests/visual/baseline/` 下对应 PNG，并在 commit message 说明视觉变更原因。

## 新增页面功能时的检查清单

1. 在 `?selftest=1` 增加断言（状态/逻辑），并在 `scripts/ui-smoke.mjs` 增加端到端路径（若涉及真实数据流）。
2. 若改变视觉（布局、配色、面板结构），跑 `--update` 更新基线并在 commit message 说明。
3. 数据路径零 `innerHTML`；不使用 `window.confirm/alert/prompt`（内嵌 webview 会静默拒绝原生对话框——历史上导致"退出星云"点击无效）。
4. `[hidden]` 属性语义：`[hidden]{display:none!important}` 兜底存在，新增 flex 类不得绕过。
5. TQL 示例遵守语法约束：边模式匿名 `-[]->`、相等比较用 `==`、`FIND` 必须带过滤条件。

## CI

`.github/workflows/webui.yml` 在 WebUI 相关路径变更时运行：构建 server → 页内自检 + ui-smoke（chromium + webkit）→ 视觉基线比对。

- 首次在某平台启用视觉门禁：`workflow_dispatch` 勾选 `update_baseline=true` 运行，从产物下载基线并提交。
- 失败时上传 `.tmp/visual-shots/` 与 `.tmp/visual-diff/` 供定位。

## 本地 AV 环境注意（公司内网）

部分测试套件（`cargo test --workspace`、`fault-injection`、`fuzz`）在公司内网会被 AV 拦截（`fault_crash-*.exe` 被误判），本机请只跑 `cargo test -p triviumdb-server`，其余套件在 CI 或离线环境补跑。

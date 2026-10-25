# V4 工作区视觉统一：开发接续

用户已认可 V4 设计方向。当前交付为可交互设计参考，产品代码尚未应用 V4。
分支：`feature/webui-astrmira-theme`，fork：`QWQcool/TriviumDB`。

## 从这里开始

1. 阅读同目录 `V2-MAPPING.md`，尤其 §4 的不可重命名/删除测试锚点。
2. 打开 `v4-workspace-unification.html`，体验 TQL/向量、暗浅主题、中英文、五种状态和旧材质对照。
3. 按参考稿的 V4-A → V4-B → V4-C 分批实施，小步提交。

从仓库根启动预览（无需 Rust 编译、数据库或前端构建）：

```powershell
bun scripts/v4-preview.mjs
```

浏览器访问 <http://127.0.0.1:8894/v4>；服务只提供这一份 V4 原型，不提供仓库目录浏览。
端口占用时可先设置 `$env:V4_PREVIEW_PORT='8895'`。
该地址是当前电脑的本地预览，公司电脑需要重新运行脚本。
HTML 为独立文件，无外部字体、脚本或服务依赖；也可以自行在浏览器中打开。

## V4 实施范围

- **V4-A：基础材质与操作角色。** 暗色工作面从旧暖黑统一到冷色家族，浅色保留暖石。新增 action/on-action，成功色只表达成功状态；明确 data-theme 对应的 color-scheme。
- **V4-B：TQL 与向量工作区。** 编辑器、toolbar、结果表格/JSON、向量摘要/配置/结果区统一层级；修正空态字体、按钮强调关系与原生选择列表。
- **V4-C：状态与回归。** 检查未运行、零结果、加载、有结果、错误、选中、禁用、聚焦；审计 token 对图浮层、详情、对话与弹窗的影响。定稿后统一更新受影响的视觉基线。

先审计 token 的继承范围，再改组件；不要仅给截图红框加末尾覆盖规则。
参考稿中的数据、分数与响应均为 fixture，不是真实检索结果。
原型未完整模拟产品编辑器、图算法、表格虚拟化或服务器校验，实施时保留现有行为。

## V3 已完成的产品基点

产品代码基点是 `27175a9`，已经推送：

- `c57f29e`：窄屏保留加载全图/TQL 入图入口。
- `e5d2857`：小图力学、屏幕空间尺寸、命中与缩放边界，新增 `scripts/graph-scale-checks.mjs`。
- `27175a9`：刷新全部 9 张 win32 基线（含浅色 cockpit/dock），修正冒烟测试快照 ID。

V3-B 既有验收：9 节点星型覆盖率 54.76%，最近点对 147.81px；原种子拓扑覆盖率 52.63%，最近距离 211.09px。
normal 标签在 k=1/3/20 均为 11px；pill/边为 10px。
小于 60 节点的力学按规模调节，60+ 保留旧参数；fit 上限 3，手动倍率范围 0.05–20。
新 V4 不应重新修改这些渲染逻辑。

产品既有验证结果（2026-10-25 Windows）：cargo 11 单元 + 29 契约；selftest 136/136；ui-smoke 通过；9 张视觉基线复验最大差异 0.02%。
1009 节点自动暂停力学，可开详情；动效开启时 glow 为 15/6/0。
已知旧问题：动效关闭时 glow 是 18/8/8，V3 未改该函数。密集图标签优先级、自动面板相机跟随、分数命名和 FPS 表述另列，不混入 V4 视觉范围。

## 验证与本机依赖

V4 原型已经过 1440/1024/390 × 暗浅 × zh/en × 两页 × 五状态共 120 组合检查，无页面横向溢出或脚本错误，并完成代表性截图复核。
原型对比度初筛：主按钮最低 4.62:1，次级文字 6.07:1，输入轮廓 3.34:1；不等同于产品最终可访问性验收。

启动预览后，在第二个终端运行：

```powershell
bun scripts/v4-reference-checks.mjs
```

自定义端口时设置 `$env:TDB_V4_BASE='http://127.0.0.1:8895'`。
脚本需要可解析的 Playwright 包和已安装的 Chromium，复用仓库现有 UI 测试环境；此提交没有新增 package.json 或前端依赖。
旧电脑的 node_modules 是指向临时测试环境的目录联接，不会随 Git 搬到公司电脑。新电脑需准备自己的测试运行环境。
截图和检查数据输出到已忽略的 `.tmp/v4-preview/`，可以重建。

产品实施后再跑：

```powershell
cargo test -p triviumdb-server
bun scripts/ui-smoke.mjs
bun scripts/visual-baseline.mjs
```

`scripts/graph-scale-checks.mjs` 需另有已重建、正在运行的产品 server（默认 8080，可用 TDB_BASE 指定）。
历史 P1/light/detail 实机脚本位于旧电脑 Temp/pw-env，未纳入此提交；新电脑不能假定存在这些路径，可依据 V4 验收清单补齐同等实机检查。

Windows 上运行中的 triviumdb-server.exe 会锁住构建输出，cargo build/test 前先停止该进程。
产品 HTML 经 include_str! 嵌入，修改后必须重新 cargo build 才能实测新界面。
CARGO_TARGET_DIR 是本机缓存设置，应在新电脑上自行选择，不依赖旧电脑绝对路径。

## 保留的约束

- 产品前端仍是 `crates/triviumdb-server/web/index.html`；无前端打包流程，Sigma 继续 CDN 按需加载。
- 不删除/重命名 V2-MAPPING §4 锚点，新增产品文案同时进入 I18N/I18N_EXT 的 zh/en 字典。
- 不改 HTTP 契约、PCA、输入校验、检索分数算法或大图护栏。
- 原型检查与产品检查分开记录，不能把示例结果当作真实性能数据。
- 不调用 GitHub API 创建 PR/评论。PR 由用户全部审核后手动创建。
- 根目录 HANDOFF.md 无关；PR-DRAFT.md、WEBUI-HANDOFF.md 是旧电脑未跟踪素材。跨电脑以本说明和已提交设计稿接续。

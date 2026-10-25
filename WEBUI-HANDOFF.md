# TriviumDB WebUI 主题改造 — 交接文档（handoff）

> 生成时间：2026-10-24（当日实测核对，非记忆推断）；**2026-10-25 第二轮更新见文末 §10（§5 待办已全部完成）**
> 用途：把当前分支未完成的工作交接给另一个 AI 模型继续开发。
> 直接把本文件整段贴给下一个模型即可，它不需要看历史对话。
>
> ⚠️ 与仓库根目录的 `HANDOFF.md` 无关 —— 那份是 2026-08-23 的「性能对比文章」交接文档，不要混用、不要删除。

---

## 0. 当前状态快照（实测）

| 项 | 值 |
|---|---|
| 仓库 | `C:/Users/Administrator/Desktop/TriviumDB` |
| 上游 upstream | `https://github.com/YoKONCy/TriviumDB` |
| 我的 fork（origin） | `https://github.com/QWQcool/TriviumDB` |
| 当前分支 | `feature/webui-astrmira-theme` |
| HEAD | `373e79d1f9ad7f7bbc1d90281d68033f2df741de` |
| 远端同步 | ✅ `ls-remote origin feature/webui-astrmira-theme` = `373e79d`（已交叉验证，非看 `git status`） |
| 工作区 | 干净，只剩未跟踪文件（见 §6） |

最近 4 条提交：

```
373e79d feat(webui): 详情第四卡——向量空间投影（PCA 3D）      ← 本次交接的最新提交
c48585a feat(webui): 图视觉对齐 V2 蓝本（配色/边可见度/光晕/首屏适配/Sigma 尺寸）
e7882d9 feat(webui): finish vector summary and compact graph controls
cc4ad6c feat(webui): wire graph results, detail cards and in-place loading
```

---

## 1. 项目背景与硬约束（改代码前必读）

**目标**：把 fork 分支上的 Web Console 前端改造成 V2 视觉风格，验收通过后由**用户手动**提 PR 给**上游 `dev` 分支**。

> 🔴 **AI 禁止调用 GitHub API 创建 PR / 评论**。只负责准备好 PR 标题、正文（中文）、截图占位与 compare 链接，由用户在网页端操作。

**三条硬约束**：

1. **零构建 / 零 npm**：前端是单文件 `crates/triviumdb-server/web/index.html`（约 13,650 行），通过 Rust `include_str!` 内联进二进制。上游 0.8.6 的 release-validation 修复正是为了消灭构建步骤，**不得引入任何需要 npm install / 打包的依赖**。
   - 推论：Sigma.js 走 CDN（`cdn.jsdelivr.net`，实测直连 200）按需加载，加载失败自动回退 Canvas 渲染器并弹 toast。
2. **不得重命名 / 删除测试锚点**：见 `docs/design/webui-html-drafts/V2-MAPPING.md` §4，包括 `#tqlInput`、`#graphCanvas`、`#drawerNodePayload`、`#toggleWebGLBtn` 等。如需新增包裹层，**只包裹不替换**。
3. **双字典 i18n**：任何新增用户可见文案必须同时进 `I18N`（zh）与 `I18N_EXT`（en）。

**服务端接口面**（不要改动服务端契约，前端适配即可）：

- `POST /v1/tql`（写操作 body 需带 `"mutation": true`）
- `POST /v1/nodes/batch-get`（body `{"ids":[1,2,3]}`，返回含 `vector`）
- `GET /v1/nodes/{id}/neighbors`、`GET /v1/nodes/{id}/edges`
- `GET /v1/nodes/{from}/paths/to/{to}`
- `POST /v1/import/nodes`、`POST /v1/import/edges`（NDJSON，`Content-Type: application/x-ndjson`）
  - 节点字段：`{"id":1,"vector":[f32...],"payload":{...}}`
  - 边字段：`{"source":1,"target":2,"label":"KNOWS","weight":0.9}`

---

## 2. 各 Phase 进度

| Phase | 状态 | 说明 |
|---|---|---|
| 0 冻结蓝本 | ✅ | 6 份 HTML + V2-MAPPING.md；**唯一视觉蓝本 = `v2-hybrid-explorer.html`**（35,547 B） |
| 1 壳层 / 侧栏 / token | ✅ | 星尘侧栏、B 版选中态、暗浅 token |
| 2 图舞台 / HUD / 查询舱 / 抽屉骨架 | ✅ | **id 以 V2-MAPPING §3「实现名」列为准**，与蓝本命名有 5 处不同 |
| 3 Canvas 视觉 → Sigma 对齐 | 🟡 | 见下方「已知未解决差异」 |
| 4 详情四卡 | ✅ | Payload / Vector / Edges / **投影**（本次提交） |
| 5 响应式 / i18n / 降级 / 动效开关 | 🟡 | i18n、断点（1280/1100/900/700）、动效开关已完成；**390 宽度实机复核未做** |
| 6 selftest / ui-smoke / 视觉基线 | 🟡 | selftest 全绿；`ui-smoke` **未执行**；视觉基线**待重建** |

**Phase 3 已落地**：
- Canvas：未知类型哈希配色（暗/浅两套额外色板 + `graphTypeHash`）、边可见度（暗色 alpha `min(0.78, edgeAlpha+0.28)`、非路径线宽 1.5）、光晕（静态 selected 18 / 普通 8，带呼吸 ±3）、首屏自动适配
- Sigma：节点尺寸 `16*(1+min(degree,cap)*0.06)`、选中 20、边宽 1.5/1.0 与 Canvas 对齐，切换后自动 fit
- 首屏自动适配机制：`pendingGraphAutoFit` + `cameraTouchedByUser`；`simulationStep()` 收敛后调 `consumePendingAutoFit()`；`fitTransformToBBox` 缩放上限 3 → **1.6**；`computeGraphBBox` 加 **26px** margin（节点半径 + 选中环）

**Phase 3 已知未解决差异**（如需解决，是下一个模型的首要课题）：
1. Sigma WebGL 的边是**单色**，无法复刻 Canvas 的「源→目标渐变」
2. Sigma **无节点描边程序**（需额外依赖 `@sigma/node-border`，违反零新依赖约束）

---

## 3. 本次提交（373e79d）做了什么：详情第四卡「投影」

**动机**：前三卡（Payload / Vector / Edges）只能看到「连了谁」，看不到「在向量空间里离谁近」。第四卡把当前节点 + 1 跳邻居的向量 PCA 降维到 3 维，用固定轴测投影画出来。

**代码位置**（`crates/triviumdb-server/web/index.html`）：

| 行号 | 内容 |
|---|---|
| 1497 | CSS：`.inspector-plane:nth-of-type(4) { --plane-accent: var(--tri-vector); }` |
| 3020–3026 | DOM：`<section id="projectionCard">` + `<canvas id="drawerProjection" width=300 height=170>` + `<div id="projectionHint">` |
| 3525–3530 | zh i18n：`detail.projection` / `projectionHint` / `projectionMeta` / `projectionLoading` / `projectionEmpty` / `projectionFail` |
| 3835–3840 | en i18n（同上 6 条） |
| 9189–9190 | `openNodeDrawer()` 末尾调用 `loadNodeProjection(node.id)` |
| 9429–9435 | 模块状态：`__projectionSeq`、`__projectionPoints` |
| 9439–9488 | `pca3d(items)` |
| 9490–9571 | `drawProjection(items, positions, selectedId)` |
| 9573–9629 | `async loadNodeProjection(nodeId)` |
| 9631–9646 | `bindProjectionClick()` IIFE |
| 11571–11582 | 页内 selftest 断言「节点抽屉：投影卡 PCA 3D 渲染与空态清理」 |

**关键设计决策**：

1. **数据源选 `POST /v1/nodes/batch-get` 而非 N 次 `GET /v1/nodes/{id}`**
   一次请求取回自身 + 全部 1 跳邻居的 `vector`，避免读放大。点数上限 **20**（自身 + 19 邻居），防止大度节点把 PCA 拖垮。

2. **`pca3d()` 复用 `pca2d` 的算法血统**
   均值中心化 → 幂迭代（40 轮）→ 逐轴对已求出的轴做 Gram-Schmidt 正交化 → 归一化到半径 1。
   **退化保护**：
   - `vector.length < 3` 的向量直接剔除
   - 维度不一致的向量剔除（只保留与首个有效向量同维的）
   - 全部半径 `maxR < 1e-6` 时返回空 Map（所有点重合）

3. **`drawProjection()` 渲染层次**
   单位立方体线框（参考系）→ 自身到邻居的连线 → 按深度排序画点（painter's algorithm，用 alpha 表达远近）→ 选中节点加金色环 + `#id` 标注。空态走 i18n 文案 `detail.projectionEmpty`。

4. **`__projectionSeq` 序号守卫**
   快速连点不同节点时，过期响应直接丢弃（`if (seq !== __projectionSeq) return;`），避免错位渲染。这是本项目既有惯例（Edges 卡同样有序号守卫）。

5. **点击跳转**
   `bindProjectionClick()` 把鼠标坐标**归一化到 300×170 逻辑尺寸**再做命中判定，兼容 CSS 缩放。命中后调 `jumpToNode(hit.id)`。

---

## 4. 验证结果（2026-10-24 实测，可复现）

| 项 | 结果 |
|---|---|
| `cargo test -p triviumdb-server` | **11 单元 + 29 契约，全绿**（0 failed） |
| 页内 selftest `/ui?selftest=1` | **127 passed / 0 failed** |
| 实机截图 | 立方体线框 + 4 个投影点 + 金色选中环，提示文案 `PCA · 4 点 · 8 维` |

**踩过并已修的一个坑**：新增的 selftest 断言第一次跑失败（65 passed / 1 failed），原因是断言在异步 `batch-get` + PCA 完成前就读了 `projectionHint`。修法两条：
- `loadNodeProjection` 一开始就把 `__projectionPoints` 清空
- `waitFor` 的条件改成**同时**要求 `__projectionPoints.length > 0` **且** hint 含 `'PCA'`

> 下一位模型若新增异步断言，请直接套用这个模式。

---

## 5. 未完成清单（按优先级）

### P0 — 提 PR 前必须做

1. **删除 `docs/design/webui-gemini-draft/`（21 MB）**
   该目录的 `README.md` 明确写着「提 PR 前必须整体删除」，里面是 11 张设计参考图，属于临时素材，不能进上游。

2. **补齐/更新 PR 描述**
   标题建议：`feat(webui): Astrmira 主题改造（壳层/图视觉/详情四卡）`
   正文需含：变更概览、Phase 0–4 对应内容、验证结果（11+29 契约 / 127 selftest）、截图占位、已知差异（Phase 3 两条）。
   compare 链接：`https://github.com/YoKONCy/TriviumDB/compare/dev...QWQcool:TriviumDB:feature/webui-astrmira-theme`

### P1 — Phase 5 收尾

3. **390px 宽度实机复核**
   断点 1280/1100/900/700 已实现，但 390 只在代码层面处理，未在真实窄视口验证。验收门禁要求「1440 / 1024 / 390 无横向溢出」。
   建议：用 Edge headless 设 `--window-size=390,844` 截图检查。

4. **`prefers-reduced-motion` 下动效开关行为确认**
   `graphMotionBtn` 已实现，持久化键 `tdb_graph_motion`。需确认系统开启「减弱动效」时默认值正确、且门禁项「动效关闭后图节点 0 漂移」成立。

5. **大图 glow 降级阈值确认**
   门禁要求「大图 1k 节点可交互，glow 按规模降级」。`graphEdgeAlpha()` / `graphAuroraGlow` 有规模相关逻辑，但 1k 节点实测未做。

### P2 — Phase 6 收尾

6. **跑 `node scripts/ui-smoke.mjs`**
   **当前阻塞**：本机未装 Playwright，且 npm registry 不可达（直连与走代理均 000）。
   可行路线：
   - a) 换 npm 镜像源重试（已试 `registry.npmmirror.com`，失败）
   - b) 找一台能联网的机器 `npm i -D playwright` 后把 `node_modules` 拷回来
   - c) 用 Edge + CDP 自己写一个等价的 E2E 脚本（本会话已验证这条路可行，见 §7）

7. **重建视觉基线**
   `tests/visual/baseline/win32/` 下 7 张 PNG 是 Phase 3 改动**之前**的基线。门禁要求「视觉基线按 V2 重建，不沿用旧截图」。
   必须在 Phase 3 视觉定稿后重新生成：
   `00-sidebar-graph-active` / `01-light-canvas-radial` / `02-dark-canvas-radial` / `03-palette-open` / `04-panel-node-detail` / `05-panel-filter` / `06-tutorial-step8`

---

## 6. 工作区未跟踪文件（未提交，按需处理）

```
?? .dsh/                          Agent 记忆后端，本地用
?? .workbuddy/                    项目记忆/配置
?? HANDOFF.md                     ← 旧的「性能文章」交接文档，别动
?? articles/                      性能对比文章与图表
?? audit-report/                  审计/基准报告
?? scripts/run_fault_injection.ps1 / .sh
?? tests/doc_bench_probe.rs
?? tests/match_where_probe.rs
?? tests/pidx_find_probe.rs
?? tests/tql_bench083_probe.rs
```

探针文件（`tests/*_probe.rs`）是临时验证代码，历史上一直保持未跟踪，**不要提交**。

---

## 7. 本机环境坑（重跑必读）

| # | 坑 | 解法 |
|---|---|---|
| 1 | **git fetch/commit/push 后 ref 静默不落盘**（packed-refs 旧值不动、loose ref 不生成） | 手写修复：`mkdir -p .git/refs/remotes/origin/<子目录>`（**必须逐级 mkdir**），再 `printf '<完整40位SHA>\n' > .git/refs/remotes/origin/<b>`。**短 SHA 不解析**，必须写满 40 位 |
| 2 | **不要用 `git status -sb` 的 ahead/behind 判断同步状态** | 用 `git ls-remote origin <b>` 或 `gh api repos/<owner>/<repo>` 交叉验证 |
| 3 | **沙箱注入私有代理环境变量**（`https_proxy=http://127.0.0.1:59395` 等随机端口），git 底层 libcurl 会读它 → GitHub 返回 `CONNECT tunnel failed, 502` | 推拉前先 `env -u https_proxy -u HTTPS_PROXY -u http_proxy -u HTTP_PROXY -u all_proxy -u ALL_PROXY` |
| 4 | **GCM 凭据缺失**（`git-credential-manager.exe: No such file or directory`），`gh` 已登录 QWQcool | 用 `-c credential.helper='!gh auth git-credential'` |
| 5 | **push 可能被掐断**（curl 28/52/35） | 加 `-c http.version=HTTP/1.1 -c http.postBuffer=5242880`，超时给到 300s；直连失败就切 `-c http.proxy=http://127.0.0.1:10090` |
| 6 | **代理端口不定**：本机猫猫云 10090 与 Clash Verge 7897 都可能出现，且 10090 进程可能残留监听但隧道失效 | 用前先探测：`for p in 7897 10090; do curl -s -o /dev/null -w "%{http_code}" -x http://127.0.0.1:$p https://api.github.com --max-time 6; done`，取 200 的；全不通就直连 |
| 7 | **沙箱内 cargo 编译必炸**（锁文件/删 .rcgu.o 被拒） | `CARGO_TARGET_DIR="C:/Users/Administrator/AppData/Local/Temp/target_b2"` |
| 8 | **`triviumdb-server.exe` 被占用导致 build 失败**（`拒绝访问 os error 5`） | 先 `taskkill //F //IM triviumdb-server.exe` |
| 9 | **server 日志管道陷阱**：用 `... | head -20` 启动会关闭日志管道 → 进程阻塞 → `/ui` 大响应被截断（`ERR_INCOMPLETE_CHUNKED_ENCODING`） | 用后台任务启动 + `> server.log 2>&1`，保持输出被持续消费 |
| 10 | **TQL `CREATE` 报 `Expected MATCH...got Create`** | POST body 加 `"mutation": true` |
| 11 | **`FIND *` 非法**（`Expected LBrace, got Star`） | 用 `FIND {type: "person"}` |
| 12 | **无 Playwright 时的可视化验证** | Edge headless + CDP，见下方脚本 |

**Edge headless + CDP 方案（已验证可用）**：

```bash
# 1) 启动常驻 headless 实例（不要用 --screenshot + --virtual-time-budget，会崩）
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --headless=new --no-sandbox --no-proxy-server \
  --user-data-dir="C:/Users/Administrator/AppData/Local/Temp/tdb-ui-shots/edge-profile" \
  --remote-debugging-port=9223 --window-size=1600,1000 \
  "http://127.0.0.1:8080/ui?selftest=1"

# 2) Node 22 内置 WebSocket 驱动：/json/list → webSocketDebuggerUrl
#    → Page.navigate / Runtime.evaluate / Page.captureScreenshot
```

**复现验证环境的最小步骤**：

```bash
# 编译（务必设 CARGO_TARGET_DIR）
cd /c/Users/Administrator/Desktop/TriviumDB
CARGO_TARGET_DIR="C:/Users/Administrator/AppData/Local/Temp/target_b2" \
  cargo build -p triviumdb-server --bin triviumdb-server

# 启动（后台任务，输出持续消费）
cd /c/Users/Administrator/AppData/Local/Temp/tdb-ui-shots
triviumdb-server.exe --database db/ui.tdb --dim 8 > server.log 2>&1

# 灌种子数据（9 节点 8 维 + 8 边）
node seed_v3.mjs        # 脚本在 Temp/tdb-ui-shots/seed_v3.mjs

# 跑页内自检
node drive_selftest.mjs # 期望 127 passed / 0 failed
```

**当前临时脚本位置**：`C:/Users/Administrator/AppData/Local/Temp/tdb-ui-shots/`
（`seed_v3.mjs` 灌数据、`drive_selftest.mjs` 跑自检、`poll.mjs` 轮询）

> ⚠️ 该目录曾被部分清理过（早期 `seed.mjs` / `shoot.mjs` / `shoot2.mjs` / `shot_v2.mjs` / `selftest.mjs` 已丢失，`seed_v3.mjs` 与 `drive_selftest.mjs` 是本次重建的）。
> 若长期需要，建议把这两个脚本挪进仓库 `scripts/` 下，避免再次丢失。

---

## 8. 给下一位模型的开工提示词（可直接复制）

```text
你在继续一个已进行到一半的 Rust 项目前端改造任务。

项目：TriviumDB（AI 原生嵌入式数据库，Rust + napi），本地路径 C:/Users/Administrator/Desktop/TriviumDB
分支：feature/webui-astrmira-theme，HEAD = 373e79d，已同步到 fork 远端。
请先读 C:/Users/Administrator/Desktop/TriviumDB/WEBUI-HANDOFF.md 和
docs/design/webui-html-drafts/V2-MAPPING.md 了解全貌与设计蓝本。

任务：把 Web Console 前端改造为 V2 视觉风格，验收后由我手动提 PR 给上游
YoKONCy/TriviumDB 的 dev 分支。你不要调用 GitHub API 创建 PR。

硬约束（违反即返工）：
1. 零构建/零 npm。前端是单文件 crates/triviumdb-server/web/index.html，
   通过 Rust include_str! 内联，不得引入需要 npm install 或打包的依赖。
2. 不得重命名/删除 V2-MAPPING.md §4 列出的测试锚点 id。
3. 新增用户可见文案必须同时进 zh/en 双字典。
4. 不改服务端 HTTP 契约，只做前端适配。

当前进度：Phase 0/1/2/4 已完成，Phase 3/5/6 有残留。
未完成项（详见交接文档 §5）：
- [P0] 删除 docs/design/webui-gemini-draft/（21MB，其 README 要求提 PR 前删除）
- [P0] 准备 PR 标题/中文正文/截图占位/compare 链接
- [P1] 390px 宽度实机复核（门禁：1440/1024/390 无横向溢出）
- [P1] prefers-reduced-motion 下动效开关行为
- [P1] 1k 节点大图 glow 降级阈值
- [P2] 跑 node scripts/ui-smoke.mjs（本机缺 Playwright，npm 不可达）
- [P2] 重建 tests/visual/baseline/win32/ 下 7 张基线

验证基线（每次改动后必须复现）：
- cargo test -p triviumdb-server → 11 单元 + 29 契约全绿
- 页内自检 /ui?selftest=1 → 127 passed / 0 failed

环境坑：见交接文档 §7，尤其是 git ref 不落盘、沙箱代理需 env -u 清掉、
cargo 必须设 CARGO_TARGET_DIR、server 进程会锁 exe、日志管道别用 | head。

开工前先用 ls-remote 交叉验证远端状态，再告诉我你打算先做哪一项，等我确认。
```

---

## 9. 一句话总结

分支 `feature/webui-astrmira-theme` 已完成 V2 主题改造的主体（壳层/侧栏、图舞台、Canvas+Sigma 双渲染对齐、详情四卡含新增 PCA 三维投影卡），提交 `373e79d` 已推送到 fork，实测 11+29 契约测试与 127 条页内自检全绿；剩余工作是删掉 21MB 临时设计素材、补齐 PR 文案、以及 Phase 5/6 的三项实机复核与两条 E2E/基线重建。

---

## 10. 第二轮更新（2026-10-25，实测核对）

**§5 的 P0/P1/P2 待办已全部完成**，当前 HEAD = `0030130`，已推送并 ls-remote 交叉验证（远端=本地=tracking ref，无 §7.1 的 ref 不落盘问题）。本节信息优先于上文对应段落。

### 10.1 本轮新增提交（373e79d 之后）

| 提交 | 内容 |
|---|---|
| `fe2f584` | 删除 `docs/design/webui-gemini-draft/`（21MB 临时素材，净差异为零） |
| `c8fe4a0` | **合入 upstream/dev（0.8.11，7e0a468）**：上游对 `web/index.html` 只有 2 处版本号 0.8.10→0.8.11，合并时以 V2 主题版为准并吸收版本号更新。merge-tree 预演已无冲突，PR 可直接合并。注意：0.8.11 是在交接文档写成之后才出现在上游的 |
| `592cf76` | 390px 修复：≤700px 隐藏图探索工具栏的拖拽提示 span（此前被挤成逐字竖排贴边，390 实机截图发现的真缺陷） |
| `36520a4` | `tests/visual/baseline/win32/` 7 张基线按 V2 重建（`visual-baseline.mjs --update`），比对模式复验差异 ≤0.02% |
| `0030130` | `V2-MAPPING.md` §8 进度表：Phase 5/6 标记完成 |

### 10.2 验证结果（全部在 0030130 实测）

- `cargo test -p triviumdb-server`：11 单元 + 29 契约全绿（**测试前先 `taskkill //F //IM triviumdb-server.exe`**，8080 的 server 会锁 exe）
- `bun scripts/ui-smoke.mjs`：全流程通过（含 127/127 页内自检）——Playwright 已可用，见 10.3
- P1 实机（Playwright 脚本，25/25）：1440/1024/390 无横向溢出（默认+图视图带数据）；reduced-motion 默认关闭+按钮禁用+不误写 `tdb_graph_motion`；动效关闭后 96 点双采样 0 漂移；1009 节点可交互（抽屉正常、重绘 20ms、力学护栏+提示条），glow 降级实测：选中 15 / 枢纽(degree≥6) 6 / 普通 0（>300 阈值，>1500 全关）

### 10.3 本机环境变化（覆盖 §7 部分结论）

- **`env -u` 在本轮 shell 里静默失败**（连 `env -u X echo hi` 都无输出、退出码 0）——§7.3 的清代理法失效，改用子 shell `(unset VAR; ...)`。本轮 shell 根本没有代理变量，GitHub/npm registry 直连全通（api.github.com 200、registry.npmjs.org 200）
- **node 不在 PATH**（workbuddy 的 node 22.22.2 是死路径）。用 **bun**（WinGet，`bun --version` = 1.4.4）跑所有 .mjs；Playwright 在 bun 下工作正常
- **Playwright 已装好**：`C:/Users/Administrator/AppData/Local/Temp/pw-env/`（playwright@1.64.1 + pixelmatch@8.0.0 + pngjs@7.0.0 + chromium），仓库根有指向它的 `node_modules` 目录联接（node_modules 已 gitignore，不污染 git）。跑 ui-smoke/visual-baseline 时给 `CARGO_TARGET_DIR="C:/Users/Administrator/AppData/Local/Temp/target_b2"` 可复用缓存
- 推送仍需 `-c credential.helper='!gh auth git-credential' -c http.version=HTTP/1.1 -c http.postBuffer=5242880`；workbuddy PortableGit 的 GCM 报 No such file 是无害噪音
- P1/390 验证脚本：`C:/Users/Administrator/AppData/Local/Temp/pw-env/p1_checks.mjs`（25 断言）、`recheck390.mjs`；8080 验证库在 `Temp/tdb-ui-shots/db/ui.tdb`（含 9+1000 节点种子，`seed_v3.mjs`/`seed_1k.mjs` 可重灌）

### 10.4 剩余事项（仅剩人工步骤）

- **用户在网页端创建 PR**：标题/中文正文/截图占位全部备好于仓库根 `PR-DRAFT.md`（未跟踪，勿提交），compare 链接见该文件。AI 不得调用 GitHub API 创建 PR
- Phase 3 两条已知差异（Sigma 单色边、无节点描边）作为接受项写进了 PR 正文，留待上游 review 定夺
- 截图 5 张占位中 3 张可直接用 `tests/visual/baseline/win32/` 现图，390/1k 两张需实机（`Temp/tdb-ui-shots/p1-390-graph-fixed.png`、`p1-1k-graph.png` 可直接用）

---

## 11. 第三轮更新（2026-10-25 下午：浅色 C 阶段，实测核对）

用户决策：**暂不提 PR；浅色 C 在同一分支继续做，将来 V2 暗色 + 浅色 C 合成一个 PR**（已按此更新 PR-DRAFT.md）。当前 HEAD = `90a34bf`，已推送并三方验证（远端=本地=tracking）。

### 11.1 新增提交（0030130 之后）

| 提交 | 内容 |
|---|---|
| `5726a05` | **浅色 C（暖石）落地**：`[data-theme="light"]` token 换蓝本值（底 `#f3efe6`/面板 `#fbf9f4`/壳层 `#eee9dd`/实线边 `#ddd5c4`·`#c8c0ad`/文字 `#242018`/金 `#9e7f47`）；Canvas 浅色舞台 34px 暖石网格 + Sigma 容器 CSS 网格一致；浅色节点粉彩→足饱和三模色（person `#4d7c78`/paper `#8c764e`/topic `#645680`/user `#9e7f47` + 6 色扩展盘）；选中环金 `#9e7f47`；标签 Halo 3→3.4px；selftest 新增「浅色 C 暖石」断言（**127→128**）；7 张基线随之重建 |
| `90a34bf` | V2-MAPPING §7 改为「浅色 C 已落地」记录 |

### 11.2 验证（全部在 90a34bf 实测）

cargo test 11+29 全绿；ui-smoke 全流程通过（含 selftest 128/128）；浅色三宽度（1440/1024/390×默认/图视图）10/10 无溢出无异常；基线比对模式复验 ≤0.02%；浅色画布与详情截图经视觉复核（暖石网格/饱和三色/白 Halo/边线/四卡全部确认）。验证脚本：`Temp/pw-env/light_checks.mjs`。

### 11.3 剩余事项

- 用户手动建 PR（单一 PR：暗色 V2 + 浅色 C），素材在 `PR-DRAFT.md`（已更新为合并口径，标题含「暖石浅色」）
- Phase 3 两条已知差异不变（接受项，已写入 PR 正文）
- 蓝本 `warm-stone-light.html` 的其余元素（顶栏 seg 胶囊、layout-bar 白胶囊）与现有 V2 壳层组件已视觉同源，未逐像素复刻——按 V2-MAPPING「蓝本是唯一视觉蓝本但不照搬」原则处理

---

## 12. 第四轮更新（2026-10-25 晚：V2 细节收敛，对照 v2-hybrid-explorer 蓝本）

用户决策：**PR 继续押后，等全部计划完成、用户亲自审核后再提**（单一 PR：V2 暗色 + 浅色 C + 细节收敛）。当前 HEAD = `da84de8`，已推送三方验证。

### 12.1 本轮补齐的 6 项蓝本差距（提交 da84de8）

查询舱 KNN（`SEARCH VECTOR` 走 `POST /v1/search/vector`，二进制 f32；**引擎分数是内部融合分非 0~1 余弦，UI 按批内最高分归一**，阈值滑杆客户端过滤）/ 命中列表接线 / 抽屉 6 列（类型胶囊+关联边+相似度渐变条）/ 脉冲扩散环（运行+路径追踪，动效关时不触发）/ 边标签沿边旋转 / 查询舱语法高亮 overlay+预览同步 / 聚类星云虚线环。细节清单见 V2-MAPPING §8「V2 细节收敛」。

### 12.2 验证（da84de8 实测）

selftest **132/132**（+4 组）；cargo 11+29；ui-smoke 全绿；p1 **25/25**；浅色 10/10；基线重建复验 ≤0.02%；KNN 查询舱/聚类环截图经视觉复核。验证脚本新增 `Temp/pw-env/v2_detail_checks.mjs`（8 断言）。

### 12.3 本轮踩的三个坑（重跑必读）

1. **引擎 `/v1/search/vector` 的 score 不是 cosine**：实测平行向量 3.0 / 正交 ~1.15，量纲随数据形态变化（内部融合分）。任何 UI 展示都要归一化，别假设 0~1。
2. **p1 C3「0 漂移」原为 flaky**：固定墙钟采样撞上力学未冻结窗口（收敛时长随帧率变化）。已改为「等 `simulationRafId === null`（reduce 短路）+ `polling: 500`」——注意 `waitForFunction` 默认 rAF 轮询在页面静止后会饿死；且顶层 `let` 变量**不挂 window**，`window.simulationRafId` 是 undefined。
3. `highlightTql` 输出 `tk-keyword/tk-string/tk-number` 类（不是 kw/str）。

### 12.4 剩余差距（蓝本对照，仅 2 条已知接受项）

Sigma WebGL 单色边（无源→目标渐变）、Sigma 无节点描边——均因零新依赖约束接受，已写入 PR-DRAFT。**蓝本其余可执行项全部补齐**；下一步等用户审核（可实机过一遍 /ui），或继续上游同步。

---

## 13. 第五轮更新（2026-10-25 深夜：V3 精修进行中，交接给下一位 AI）

**新蓝本**：`docs/design/webui-html-drafts/v3-refinement-details.html`（584 行施工图：10 个小节 A–H + 勿误改清单 + 验收门禁，含每项的实测证据/目标 SVG/验收规格/实施顺序建议）。**用户决策：PR 继续押后，全部完工并用户亲自审核后再手动提交**。

### 13.1 当前进度（HEAD = 858f940，已推送三方验证）

| V3 项 | 状态 | 提交 |
|---|---|---|
| A 浅色舞台浮层暖石适配 | ✅ | 7c6445d（`[data-theme="light"]` 作用域覆盖 cockpit/dock/布局条/HUD/更多菜单，computed 实测 rgba(251,249,244,.94)，截图视觉复核通过） |
| E 面板让位方案② | ✅ | 858f940（panel-open 下 cockpit left −188px / dock·more-menu right 388px / 布局条 −188px；selftest 断言用 computed left/right 而非 rect——cockpit width 有 180ms transition，rect 会读到中间态） |
| C 右上 HUD 收敛 | ✅ | 858f940（两视图 float-toolbar 改横排：＋/－/适合窗口/+星云 或 并入图探索；导出/全屏/动效收进「更多」菜单；id 全部保留） |
| D 工具条收纳 | ✅ | 858f940（加载全图/TQL 入图迁入左上 HUD（新键 graph.hud.loadWhole/graph.tqlIn）；拖拽提示改首次一次性 toast；删除 editor-toolbar 整条，舞台顶部省 ~46px；视图 tab 行按用户决策保留） |
| F 查询舱空态 | ✅ | 858f940（null=「未运行」图标占位 graph.cockpit.idle；{summary}=运行无命中摘要；两态区分 zh/en） |
| G Payload 8 行 | ✅ | 858f940（max-height 220→168、阈值同步 168；扩展邻域/khop/路径追踪操作区从 Edges 卡上移到 Payload 卡底部，id 不变） |
| H 文案/状态栏 | ✅ | 858f940（聚类→星云聚类；后端钮双态显示当前后端（syncBackendButtons 语义反转：sigma→'WebGL 渲染'/canvas→'Canvas 渲染'）；状态栏新增 statusGraphInfo（图: N 节点 · M 边 · 后端 · FPS 估算，仅探索 tab 显示，redrawGraph 驱动）） |
| B 小图密度+屏幕空间标签 | ❌ 未做 | 按蓝本建议最后做（会改所有图视图截图） |

### 13.2 本轮新增坑（覆盖前文）

1. selftest 断言读 cockpit/dock 位置：**用 computed left/right，别用 getBoundingClientRect**（width transition 中间态）；且断言前先 `collapseUnifiedPanel()` 复位（前序断言会遗留 panel-open）。
2. `openNodeDrawer` 在 selftest 里打开面板后**不自动收起**，会影响后续布局断言。
3. sed 改 index.html 后文件 mtime 变化会导致 Edit 工具报 stale——用 Read 重刷再编辑。
4. i18n 断言引用 `#loadWholeGraphBtn [data-i18n=...]` 内层 span 的两处已改为直接断言按钮 textContent（按钮结构已改为整钮 data-i18n）。

### 13.3 下一步（接手者从这里开始）

1. **第 5 批 B**（唯一未做项）：小图力学按规模缩放（<60 节点 springLength 130→~220、提高 repulsion，<9400 或按目标屏幕边长 ≥90px 反推）+ 标签/半径/选中环改屏幕空间尺寸（绘制时除以 k）+ fitTransformToBBox 上限 1.6→2.4~3。验收：9 节点 bbox 覆盖率 ≥45%（当前 <7%）、相邻节点屏幕距 ≥90px、放大上限标签仍 11px 视觉大小、1k 大图护栏不回退。**单独小步，做完一次性重建全部基线**。
2. 蓝本 §H 剩余可选项：顶栏 QuIVer pill 提升（可选）；投影卡标注保留 PCA 不换 UMAP（明确不要改）。
3. 全部完成后按 v3 蓝本「验收」节过门禁：cargo 11+29 / selftest 134+（B 批需新增屏幕空间字号断言）/ ui-smoke / 三宽度无溢出 / 0 漂移 / 基线重建（含新增浅色浮层 2 张：light cockpit、light dock）/ console 0 error。
4. 然后**停手等用户实机审核**，用户通过后由用户手动建 PR（素材 PR-DRAFT.md 需刷新到最终状态）。**不要催 PR，不要调 GitHub API。**

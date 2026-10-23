


A. 现状审计（架构层级总结 + 3 优点 + 5 具体问题）
0. 信息架构与视觉层级总结
基於 feature/webui-astrmira-theme 分支的 index.html 单文件架构与 ui-smoke.mjs 交互基线，当前 TriviumDB WebUI 采用典型的 桌面端四区固定工作台（Four-Zone Workbench） 结合 三模语义映射（Tri-Model Semantic Mapping）：

+-----------------------------------------------------------------------------------+
| 顶栏 Topbar (40px): 品牌字标 TriviumDB | 核心视图切换 | 全局状态 Pill | 主题/语言 |
+------------------+---------------------------------------------+------------------+
| 左侧对象导航     | 中央主工作区 Center Stage                   | 右侧统一面板     |
| Left Nav (240px) | +-----------------------------------------+ | Right Inspector  |
| - 文档 Document  | | 上下文工具栏 Toolbar (36-40px)          | | (360px, 可折叠)  |
| - 图拓扑 Graph   | | [运行] [写入模式] [剖析] | 视图切换胶囊 | | Tabs:            |
| - 常用代码片段   | +-----------------------------------------+ | [节点详情]       |
| - 查询历史       | | TQL 编辑器 (暗冷色槽 #101215)           | | [过滤器]         |
|                  | +-----------------------------------------+ | [AI 助手]        |
|                  | | 结果容器 Result Card (18px 圆角, #191713)| | - Payload (折叠) |
|                  | | - 表格视图 / 交互拓扑图 / JSON 视图     | | - Vector (热力)  |
|                  | | - 底部浮动图控制条 (仅拓扑图激活)       | | - Edges & 迷你图 |
+------------------+---------------------------------------------+------------------+
| 底部状态栏 Status Bar (24px, Mono 字体): 引擎状态 | WebGL/Canvas | 耗时 | 节点数  |
+-----------------------------------------------------------------------------------+
Z 轴视觉层级（由底向顶）：

L0 画布底层（Canvas Void）：暗色 #070806 / 浅色 #f4f1ea，承载 WebGL/Canvas 拓扑图与主工作区背景。

L1 框架壳层（App Shell）：暗色 #0b0a08，承载左侧对象导航、顶栏、底栏与右侧统一面板基底。

L2 内凹数据槽（Code & Data Well）：暗色 #101215，用于 TQL 编辑器、代码块与输入框内胆，通过微弱内阴影体现“输入槽”深度。

L3 抬升卡片与浮层（Elevated Surface & Floating HUD）：暗色 #191713 / 浅色 #fbf9f5，用于 18px 圆角结果大卡、12px 详情子卡、右上浮动工具条、底部图控制条及 Ctrl+K 命令面板。

L4 语义高亮与焦点层（Semantic & Focus）：主强调金 #b8a06f（主操作/选中态）、三模色（Vector #8fb3b0、Graph #9589ad、Payload #c6b9a0）及 2px 青灰焦点环。

1. 当前设计做得好的 3 点
克制的“矿物星尘”三模语义色彩系统：
摒弃了传统数据库管理台常见的高饱和霓虹色，采用低明度、低彩度的矿物色系——向量青（#8fb3b0）、图谱紫（#9589ad）、文档沙金（#c6b9a0）搭配主强调暖金（#b8a06f）。在 #070806 暖黑基底上既能一眼区分三模数据属性，又在 DBA 与算法工程师长时间盯屏时大幅降低视觉疲劳。

去噪的中文工程化微文案与严格的字体职能边界：
清理了早期版本冗余的“中文（English）”双语括号堆砌，仅在 TQL、JSON、WebGL、QuIVer、Top-K 等行业原语上保留英文；同时建立了清晰的字体契约——系统无衬线字体负责高频 UI 交互，Monospace 严格限定于底部状态栏、表格列头、耗时与维度微标签，Serif 仅在空态引导与 8 步教程中点缀人文气质，信息信噪比极高。

反“营销噱头”的微交互与图渲染性能纪律：
严格执行 150ms 干脆过渡（按钮 hover 上浮 1px 配合青灰边框、active 缩放 0.98），全面禁止常驻呼吸灯、无限发光与每帧节点随机漂移；同时在浅色模式拓扑图中引入了随节点/边密度动态衰减的边线透明度机制（#5f523b, alpha 0.82 → 0.58），有效避免了稠密子图糊成一团的常见图可视化通病。

2. 当前存在的 5 个具体问题（定位到页面 / 组件 / 状态）
【TQL 查询控制台 / 编辑器与结果卡交界】冷暖材质色温断层导致容器割裂：
:root 中主壳层与结果卡均采用偏暖褐炭色（#070806 / #0b0a08 / #191713），唯独 TQL 编辑器与部分内胆面板使用了冷蓝灰 #101215。当 TQL 编辑器与下方 18px 圆角的 #191713 结果卡上下紧邻时，冷蓝与暖褐在 1px 边框处产生明显的色相冲撞，削弱了星尘主题的整体矿物感。

【独立图探索器 / 底部布局控制条 / 双侧栏展开态】1440px 视口下水平空间不足导致折行遮挡：
当左侧对象导航（240px）与右侧统一面板（360px）同时打开时，中央图画布仅剩约 840px 净宽。此时底部浮动控制条内塞入了“渲染后端（Canvas/WebGL）”、“4 种布局切换（力导向/聚类/向量星图/度数径向）”、“星云模式”、“k-hop 邻域步数”及“路径追踪”共十余个胶囊控件，触发双行甚至三行折叠，直接遮挡画布下半区近 110px 的拓扑节点。

【右侧统一面板 / 节点详情 Tab / 展开态】Payload、Vector、Edges 与邻居迷你图四层信息缺乏视觉锚点与折叠契约：
选中复合节点后，右侧 360px 面板内的 Payload（多级 JSON）、Vector（数百维浮点数组与预览条）、Edges（出入边列表）和 邻居迷你图 全部使用同质化的 12px 圆角灰底卡片纵向堆叠。缺少左侧三模语义色条（3px indicator）区分模块属性，且缺少粘性子标题（Sticky Section Header）与默认行数截断，当 Payload 字段超过 15 行时，用户必须频繁长距离滚动才能看到底部的 Edges 与 邻居迷你图。

【交互拓扑图 / 浅色模式（Light Mode）/ 稠密图状态】节点文字标签与深金棕边线粘连，且三模色在暖白底上对比度不足：
浅色模式（#f4f1ea 底）下边线采用 #5f523b（alpha 0.58~0.82），当多条边线穿过节点附近时，深色节点文字标签因缺少 2px 暖白描边衬底（Text Halo / Pill Backdrop）而与边线笔画交织难辨；同时原暗色模式的三模色（#8fb3b0 / #9589ad / #c6b9a0）明度过高（L* 均大于 60%），直接用于浅色画布节点或 #fbf9f5 卡片内的状态 Pill 文本时，对比度仅约 2.1:1~2.8:1，低于 WCAG AA（4.5:1）可读标准。

【向量检索实验台 / 查询区与结果表】高维向量输入区纵向失控，且结果表缺少视觉化距离标尺：
向量实验台顶部将“来源选择”、“Top-K”与“查询向量输入框”上下平铺，当粘贴 768 或 1536 维浮点向量时，文本框撑高并把下方结果表挤出首屏；同时结果表中的相似度/距离列仅渲染了单调的 Mono 浮点数（如 0.8942），未与顶部的向量热力条及 #8fb3b0 向量主题色形成内联数据条（Inline Score Bar）联动，肉眼难以快速扫视 Top-K 梯队断层。

B. 3 个设计方向与推荐方案
维度	方向 1：Astrmira Obsidian（星尘黑曜 · 矿物精密台）	方向 2：Graphite Lab（石墨实验室 · 极客冷峻风）	方向 3：Warm Parchment（暖羊皮纸 · 知识图谱工坊）
一句话气质	深空暖黑曜石基底与低饱和矿物三模色交织的重型精密数据库仪器。	纯中性冷石墨灰搭配高锐度细线与工业仪表盘感的极速开发台。	以暖白羊皮纸与深棕铜版画墨线为核心的高可读性图谱与文档分析台。
主色与材质	暗色暖炭黑 #070806 / #0b0a08，将原冷灰槽修正为深玄武岩 #111110；卡片 #191713 配 1px 暖白 8% 微边框；强调金 #b8a06f；浅色镜像为暖砂岩 #f4f1ea。	纯灰阶 #090a0c / #111317 / #181b20；边框 #262930；主强调色改为冷青蓝 #5ea8a0，三模色提亮彩度 15%。	默认以 #f4f1ea / #fbf9f5 暖纸底为主视角，边框采用 #ded8cc 实线，图边线 #5f523b，强调色为古铜金 #8c6d3b。
字体与排版	Inter / PingFang SC 负责 UI；JetBrains Mono 负责 TQL、向量维度、耗时与表头；Newsreader / 宋体衬线仅用于空态与教程标题。字重对比克制（400/500/600）。	全局紧凑无衬线 + 大比例等宽字体（Mono 占比超 45%），全部取消衬线体，字号整体下调 0.5px。	标题与节点详情键值强化衬线/人文无衬线混排，正文行高放宽至 1.6，弱化代码感，强化文档阅读感。
信息密度	高密度可控（Compact-Pro）：32px 控件高，34px 表格行高，折叠式二级工具条。	极限高密度（Ultra-Dense）：28px 控件高，28px 表格行高，全边框网格化（Grid-line）。	舒展中密度（Comfortable）：36px 控件高，40px 表格行高，大量留白与卡片内边距。
解决的核心问题	
1. 修正 #101215 冷暖断层；


2. 收纳图探索器底部双层控制条；


3. 建立右侧节点详情三模色锚点与浅色高对比度映射。

解决底部工具条拥挤与高密度表格展示，但会彻底丢失当前分支独特的“星尘暖黑”品牌辨识度。	重点解决浅色模式图边线对比度与长文档 Payload 阅读体验，但削弱了向量检索与底层引擎的性能感。
推荐方向：方向 1 — Astrmira Obsidian（星尘黑曜 · 矿物精密台，含高对比度浅色镜像）
推荐理由：

架构与资产继承度最高：完全贴合 feature/webui-astrmira-theme 既有的色彩基因（#070806 基底、#b8a06f 金与三模矿物色），无需推翻现有 CSS 变量体系，只需微调冷灰槽色值（#101215 → #11110f）并补充浅色模式下的深色语义变量即可平滑落地。

精准攻克 5 大痛点：通过“主副分段式底部 HUD 控制条”解决 840px 画布换行；通过“左边框三模色条 + 粘性折叠头”重构右侧 360px 节点详情；通过“浅色模式节点文本 2px 暖白 Halo + 深色三模 Token”彻底解决浅色拓扑图可读性。

B 端专业度与差异化兼具：既保持了硬核数据库控制台的冷静与高信息密度，又避开了市面上千篇一律的紫蓝渐变 SaaS 模板与过度发光动效。

C. 推荐方向的设计参考图（6 张核心图 + 2 张进阶图）
说明：以下为 Astrmira Obsidian 方向的完整视觉规范与分镜。每张图均包含：① 空间构图线框（ASCII 布局基准）、② 可直接用于高精 UI 渲染模型的英文提示词（含精确色值、尺寸、组件与防幻觉约束），以及 ③ 图内中英标签对照与视觉层级拆解。

图 1：桌面暗色 1440×900 — TQL 查询控制台（TQL Query Console）
+----------------------------------------------------------------------------------------+
| ● TriviumDB  [TQL 查询控制台*] [独立图探索器] [向量检索]    [WebGL: 就绪] [中文] [◐]  | 40px
+-------------------+------------------------------------------------+-------------------+
| 对象导航          | [▶ 运行 (Ctrl+Enter)] [写入模式 ○] [剖析]      | [节点详情*] [过滤] | 38px
| [搜索对象...   ]  |                        [表格视图*][交互拓扑][JSON]| [AI 助手]          |
|                   +------------------------------------------------+-------------------+
| ▾ 文档 (12.4k)    | 1 | MATCH (u:User)-[r:PURCHASED]->(p:Product)  | 选中对象: u:User  |
|   ● users         | 2 | WHERE VECTOR_SIM(p.embedding, $q) > 0.82   | ID: usr_9042_xk   |
|   ● articles      | 3 | RETURN u.id, p.title, r.weight, p.vec      |-------------------|
| ▾ 图拓扑 (38.1k)  | 4 | LIMIT 6;                                   | ▾ Payload [文档]  |
|   ◆ FOLLOWS       +------------------------------------------------+   role: "architect"|
|   ◆ CITATION      | 结果卡片 (18px radius, #191713)      6 rows    |   tier: 3         |
| ▾ 常用代码片段    | #  | _id         | title      | weight | vec   |-------------------|
|   › 混合图向量查询| 01 | doc_8821_a  | Graph Core | 0.94   | [██▓░]| ▾ Vector [768d]   |
| ▾ 查询历史        | 02 | doc_3109_b  | HNSW Index | 0.91   | [██░░]|   ||I|l||I|ll|I|| |
|   › 14:20 MATCH...| 03~06 (共 6 行紧凑数据，含三模胶囊标签)        |-------------------|
|                   |                                                | ▾ Edges & 邻居图  |
+-------------------+------------------------------------------------+-------------------+
| ● READY | 引擎: QuIVer-0.4 | 耗时: 4.2ms | 扫描: 1,024 | 返回: 6 行 | 内存: 412 MB     | 24px
+----------------------------------------------------------------------------------------+
English Image Generation Prompt:

Plaintext
High-precision desktop B2B database console UI design, "TriviumDB", 1440x900 resolution, 16:10 aspect ratio, 2x Retina clarity, Astrmira Obsidian dark theme. Flat vector UI screenshot, zero 3D perspective, no marketing hero, no neon purple/blue gradients, no glassmorphism blur stack.
Color Palette: Deep warm obsidian background #070806, sidebar and topbar surface #0b0a08, code editor recessed well #11110f, elevated result card #191713 with 18px border-radius and 1px subtle border rgba(244,238,228,0.08). Primary text #f4eee4, secondary text #b9bdb6, muted text #8f958e. Tri-model semantic accents: Vector teal #8fb3b0, Graph amethyst #9589ad, Payload sandstone #c6b9a0, primary accent brass gold #b8a06f.
Layout & Components:
1. Topbar (40px height): Left brand wordmark "TriviumDB" with subtle gold geometric icon; center navigation tabs ("TQL Console" active with #b8a06f bottom indicator, "Graph Explorer", "Vector Lab"); right status pills ("QuIVer Engine: Online", "ZH/EN", dark theme toggle).
2. Left Sidebar (240px width, #0b0a08): "Object Navigator" with tree groups: "Documents" (#c6b9a0 dot), "Graph Topology" (#9589ad dot), "Snippets", "Query History".
3. Center Workspace:
   - Toolbar (38px height): Primary gold button "Run" (#b8a06f fill, dark text, 8px radius, 32px height), secondary buttons "Write Mode", "Profile" (3.5% fill, 42% border); right-aligned segmented view switcher ("Table View" active, "Topology Graph", "JSON View").
   - TQL Editor (180px height, #11110f): Monospace syntax-highlighted TQL query combining MATCH graph pattern and VECTOR_SIM function, line numbers on left.
   - Result Card (18px border-radius, #191713): Clean data table with exactly 6 rows, monospace column headers (_id, type, payload_summary, edge_degree, vector_preview, score_ms), capsule tags (999px radius) colored by model type (#8fb3b0, #9589ad, #c6b9a0), inline mini vector barcode in each row.
4. Right Unified Panel (360px width, #0b0a08): Top tabs ("Node Details" active, "Filters", "AI Assistant"). Inside Node Details: 3 distinct collapsible cards (12px radius) with 3px left semantic border strips — Payload JSON viewer (#c6b9a0 border), Vector 768-dim mini heatmap strip (#8fb3b0 border), and Edges list with a small radial neighbor mini-graph (#9589ad border).
5. Bottom Status Bar (24px height, #070806, monospace 11px): "STATUS: READY | BACKEND: WebGL2 | ELAPSED: 4.2ms | ROWS: 6". Crisp typography, surgical alignment. --ar 16:10 --v 6.1 --style raw
图内中文标签与视觉对照：

顶栏与导航：TQL 查询控制台、独立图探索器、向量检索；左侧 对象导航（含 文档、图拓扑、常用代码片段、查询历史）。

工具栏与视图：主按钮 运行（#b8a06f 暖金实心），次级按钮 写入模式、剖析；右侧视图切换胶囊 表格视图（激活）、交互拓扑图、JSON 视图。

层级亮点：将 TQL 编辑器内胆色由原 #101215 修正为深暖玄武岩 #11110f，彻底消除与下方 #191713（18px 圆角）结果大卡的冷暖冲突。

图 2：桌面暗色 1440×900 — 交互拓扑图（WebGL 渲染 + 右上浮动工具条 + 底部布局控制条）
+----------------------------------------------------------------------------------------+
| ● TriviumDB  [TQL 查询控制台] [独立图探索器*] [向量检索]    [WebGL 60fps] [中文] [◐]   |
+-------------------+------------------------------------------------+-------------------+
| 对象导航 (240px)  | 画布顶栏: [图内搜索: 输入节点/属性...] [k-hop: 2] [路径追踪 ○]     |
| ▾ 图拓扑模式      |                                      +------ 右上浮动工具条 ------+ |
|   ◆ 节点数: 22    |         (o)---0.84--->(*)            | [+] [-] [1:1] [适应] [星云]| |
|   ◆ 边数: 39      |         / \            | \           +----------------------------+ |
|   ● Vector 节点   |       (o) (o)         (o) (o)                                      |
|   ● Graph 节点    |            \          /                                            |
|   ● Payload 节点  |            [★ usr_9042_xk] <====== 选中节点(外圈 2px 金环 #b8a06f) |
|                   |             /      |     \                                         |
| ▾ 子图快照        |           (o)     (o)    (o)                                       |
|   › 核心交易簇    |                                                                    |
|   › 语义近邻簇    |    +--------------- 底部紧凑布局控制条 (单行不换行) --------------+ |
|                   |    | 后端:[WebGL*|Canvas] | 布局:[力导向*][聚类][向量星图][度数径向] | |
|                   |    +--------------------------------------------------------------+ |
+-------------------+--------------------------------------------------------------------+
| ● 渲染引擎: Sigma WebGL | 节点: 22 | 边: 39 | 布局: 力导向 (已收敛) | 帧率: 60.0 FPS   |
+----------------------------------------------------------------------------------------+
English Image Generation Prompt:

Plaintext
Desktop B2B graph database explorer UI, "TriviumDB", 1440x900 resolution, 16:10 aspect ratio, 2x Retina clarity, Astrmira Obsidian dark theme (#070806 canvas void). Pure technical console interface, no sci-fi glowing flares, no 3D holographic gimmicks.
Graph Canvas Center Stage:
- WebGL rendered interactive topology graph on #070806 background with subtle radial dot grid.
- Exactly 22 nodes and 38 directed edges clearly visible. Nodes are crisp flat circles (12px to 28px diameter based on degree) colored by tri-model semantics: Vector nodes in mineral teal #8fb3b0, Graph hub nodes in amethyst #9589ad, Document payload nodes in warm sandstone #c6b9a0.
- One central hub node is selected, highlighted with a crisp 2px brass gold ring #b8a06f and a dark pill label "usr_9042_xk" in #f4eee4 text.
- Edges are crisp 1.2px lines in warm muted bronze-grey rgba(198,185,160,0.55) with directional arrowheads and monospace edge type micro-labels ("FOLLOWS", "SIMILAR_TO 0.89"). Connected k-hop paths highlighted in #b8a06f.
Floating HUD Controls:
1. Top-Left Canvas Search Pill (12px radius, #191713 surface): "Graph Search" input, "k-hop: 2" stepper capsule, and "Path Trace" toggle pill.
2. Top-Right Floating Toolbar (vertical or compact horizontal pill bar, #191713, 12px radius, 1px border): Zoom In, Zoom Out, Fit View, Lock Layout, and "Nebula Mode" toggle button.
3. Bottom-Center Floating Layout Control Bar (single-line compact HUD, height 40px, 999px capsule container, #191713 surface): Divided into two clean groups — Backend switcher ("Canvas" / "Sigma WebGL" active) and 4 Layout pills ("Force-Directed" active with #b8a06f border, "Cluster", "Vector Starfield", "Degree Radial"). Zero line-wrapping.
Left sidebar (240px, #0b0a08) showing graph schema legend and degree distribution. Bottom monospace status bar (24px). --ar 16:10 --v 6.1 --style raw
图内中文标签与视觉对照：

画布浮层控件：左上角 图内搜索、k-hop 邻域（步数选择器 1 / 2 / 3）、路径追踪；右上角浮动工具条含缩放、居中、星云模式；底部单行控制条含后端 Canvas / WebGL 与四种布局 力导向、聚类、向量星图、度数径向。

关键痛点修复：将原底部散落的 10+ 个按钮拆分为 左上检索条（搜索 + k-hop + 路径追踪） 与 底部纯粹布局条（后端 + 4 布局），即使左右双栏全开（中央剩 840px），底部控制条宽度也控制在 520px 以内，彻底根治换行遮挡问题。

图 3：桌面浅色 1440×900 — 交互拓扑图（浅色暖白底 + 深金棕边线 + 右侧节点详情面板展开）
+----------------------------------------------------------------------------------------+
| ● TriviumDB  [TQL 查询控制台] [独立图探索器*] [向量检索]    [WebGL 60fps] [中文] [☀]   |
+-------------------+------------------------------------+-------------------------------+
| 对象导航 (#f4f1ea)| 画布 (#fbf9f5 暖白底 + 浅灰点阵)    | 右侧面板 (360px, #f4f1ea)     |
| ▾ 图拓扑 (22 节点)| [图内搜索...] [k-hop: 2] [路径追踪] | [节点详情*] [过滤器] [AI 助手]|
|   ● Vector (#4a7a76)                                   |-------------------------------|
|   ● Graph  (#62547d)    (o)--- #5f523b 边线 --->(*)    | 节点: doc_8821_a  [文档|向量] |
|   ● Payload(#8a734c)     |  (alpha 0.82~0.58)    |     |-------------------------------|
|                          v                       v     | ▌Payload (JSON)        [折叠] |
|                        [★ doc_8821_a] (白底描边标签)   |   "title": "Graph Core",      |
|                         /          \                   |   "category": "storage"       |
|                       (o)          (o)                 |-------------------------------|
|                                                        | ▌Vector (768d · L2)    [复制] |
|     +--- 底部控制条 (#fbf9f5, 1px #ded8cc 边框) ---+    |   [████████▓▓▒▒░░▓▓██]        |
|     | [WebGL*] | [力导向*][聚类][向量星图][度数径向] |    |   [-0.041, 0.812, 0.119...]   |
|     +---------------------------------------------+    |-------------------------------|
|                                                        | ▌Edges (14) & 邻居迷你图      |
|                                                        |   -> CITATION (doc_3109_b)    |
|                                                        |   [ 迷你径向拓扑预览框 90px ] |
+-------------------+------------------------------------+-------------------------------+
| ● 渲染引擎: Sigma WebGL | 浅色高对比度模式 | 边线密度自适应: α=0.74 | 耗时: 1.8ms      |
+----------------------------------------------------------------------------------------+
English Image Generation Prompt:

Plaintext
Desktop B2B graph database explorer UI in Light Mode, "TriviumDB", 1440x900 resolution, 16:10 aspect ratio, 2x Retina clarity, Warm Stone & Paper theme. Exact same graph topology as the dark mode view, with the Right Unified Inspector Panel (360px) open.
Light Mode Color System:
- Canvas background #f4f1ea (warm stone paper), elevated cards and floating HUD bars #fbf9f5 with crisp 1px border #dcd6c8 and soft shadow rgba(95,82,59,0.06).
- Primary ink text #1e1c18, secondary text #524e46, muted text #7a756c.
- Graph edges rendered in deep bronze-brown #5f523b with adaptive alpha transparency (0.82 for primary paths, 0.58 for dense background edges) — clearly visible against #f4f1ea.
- Node colors darkened for WCAG AA contrast on light paper: Vector nodes #4d7c78 (deep mineral teal), Graph nodes #645680 (deep plum), Payload nodes #8c764e (deep ochre), Selected node ring #9e7f47 (burnished gold).
- Every node text label has a 2px #fbf9f5 halo stroke so text never collides visually with crossing #5f523b edges.
Right Unified Panel (360px width, open on right):
- Top segmented tabs: "Node Details" (active), "Filters", "AI Assistant".
- Inside Node Details, 3 structured sub-cards (#fbf9f5, 12px radius) with 3px colored left border accents:
  1. "Payload" section (#8c764e left bar): clean key-value JSON tree.
  2. "Vector" section (#4d7c78 left bar): 768-dim horizontal heatmap color strip + truncated monospace float array.
  3. "Edges & Mini-Graph" section (#645680 left bar): compact list of incoming/outgoing edges + a 100px embedded radial neighbor mini-graph canvas at the bottom. --ar 16:10 --v 6.1 --style raw
图内中文标签与视觉对照：

右侧统一面板完整结构：顶栏切换 节点详情（激活）、过滤器、AI 助手；内部严格分为四层卡片——节点头部元信息、Payload（带 #8c764e 沙金左色条）、Vector（带 #4d7c78 青色左色条与热力预览条）、Edges 与底部的 邻居迷你图（带 #645680 紫色左色条）。

浅色模式对比度治理：保留 #5f523b 边线（alpha 0.82 → 0.58），同时为节点文字增加 2px #fbf9f5 暖白描边衬底（Text Halo），并将三模色在浅色主题下自动映射为深色阶，彻底解决文字与边线粘连及对比度不足问题。

图 4：桌面暗色 1440×900 — 向量检索实验台（Vector Search Lab）
+----------------------------------------------------------------------------------------+
| ● TriviumDB  [TQL 查询控制台] [独立图探索器] [向量检索*]    [索引: HNSW-QuIVer] [中文] |
+-------------------+------------------------------------------------+-------------------+
| 对象导航 (240px)  | 向量检索实验台配置区 (#191713, 12px radius)    | 右侧面板 (360px)  |
| ▾ 向量集合 (4)    | 来源选择:[articles_emb (768d) ▾] 距离:[Cosine▾]| [过滤器*] [节点]  |
|   ● articles_emb  | Top-K:[ 10 ━━●━━━ ] efSearch:[ 64 ] [▶ 检索]   | [AI 助手]         |
|   ● user_profile  | 查询向量:[ -0.0241, 0.1184, -0.0921... (已折叠)]|-------------------|
|   ● image_clip    | 向量热力条 (Query Vector 768d Fingerprint):    | ▾ 标量预过滤      |
|   ● code_ast_vec  | [██▓▓▒▒░░██▓▓▒▒░░▓▓██▒▒░░██▓▓▒▒░░▓▓██▒▒░░██▓▓] |   status = "pub"  |
|                   +------------------------------------------------+   year >= 2024    |
| ▾ 检索历史        | 检索结果表 (18px radius, #191713)  耗时: 1.9ms |-------------------|
|   › Top-10 Cosine | 排名 | 节点 ID    | 向量热力对比 | 相似度得分  | ▾ 图拓扑约束      |
|   › Top-25 L2     | #01  | art_9012   | [██▓▓▒▒░░██] | ████▓ 0.964 |   必须包含边:     |
|                   | #02  | art_4410   | [██▓▓▒▒░░▓▓] | ████░ 0.931 |   [CITATION]      |
|                   | #03  | art_1088   | [██▓▒▒░░░▓▓] | ███▓░ 0.887 |   最小度数: 2     |
|                   | #04~#08 (紧凑排列，含三模关联胶囊与内联得分条) |                   |
+-------------------+------------------------------------------------+-------------------+
| ● 索引状态: HNSW (M=16, ef=200) | 向量维度: 768 | 距离度量: Cosine | 检索耗时: 1.9ms   |
+----------------------------------------------------------------------------------------+
English Image Generation Prompt:

Plaintext
Desktop B2B vector database search lab UI, "TriviumDB", 1440x900 resolution, 16:10 aspect ratio, 2x Retina clarity, Astrmira Obsidian dark theme (#070806 background, #0b0a08 shell, #191713 cards).
Center Workspace — Vector Search Lab:
1. Compact Parameter Control Card (top, 12px radius, #191713):
   - Row 1: "Source Collection" dropdown ("articles_embedding · 768d"), "Metric" selector ("Cosine"), "Top-K" slider & number input set to "10", primary gold action button "Run Search" (#b8a06f).
   - Row 2: Single-line collapsible "Query Vector" monospace input showing "[ -0.0241, 0.1184, -0.0921, +765 dims... ]" with an "Expand / Paste JSON" pill button.
   - Row 3: Full-width "Query Vector Heatmap Strip" (28px height) rendering the 768 dimensions as a high-density vertical barcode gradient transitioning from deep slate #11110f through mineral teal #8fb3b0 to warm gold #b8a06f.
2. Vector Results Card (below, 18px radius, #191713):
   - 8 data rows with columns: Rank (#01 to #08), Document ID (monospace), Payload Preview (with #c6b9a0 tag), Graph Degree (#9589ad badge "4 edges"), "Vector Residual Heatmap" (compact 120px barcode per row for visual comparison against query vector), and "Similarity Score" featuring an inline #8fb3b0 horizontal progress bar next to monospace numbers (0.9642, 0.9318, 0.8904...).
Right Unified Panel (360px): "Filters" tab active, showing hybrid pre-filtering rules combining Document payload conditions and Graph edge constraints. --ar 16:10 --v 6.1 --style raw
图内中文标签与视觉对照：

核心控件：向量检索、来源选择、查询向量（默认单行截断并带维度胶囊提示 768d，点击展开，防止撑爆首屏）、Top-K 滑块、全宽 向量热力条（Query Vector Fingerprint）。

结果表升级：每行不仅展示目标节点的迷你向量热力条，还在“相似度得分”列加入 #8fb3b0 归一化内联进度条（Inline Score Bar），一眼即可分辨 Top-K 相似度的断层位置。

图 5：移动端 390×844 双状态对照 —（左：查询页 + 结果表格；右：左侧对象导航抽屉打开 + 遮罩覆盖）
[状态 A: 移动端查询页 + 结果表格 (390x844)]     [状态 B: 左侧抽屉打开 + 遮罩覆盖 (390x844)]
+----------------------------------------+     +----------------------------+-----------+
| [≡] TriviumDB          [运行 ▶] [◐]    |     | ● TriviumDB      [✕ 关闭]  |░░░░░░░░░░░|
+----------------------------------------+     |----------------------------|░ 遮罩层 ░░|
| [TQL 控制台*] [拓扑图] [向量] [详情(1)]|     | 对象导航                   |░ rgba(7,8,|
+----------------------------------------+     | [搜索集合或边类型...     ] |░ 6, 0.68)░|
| TQL 编辑器 (可折叠, 110px, #11110f)    |     |                            |░░░░░░░░░░░|
| 1 | MATCH (n:Doc)                      |     | ▾ 文档集合 (12.4k)         |░ 底部页面░|
| 2 | RETURN n._id, n.title LIMIT 6;     |     |   ● users          (4.2k)  |░ 保持静止░|
+----------------------------------------+     |   ● articles       (8.2k)  |░ 禁止滚动░|
| [表格视图*] [交互拓扑] [JSON]   6 rows |     | ▾ 图拓扑边 (38.1k)         |░░░░░░░░░░░|
+----------------------------------------+     |   ◆ FOLLOWS                |░░░░░░░░░░░|
| #01 | doc_8821_a          | 0.94 [██▓] |     |   ◆ PURCHASED              |░░░░░░░░░░░|
|     | Graph Core Engine   | [文档][图] |     | ▾ 常用代码片段             |░░░░░░░░░░░|
|----------------------------------------|     |   › 混合检索模板           |░░░░░░░░░░░|
| #02 | doc_3109_b          | 0.91 [██░] |     | ▾ 查询历史                 |░░░░░░░░░░░|
|     | HNSW Vector Index   | [向量]     |     |   › 14:20 MATCH (n:Doc)... |░░░░░░░░░░░|
|----------------------------------------|     |----------------------------|░░░░░░░░░░░|
| #03 ~ #05 (紧凑双行卡片化表格行)       |     | 语言: [中文*] / [EN]       |░░░░░░░░░░░|
+----------------------------------------+     +----------------------------+-----------+
| ● READY | WebGL | 4.2ms | 6 行         |     | ● READY | 抽屉导航已激活   |░░░░░░░░░░░|
+----------------------------------------+     +----------------------------+-----------+
English Image Generation Prompt:

Plaintext
Side-by-side mobile UI presentation showing two states of "TriviumDB" mobile console, each screen 390x844 resolution (9:19.5 aspect ratio), 2x Retina clarity, Astrmira Obsidian dark theme (#070806 background, #191713 cards, #b8a06f gold accent).
Left Screen (State A: Mobile TQL Query & Result Table):
- Top App Bar (44px): Hamburger menu icon on left, "TriviumDB" brand title, compact primary gold "Run" button (#b8a06f) on right.
- Segmented Navigation Strip: "TQL", "Graph", "Vector", "Inspector (1)".
- Compact TQL Editor box (110px height, #11110f monospace code with line numbers, collapsible chevron).
- View Switcher Pills: "Table View" (active), "Topology", "JSON".
- Mobile Result Table Card (18px top border-radius, #191713): 5 visible rows designed for narrow 390px viewport — each row displays monospace _id, primary title, tri-model semantic pills (#8fb3b0, #9589ad, #c6b9a0), and compact score badge without horizontal overflow.
- Bottom Status Bar (24px, monospace): "READY | 4.2ms | 6 rows".
Right Screen (State B: Left Navigation Drawer Open with Scrim Overlay):
- Left slide-over drawer (300px width, #0b0a08 surface, 1px right border rgba(244,238,228,0.12)) open over the query page.
- Drawer contents: "Object Navigator" header with close button, search input, collapsible sections for "Documents" (#c6b9a0 dot), "Graph Topology" (#9589ad dot), "Snippets", and "Query History", plus bottom language/theme switchers.
- Remaining 90px on the right shows the underlying TQL Query screen dimmed by a dark translucent scrim overlay rgba(7,8,6,0.68) with zero blur distortion. --ar 16:10 --v 6.1 --style raw
图内中文标签与视觉对照：

移动端适配策略：在 390×844 窄屏下，左侧 对象导航 收纳入 300px 抽屉（带 rgba(7,8,6,0.68) 遮罩覆盖），右侧面板转化为顶部第 4 个切换标签 节点详情(1) 或底部上拉抽屉（Bottom Sheet）；表格行采用“主 ID + 副标题胶囊”紧凑双行排版，避免横向滚动条割裂手势。

图 6：组件状态板 1440×900 — 暗/浅两半对照（Buttons × 5 States + 胶囊 + 输入框 + Pill + 结果卡 + 表头）
+-------------------------------------------+-------------------------------------------+
| 暗色模式组件板 Dark (#070806 / #191713)   | 浅色模式组件板 Light (#f4f1ea / #fbf9f5)  |
|-------------------------------------------+-------------------------------------------|
| 1. 按钮矩阵 (32px 高, 12.5px 字, 8px 圆角)| 1. 按钮矩阵 (32px 高, 12.5px 字, 8px 圆角)|
|          [Default][Hover↑1px][Active.98]  |          [Default][Hover↑1px][Active.98]  |
|          [Focus 2px青圈] [Disabled 40%]   |          [Focus 2px青圈] [Disabled 40%]   |
| - 主按钮 (运行): #b8a06f 实心             | - 主按钮 (运行): #9e7f47 实心             |
| - 次级按钮 (剖析): 3.5%填充 + 42%边框     | - 次级按钮 (剖析): 4.5%填充 + #b8b0a0边框 |
| - 危险按钮 (清空): #c46b62 矿物砖红       | - 危险按钮 (清空): #a8483f 矿物深红       |
|-------------------------------------------+-------------------------------------------|
| 2. 三模胶囊标签与状态 Pill (999px 圆角)   | 2. 三模胶囊标签与状态 Pill (999px 圆角)   |
|   [● 向量 #8fb3b0] [◆ 图拓扑 #9589ad]     |   [● 向量 #4d7c78] [◆ 图拓扑 #645680]     |
|   [■ 文档 #c6b9a0] [● 引擎就绪]           |   [■ 文档 #8c764e] [● 引擎就绪]           |
|-------------------------------------------+-------------------------------------------|
| 3. 输入框 (8px) & 表头 (Mono) & 结果卡(18)| 3. 输入框 (8px) & 表头 (Mono) & 结果卡(18)|
|   [ 检索节点 ID...  (Focus 2px #8fb3b0) ] |   [ 检索节点 ID...  (Focus 2px #4d7c78) ] |
|   +--- 结果卡片 (18px radius, #191713) --+|   +--- 结果卡片 (18px radius, #fbf9f5) --+|
|   | _ID (Mono) | TYPE     | ELAPSED      ||   | _ID (Mono) | TYPE     | ELAPSED      ||
|   | doc_8821   | [向量]   | 1.24 ms      ||   | doc_8821   | [向量]   | 1.24 ms      ||
|   +--------------------------------------+|   +--------------------------------------+|
+-------------------------------------------+-------------------------------------------+
English Image Generation Prompt:

Plaintext
UI Design System Component State Sheet for "TriviumDB", 1440x900 resolution, 16:10 aspect ratio, 2x Retina clarity. Split vertically 50/50: Left half is Astrmira Obsidian Dark Mode (#070806 background, #191713 card surfaces); Right half is Warm Stone Light Mode (#f4f1ea background, #fbf9f5 card surfaces). Surgical grid layout with monospace engineering annotations.
Section 1 — Button State Matrix (32px height, 12.5px font, 8px border-radius):
- 3 rows ("Primary Button #b8a06f", "Secondary Button 3.5% fill + 42% border", "Danger Button #c46b62 mineral terracotta") x 5 columns ("Default", "Hover: translateY(-1px) + teal-grey border #8fb3b0 + soft shadow", "Active: scale(0.98)", "Focus-Visible: 2px solid #8fb3b0 outer ring", "Disabled: 38% opacity").
Section 2 — Capsules, Status Pills & Inputs:
- Tri-model semantic capsules (999px radius): Vector (#8fb3b0 dark / #4d7c78 light), Graph (#9589ad dark / #645680 light), Payload (#c6b9a0 dark / #8c764e light).
- Status Pills: "WebGL Ready", "Write Mode Locked", "QuIVer Indexing".
- Text & Search Inputs (8px radius, 32px height) in Default, Hover, and Focus-Visible (2px teal ring) states.
Section 3 — Result Card (18px radius), Sub-Card (12px radius), and Monospace Table Header:
- Specimen of the 18px border-radius Result Card container containing a monospace table header row (_ID, MODEL_TYPE, VECTOR_NORM, LATENCY_MS) with sort arrows and two sample data rows. --ar 16:10 --v 6.1 --style raw
图内中文标签与视觉对照：

完整呈现主按钮（运行）、次级按钮（写入模式 / 剖析）、危险按钮（删除节点）在 default / hover / active / focus-visible / disabled 五态下的像素级差异，以及 8px 控件、12px 子卡、18px 结果卡、999px 胶囊在暗/浅双主题下的对比度映射。

图 7（补充）：桌面暗色 1440×900 — 命令面板（Ctrl+K）与 8 步交互教程弹窗同屏规范
+----------------------------------------------------------------------------------------+
| (底层控制台背景降暗遮罩 rgba(7,8,6,0.65))                                              |
|                                                                                        |
|        +----------------------- 命令面板 (Ctrl+K, 560px 宽) ----------------------+    |
|        | > 输入命令或跳转视图...                                        [ESC 关闭]|    |
|        |--------------------------------------------------------------------------|    |
|        | 常用操作                                                                 |    |
|        | ★ [运行当前 TQL 查询]                                       Ctrl + Enter |    |
|        |   [切换至独立图探索器 · 向量星图布局]                       G -> S       |    |
|        |   [开启 2-hop 邻域路径追踪]                                 Alt + K      |    |
|        | 主题与语言                                                               |    |
|        |   [切换暗色 / 浅色模式]                                     Ctrl + Shift |    |
|        +--------------------------------------------------------------------------+    |
|                                                                                        |
|                                       +--- 8 步教程浮窗 (Step 3/8, 380px 宽) ------+   |
|                                       | 03 / 08 · 混合图向量检索 (Serif 衬线标题)   |   |
|                                       | 在 TQL 中使用 VECTOR_SIM() 结合 MATCH 子句 |   |
|                                       | 可同时过滤度数与余弦距离。                 |   |
|                                       | [● ● ◉ ○ ○ ○ ○ ○]      [上一步] [下一步 ▶] |   |
|                                       +--------------------------------------------+   |
+----------------------------------------------------------------------------------------+
English Image Generation Prompt:

Plaintext
Desktop UI overlay states showcase for "TriviumDB", 1440x900 resolution, 16:10 aspect ratio, Astrmira Obsidian dark theme. Over a dimmed console background (#070806 with rgba(7,8,6,0.65) scrim), displaying two key overlay components:
1. Command Palette Modal (top-center, 560px width, 12px border-radius, #191713 surface, 1px #b8a06f/30% border):
   - Search input at top with "> Type a command or jump to node..." and "ESC" badge.
   - Categorized command list ("Query Actions", "Graph Layouts", "Vector Tools", "System"): First item highlighted with 3.5% warm fill and 3px left #b8a06f bar ("Run Current TQL Query — Ctrl+Enter"), followed by "Switch Layout: Vector Starfield", "Trace k-hop Neighborhood", "Toggle Dark/Light Theme". Monospace keyboard shortcut badges on right.
2. 8-Step Onboarding Tutorial Popover Card (bottom-right anchored near the TQL editor, 380px width, 12px border-radius, #191713 surface):
   - Header featuring an editorial Serif title (#f4eee4) — the ONLY place Serif typography is used: "Step 3 of 8: Hybrid Graph-Vector Querying".
   - Concise instructional body text in sans-serif (#b9bdb6) and a 2-line monospace TQL snippet preview.
   - Footer with 8 progress dots (dot 3 active in #b8a06f gold) and buttons "Skip", "Previous", "Next Step" (#b8a06f). --ar 16:10 --v 6.1 --style raw
图 8（补充）：动效分镜规范板 1440×900 — 4 组关键帧与缓动曲线（严禁无限循环）
+-------------------------------------------+-------------------------------------------+
| 分镜 A: 按钮 Hover & Active (150ms)       | 分镜 B: 结果卡进入 (160ms)                |
| [F0: t=0ms]   -> [F1: t=150ms] -> [Click] | [F0: t=0ms]          -> [F1: t=160ms]     |
|  y: 0px           y: -1px          scale  |  opacity: 0              opacity: 1       |
|  border: 42%      border: #8fb3b0  (0.98) |  translateY(+6px)        translateY(0px)  |
|  曲线: cubic-bezier(0.22, 1, 0.36, 1)     |  曲线: cubic-bezier(0.16, 1, 0.3, 1)      |
+-------------------------------------------+-------------------------------------------+
| 分镜 C: 图布局切换 (力导向 -> 度数径向)   | 分镜 D: 右侧 360px 面板收起/展开 (180ms)  |
| [F0: 0ms]     -> [F1: 140ms]  -> [F2:280ms| [F0: 0ms (w:360px)]  -> [F1: 180ms (w:0)] |
|  原坐标集         线性插值过渡     收敛锁定|  画布视口平滑重算         WebGL 锚点保持  |
|  (锁定后 0 漂移，严禁每帧呼吸晃动)        |  曲线: cubic-bezier(0.22, 1, 0.36, 1)     |
+-------------------------------------------+-------------------------------------------+
English Image Generation Prompt:

Plaintext
UI Motion & Keyframe Storyboard Specification Sheet for "TriviumDB", 1440x900 resolution, 16:10 aspect ratio, Astrmira Obsidian dark theme (#070806 background, #191713 grid cards). Architectural blueprint style showing discrete keyframes (F0, F1, F2) with directional arrows, pixel deltas, millisecond durations, and cubic-bezier curves. Strictly NO infinite pulsing, NO breathing glow, NO continuous node drift.
Quadrant 1 — Button Micro-Interaction (150ms, cubic-bezier(0.22, 1, 0.36, 1)):
- Frame 0 (0ms): Secondary button at rest (y: 0px, border rgba(185,189,182,0.42)).
- Frame 1 (150ms Hover): Button elevated by -1px upward arrow, border shifts to mineral teal #8fb3b0, soft drop shadow 0 4px 10px rgba(0,0,0,0.35).
- Frame 2 (80ms Active Press): Button scales down to scale(0.98).
Quadrant 2 — Result Card Entrance (160ms, cubic-bezier(0.16, 1, 0.3, 1)):
- Frame 0 (0ms): 18px radius Result Card at opacity 0, offset +6px down.
- Frame 1 (160ms): Card settles at opacity 1, translateY(0px), zero overshoot bounce.
Quadrant 3 — Graph Layout Transition (280ms finite interpolation, cubic-bezier(0.25, 1, 0.5, 1)):
- Frame 0 (0ms): Nodes in "Force-Directed" cluster.
- Frame 1 (140ms): Straight vector motion trails showing nodes interpolating along direct paths.
- Frame 2 (280ms): Nodes locked into concentric rings of "Degree Radial" layout with a "LOCKED / 0 FPS IDLE" badge indicating rendering stops once converged.
Quadrant 4 — Right 360px Panel Collapse (180ms, cubic-bezier(0.22, 1, 0.36, 1)):
- Frame 0 (0ms): Right panel open (width: 360px).
- Frame 1 (180ms): Panel slides right (translateX(100%)), central canvas expands smoothly while keeping graph center anchor fixed. --ar 16:10 --v 6.1 --style raw
D. 设计规范摘要（Design System Specification）
1. 颜色变量表（Color Tokens：暗色星尘 & 浅色暖石对照）
语义角色	CSS 变量建议名	暗色模式（Astrmira Dark）	浅色模式（Warm Stone Light）	适用范围与对比度说明
L0 画布底色	--bg-canvas	#070806	#f4f1ea	拓扑图底层画布、主工作区底板
L1 框架壳层	--bg-shell	#0b0a08	#ece7dd	左侧对象导航、顶栏、底栏、右侧面板底板
L2 内凹数据槽	--bg-well	#11110f (修正原 #101215)	#e4dfd4	TQL 编辑器、查询向量输入槽、代码块背景
L3 卡片与浮层	--bg-elevated	#191713	#fbf9f5	18px 结果大卡、12px 详情子卡、浮动工具条
主文本	--text-primary	#f4eee4	#1e1c18	标题、正文、代码主标识符（对比度大于 12:1）
次级文本	--text-secondary	#b9bdb6	#524e46	表格常规单元格、面板属性名、次级按钮文字
弱化文本	--text-muted	#8f958e	#7a756c	表头说明、单位标识、空态副文案
禁用/元信息	--text-disabled	#70766f	#9e988e	禁用态控件、行号、折叠提示
主强调色（金）	--accent-gold	#b8a06f	#9e7f47	运行 主按钮、选中节点外环、激活 Tab 指示条
向量语义色	--model-vector	#8fb3b0	#4d7c78	向量节点、热力条主色、focus-visible 焦点环
图拓扑语义色	--model-graph	#9589ad	#645680	图枢纽节点、边类型胶囊、邻居迷你图 边框
文档语义色	--model-payload	#c6b9a0	#8c764e	文档节点、Payload JSON 键名高亮
危险语义色	--accent-danger	#c46b62	#a8483f	危险按钮、查询语法报错、连接断开状态
2. 字体、字号与行高规范（Typography Scale）
字体栈：

--font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Inter", "Microsoft YaHei", sans-serif（全局 UI 主体）

--font-mono: "JetBrains Mono", "Fira Code", "SFMono-Regular", Consolas, monospace（状态栏、表头、TQL 编辑器、向量数组、耗时微标签）

--font-serif: "Newsreader", "Source Han Serif SC", "Songti SC", Georgia, serif（仅限 空态标题与 8 步教程弹窗主标题）

字号梯度：

底部状态栏 / 微标签（Mono）：11px / 行高 16px / 字距 0.02em

表头（Mono 大写）：11.5px / 行高 16px / 字重 600 / 字距 0.04em

标准按钮 / 导航项 / 表格正文：12.5px / 行高 18px / 字重 500（按钮）或 400（表格）

TQL 编辑器代码（Mono）：13px / 行高 20px

面板分区标题 / 卡片标题：13.5px / 行高 20px / 字重 600

教程弹窗 / 空态 Serif 标题：18px / 行高 26px / 字重 500

3. 间距、圆角与布局网格（Spacing & Radius）
圆角（Border Radius）：

基础控件（按钮、输入框、下拉框、代码内胆）：8px

面板内子卡片、浮动工具条、命令面板、教程弹窗：12px

中央主结果大卡片（Result Card）：18px

三模语义标签、状态 Pill、底部布局切换器：999px（全胶囊）

空间尺寸契约：

顶栏高度：40px；上下文工具栏高度：38px；底部状态栏高度：24px

左侧对象导航宽度：240px（支持折叠至 0px）；右侧统一面板宽度：360px（支持折叠至 0px）

卡片内边距：12px（紧凑子卡） / 16px（18px 结果大卡）；组件间距基数：4px / 8px / 12px / 16px

4. 按钮状态矩阵（Button States：12.5px 字号 / 32px 高度 / 8px 圆角）
按钮类型	Default	Hover（150ms）	Active（80ms）	Focus-Visible	Disabled
主按钮（Primary）	背景 #b8a06f，文字 #0b0a08（字重 600），边框 1px solid rgba(255,255,255,0.12)	translateY(-1px)，背景提亮至 #c4ae7f，边框 #8fb3b0，阴影 0 4px 12px rgba(0,0,0,0.35)	scale(0.98)，背景 #a68e5e	外圈 2px solid #8fb3b0，outline-offset: 2px	整体透明度 0.38，cursor: not-allowed，无位移
次级按钮（Secondary）	背景 rgba(244,238,228,0.035)（3.5% 填充），边框 rgba(185,189,182,0.42)（42% 边框），文字 #f4eee4	translateY(-1px)，背景升至 6.5%，边框变为青灰 #8fb3b0，柔和阴影 0 3px 10px rgba(0,0,0,0.28)	scale(0.98)，背景 2%	外圈 2px solid #8fb3b0，outline-offset: 2px	填充 1.5%，边框 18%，文字 #70766f
危险按钮（Danger）	背景 rgba(196,107,98,0.10)，边框 rgba(196,107,98,0.45)，文字 #e08a82	translateY(-1px)，背景 rgba(196,107,98,0.18)，边框 #c46b62，柔和阴影	scale(0.98)	外圈 2px solid #c46b62，outline-offset: 2px	整体透明度 0.35
5. 拓扑图节点与边线渲染规则（Graph Rendering Rules）
节点（Nodes）：

半径映射：
R=clamp(6+2.5×ln(degree+1), 6px, 18px)。

颜色映射：按主属性着三模色（Vector #8fb3b0 / Graph #9589ad / Payload #c6b9a0；浅色模式切换为 #4d7c78 / #645680 / #8c764e）。

选中与悬停态：选中节点外扩 3px 间隙并绘制 2px #b8a06f 实心金环；hover 节点绘制 1.5px #8fb3b0 青灰环。

标签防粘连（Text Halo）：暗色模式下文字 #f4eee4 配 2px #070806 外描边；浅色模式下文字 #1e1c18 强制配 2.5px #fbf9f5 暖白外描边，彻底阻断边线穿字干扰。

边线（Edges）：

暗色模式：默认 #c6b9a0，透明度随画面可见边数 
E 动态计算 
α=clamp(0.68−0.0008×E, 0.22, 0.68)。

浅色模式：固定色相 #5f523b（深金棕），密度自适应透明度 
α∈[0.58,0.82]；选中节点的关联一跳边（1-hop）提升至 
α=0.95，线宽由 1.2px 加粗至 2.0px。

静止帧保护：力导向布局迭代收敛（速度阈值低于 0.001）后立即停止 requestAnimationFrame 循环，进入按需重绘（Dirty-flag Render）状态，杜绝每帧微漂移。

E. 下一步建议：优先改造的 3 个页面/模块与工程理由
第一优先级：全局 :root 设计变量与右侧统一面板“节点详情（Node Details）”重构

改动内容：

将 :root 中暗色内胆槽 #101215 替换为深暖玄武岩 #11110f，同时补齐 .theme-light 下的深色三模语义变量（#4d7c78 / #645680 / #8c764e）。

为右侧 360px 面板内的 Payload、Vector、Edges、邻居迷你图 四个子容器加上 3px 左侧三模语义色条、粘性折叠标题（Sticky Header）及默认最大高度截断（Payload 默认展示前 8 行，点击展开）。

为什么先改：右侧统一面板在 TQL 控制台、独立图探索器、向量实验台三个核心页面中全局复用。一次 CSS + DOM 结构微调即可同时提升全部页面的信息层级，且修改范围高度收敛，不会破坏 ui-smoke.mjs 的主流程断言。

第二优先级：独立图探索器（Graph Explorer）浮动 HUD 拆分与浅色模式 Text Halo 补丁

改动内容：

将底部拥挤的单条浮动控制栏拆分为 左上检索胶囊条（图内搜索 + k-hop 邻域 + 路径追踪）与 底部纯布局控制条（Canvas/WebGL + 力导向/聚类/向量星图/度数径向）。

在 Canvas 2D strokeText 与 Sigma WebGL 节点标签 Shader 中加入 2.5px 背景同色 Halo 描边（暗色 #070806 / 浅色 #fbf9f5）。

为什么第二改：直接解决当前 7 张视觉基线中最显著的“双栏展开时底部按钮换行遮挡节点”与“浅色模式文字与 #5f523b 边线重叠难辨”两大硬伤，且视觉对比提升最为直观。

第三优先级：向量检索实验台（Vector Lab）参数区折叠收纳与结果表内联热力条联动

改动内容：

将顶部查询向量输入框改为单行可折叠摘要槽（展示前 6 维 + 768d 胶囊 + 全宽 28px 向量热力条），把首屏 70% 以上的垂直空间让位给结果表。

在结果表的“相似度得分”列内嵌 #8fb3b0 宽度归一化进度条，并增加行级迷你向量条码对照。

为什么第三改：完成从“能用的表单工具”到“专业三模向量分析台”的体验闭环，改动独立于图渲染引擎，前端回归测试风险最低。










TDB 太空星夜未来科技峰

为您重新设计了 TriviumDB 的 WebUI 界面（astrmira-theme 太空星夜/未来科技主题）。由于 TriviumDB 是一个将向量检索（Vector）、属性图谱（Graph）和文档型元数据（Document）原生融合的 AI 级嵌入式三模数据库，在重新设计时，特别注重了三者在视觉上的联动性、信息的层次结构、以及交互的可读性。

这里为您生成了 2 张前端 UI 定稿图（Overview 概览页和 Graph Visualizer 图谱与向量探索页），展示了在色彩、排版、卡片化布局及多模态数据可视化上的深度优化：

1. Overview 概览页 (image_0.png)
展现系统整体状态与日常管理的 Dashboard。

左侧导航栏 (Sidebar)：融合了 “astrmira” 的宇宙暗夜微光视觉。顶部展示 logo 及 WebUI 分支主题。菜单清晰划分，激活态伴随霓虹渐变。

顶部状态栏：整合了状态、API端点、负载信息，并采用精致的圆角标签（Badges）。

顶部核心指标卡片：使用微折线图、环形图及进度条，直观展示 Document、Vector、Graph 核心数据。

左侧：语义与向量检索 (Documents & Vectors)：优化了搜索交互和折叠式 JSON 查看器。高亮及标签（如 address, natice 等）使多模态元数据检索一目了然，极具可读性。

右侧：图谱可视化 preview (Graph Visualization)：展示节点与边的关联，右下角带有高维向量空间的投影缩略图，增强直观感知。

底部：多模式 Playground / 查询终端：支持 Cypher / JSON 混合查询，代码高亮与 Execute 按钮设计显著，提升了操作体验。

2. Graph & Vector Explorer 属性图谱与向量探索页 (image_1.png)
面向数据分析与深度探索的核心功能页，强化了 3D 关联的可读性。

左侧搜索与过滤：增加了“模式查询与相似度搜索（Pattern Query & Similarity Search）”、相似度阈值滑动条（Cosine Similarity Threshold）以及图/文混合结果列表，便于条件过滤。

中央：3D 属性图谱 (Interactive 3D Graph)：全景展示 Agent、Memory 等三模节点的复杂拓扑。连接线上标有 RECALLS、HAS_METADATA、CONTRIBUTES_TO 等关系标签。点击某节点可激发波纹特效，突出邻居节点。

右侧：节点详细属性卡 (Node Details Popup)：悬浮展示所选节点的 metadata 及 embedding 向量片段，附带“探索邻居 (Explore Neighbors)”与“查询原始文档 (Query Raw Document)”等高频操作。

右下角：3D 向量空间投影 (3D Vector Space Projection)：三维点云聚类图，以点代表向量，多色彩映射，与左、中部的图谱和文档形成闭环。

底部控制栏：提供 Zoom、3D/2D 切换、力导向布局 (Force-directed) 调整等便捷物理参数配置。
# WebUI 图探索 API Gap 记录（PR-14）

> 记录内置 Web Console（`crates/triviumdb-server/web/index.html`）在实现「搜索驱动图探索」
> 过程中遇到的 HTTP API 能力缺口。每条 gap 包含：现状、对 WebUI 的实际影响、建议的端点草案。
> 目的是为后续 server 迭代提供输入；在 gap 补齐之前，WebUI 用现有 API 的客户端组合 workaround。

## 已有能力（本文引用）

| 能力 | 端点 | 说明 |
| --- | --- | --- |
| TQL 查询 | `POST /v1/tql` | 支持 `Accept: application/x-ndjson` 流式（PR-11） |
| 节点详情 | `GET /v1/nodes/{id}` | 返回 node + edgeVersions（targetId/label/version） |
| 向量检索 | `POST /v1/search/vector` | Top-K 近邻 |
| 健康探测 | `GET /health/ready`、`GET /health/details` | |

## Gap 1：无 k-hop / 多跳邻域批量查询端点

- **现状**：拉取某节点的 1 跳邻域只能 `GET /v1/nodes/{id}` 拿 edgeVersions，再对每个
  targetId 逐个 `GET /v1/nodes/{targetId}`，即 N+1 请求。2 跳扩展请求数按分支因子平方增长。
- **影响**：WebUI「扩展邻域入图」功能（`expandNeighborhoodIntoGraph`）在稠密图上会产生
  请求风暴；深度 >1 的探索在小带宽/远程场景不可用。
- **建议草案**：
  - `GET /v1/nodes/{id}/neighbors?depth=1..3&limit=N&types=paper,person`
    → 返回 `{ nodes: [...], edges: [{ source, target, label }], truncated: bool }`，
    一次性返回子图；`truncated` 配合 `limit` 做服务端护栏（与 max_query_rows 语义对齐）。
- **当前 workaround**：客户端 BFS 逐跳逐节点拉取（depth 固定 1，由用户重复点击继续扩展）。

## Gap 2：无最短路径 / 路径追踪查询

- **现状**：TQL `MATCH` 只能匹配固定模式（定点跳数），无法表达「A 到 B 的最短路径 /
  所有 ≤N 跳路径」这类变长路径查询；HTTP API 也没有 path 端点。
- **影响**：WebUI「路径追踪」探索（选中两个节点高亮连通路径）无法实现，只能整图肉眼找。
- **建议草案**：
  - `GET /v1/nodes/{from}/paths/to/{to}?maxHops=4&limit=10`
    → 返回 `{ paths: [[{ id, label }, { edgeLabel, id }...]] }`（节点序列 + 连接边标签）。
  - 或 TQL 扩展：`MATCH SHORTEST (a)-[*1..4]->(b)`（需查询引擎支持变长路径与去环）。
- **当前 workaround**：无（功能放弃，UI 未提供入口）。

## Gap 3：MATCH 投影无法返回边对象

- **现状**：`MATCH (a)-[r]->(b) RETURN a, b, r` 中 `r` 无法作为边对象返回（服务端只支持
  返回节点绑定）；WebUI 图视图的连线靠「同一行内节点出现顺序」推断。
- **影响**：推断出的连线没有真实边语义（可能画出查询路径而非真实边），边 label 只能来自
  显式 edge 对象行；两个节点被多条边连接时无法表达。
- **建议草案**：`RETURN r` 支持 EdgeView：`{ source, target, label, payload?, version }`，
  与 node 的 `{ type: 'node', ... }` 形状对齐（如 `{ type: 'edge', ... }`）。
- **当前 workaround**：行内顺序推断 + 去重（`mergeRowsIntoGraph` / `renderGraph`）。

## Gap 4：无按 label / 方向过滤的边列举

- **现状**：`GET /v1/nodes/{id}` 的 edgeVersions 返回全部出边（targetId/label/version），
  不支持按 label 过滤、方向（入边/出边）、分页。
- **影响**：hub 节点（大量出边）的邻域扩展无法选择性加载；入边完全不可见（需要反向查询）。
- **建议草案**：`GET /v1/nodes/{id}/edges?direction=out|in|both&label=KNOWS&offset&limit`。
- **当前 workaround**：全量拉取后客户端过滤（入边无解）。

## Gap 5：无子图/批量节点批量获取端点

- **现状**：按 id 列表获取节点只能逐个 `GET /v1/nodes/{id}`；NDJSON 批量端点只有导入
  （`POST /v1/import/nodes`、`POST /v1/import/edges`），没有读取。
- **影响**：与 Gap 1 叠加放大请求数；批量恢复/对比会话中的图快照效率低。
- **建议草案**：`POST /v1/nodes/batch-get`（body: `{ ids: [...] }`，NDJSON 响应）。
- **当前 workaround**：逐个请求 + 并发节制（串行）。

## Gap 6：结果 → 图的投影依赖约定形状

- **现状**：WebUI 从查询行中识别节点靠约定（对象含 `id` 且 `type === 'node'`；`hit`、
  别名等形状靠逐值探测），边靠 `source/target` 字段或行内顺序推断。
- **影响**：新增投影形状时前端需要跟着猜；无法显式声明「这列是节点/边」。
- **建议草案**：查询响应 meta 中携带列类型描述（`columns: [{ name, kind: 'node'|'edge'|'scalar' }]`），
  或统一 node/edge 包装形状（见 Gap 3）。
- **当前 workaround**：`findNodeInRow` / `mergeRowsIntoGraph` 的启发式识别。

## 已满足、无需新端点的需求（备忘）

- **流式结果**：`Accept: application/x-ndjson` 已满足大结果渐进渲染（PR-11）。
- **节点 360° 详情**：`GET /v1/nodes/{id}` 的 edgeVersions 满足抽屉 Edges 平面。
- **向量 Top-K 种子**：`POST /v1/search/vector` 满足向量检索种子入图。

## 优先级建议

1. **Gap 1（k-hop 邻域批量）** —— 对图探索体验提升最大，直接消除 N+1。
2. **Gap 3（MATCH 返回边对象）** —— 修正图连线语义，属于正确性问题。
3. **Gap 2（路径查询）** —— 差异化能力，可结合 TQL 变长路径一并设计。
4. Gap 4 / Gap 5 / Gap 6 —— 体验与健壮性改进，随相关功能一并考虑。

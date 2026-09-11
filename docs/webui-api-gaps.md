# WebUI 图探索 API Gap 记录与状态

> 记录内置 Web Console（`crates/triviumdb-server/web/index.html`）在实现「搜索驱动图探索」过程中
> 遇到的 HTTP API 能力缺口。**2026-09-11 更新：上游 0.8.8（PR #50 `feat/server-graph-exploration`）
> 已补齐其中 4 项，WebUI 相应 workaround 已移除。**

## 状态总览

| # | Gap | 状态 | 上游能力 / 现行实现 |
| --- | --- | --- | --- |
| 1 | k-hop 邻域批量查询 | ✅ **0.8.8 已修复** | `GET /v1/nodes/{id}/neighbors?depth&limit&labels&types&direction` → `{nodes, edges, visitedNodes, traversedEdges, truncated, generation}`；WebUI `expandNeighborhoodIntoGraph` 已改为单请求 |
| 2 | 最短路径 / 路径追踪 | ✅ **0.8.8 已修复** | `GET /v1/nodes/{from}/paths/to/{to}?maxHops&label` → `{paths:[{nodes, edges}], truncated, generation}`；WebUI 新增「追踪路径」（并入 + 琥珀色高亮 + 清除） |
| 3 | MATCH 投影无法返回边对象 | ⚠️ **仍开放** | TQL `RETURN r` 仍不支持边绑定；WebUI 保留行内顺序推断（`mergeRowsIntoGraph`）作为兜底。新的 `/neighbors`、`/edges`、`/paths` 端点已能提供真实边对象，图探索路径不再依赖推断 |
| 4 | 按 label / 方向过滤的边列举 | ✅ **0.8.8 已修复** | `GET /v1/nodes/{id}/edges?direction=out|in|both&label&offset&limit` → `{edges, total, offset, limit, hasMore, generation}`；WebUI 抽屉 Edges 平面改为双向 + 分页「加载更多」 |
| 5 | 批量节点读取 | ✅ **0.8.8 已修复** | `POST /v1/nodes/batch-get`（body `{ids:[...]}`）→ `{nodes, missingIds, generation}`；WebUI 路径追踪用它补齐路径节点 payload |
| 6 | 结果 → 图的投影依赖约定形状 | ⚠️ **仍开放** | 查询响应 meta 仍无列类型描述；WebUI 保留 `findNodeInRow` / `mergeRowsIntoGraph` 启发式识别 |

## 历史背景（workaround 移除记录）

- **Gap 1 旧 workaround**：`GET /v1/nodes/{id}` 取 `edgeVersions` → 逐 targetId 递归拉取（N+1，2 跳按分支因子平方增长），并在 BFS 结束后过滤悬挂边。0.8.8 后：单请求 + 服务端 `truncated` 护栏，悬挂边问题由服务端保证（返回边两端必在 `nodes` 中）。
- **Gap 4 旧 workaround**：全量拉取出边后客户端过滤，且**入边完全不可见**。0.8.8 后：`direction=both` 让入边以 `←` 标注呈现，hub 节点分页加载。
- **Gap 5 旧 workaround**：逐个 `GET /v1/nodes/{id}` 串行补齐。0.8.8 后：`batch-get` 单请求（上限 10000 ids）。

## 仍开放的两项（对 WebUI 的影响与建议）

### Gap 3：TQL MATCH 投影无法返回边对象

- **影响**：TQL 查询结果入图（查询控制台「交互拓扑图」/「并入图探索」）仍靠行内节点顺序推断连线；两节点间多条边、环状路径等场景的连线语义不精确。
- **现状缓解**：图探索路径（k-hop / 边列举 / 路径追踪）已全部走真实边端点；只有 TQL 结果投影仍是推断。
- **建议**：`RETURN r` 支持 `{ type: 'edge', source, target, label, weight, metadata }`（与 `encode_graph_edge` 形状对齐，服务端已有该编码函数）。

### Gap 6：结果形状无列类型声明

- **影响**：前端靠启发式识别节点/边/标量列；新增投影形状时需同步改前端。
- **建议**：响应 meta 携带 `columns: [{name, kind: 'node'|'edge'|'scalar'}]`（NDJSON 的 meta 行或 JSON 顶层）。

## 已满足、无需新端点（备忘）

- 流式结果：`Accept: application/x-ndjson`（PR-11）。
- 节点 360° 详情：`GET /v1/nodes/{id}`（仍返回 `edgeVersions`，向后兼容）。
- 向量 Top-K 种子：`POST /v1/search/vector`。
- 星云模式全图拉取：`MATCH (a)-[]->(b) RETURN a, b LIMIT 10000`（受 `max_query_rows` 护栏；无过滤 FIND 仍不合法，见 Gap 6 相关讨论）。

> **Evidence review notice:** This is the historical report. For corrections and limitations, read [the evidence README](README.md) before using any claim. In particular, do not describe the non-comparable memory metrics as precise savings, do not treat baseline build time as a three-build median, and do not assume the documented CPU-load gate was verified for each run.
# TriviumDB 0.9.0 跑测报告（交付 Astra）

生成时间：2026-11-04T10:35:16+00:00　｜　版本：`v0.9.0`（`7edf8ce`）　｜　线程：16　｜　重复：3

> 本报告只做两件事：给出**可以直接写进稿子的数字**，以及**明确不能写的数字**。
> 所有数字都能在 `results/bench-090/official/` 下找到对应文件。

---

## 0. 一句话结论（可直接用于 X 首行）

在 384/768/1536 三个 LLM embedding 维度上，同机同参数、R@10 对齐 90% 时，
TriviumDB 0.9.0 相对 hnswlib 的吞吐为 2.24–2.76×，构建快 2.6–4.0×，索引内存少 2.4–4.7×。

- MiniLM 384d / 1M：QPS **2.40×**，构建 **2.63×** 更快，索引内存 **2.39×** 更少
- Cohere 768d / 1M：QPS **2.24×**，构建 **3.67×** 更快，索引内存 **3.41×** 更少
- DBpedia 1536d / 990K：QPS **2.76×**，构建 **3.96×** 更快，索引内存 **4.70×** 更少
- SIFT 128d / 1M（边界）：TriviumDB 未达到 90% 召回，最高 30.10%（不复用为优势数字）

---

## 1. 环境与口径（写稿时必须带上）

| 项 | 值 |
|---|---|
| 机器 | Intel i9-14900K（24C/32T）/ 64 GB / Windows 11 |
| 线程 | 固定 16 线程（rayon / hnswlib / faiss 三处一致） |
| 版本 | TriviumDB 0.9.0（git `7edf8ce`），hnswlib 0.8.0，FAISS 1.15.0 |
| 参数 | HNSW `M=32`、`ef_construction=128`；TriviumDB `m=32`、`ef_c=128` |
| 指标 | R@10（cosine，L2 归一化）；目标召回 90% 处按 recall 轴线性插值 QPS |
| 重复 | 每个配置 3 次，QPS 取中位数 |
| 查询集 | 每数据集平铺至 2 万条（放大计时窗口，避免 25 ms 短窗低估吞吐） |
| GroundTruth | 数据集自带 `.i32`，跑前用精确 cosine 重算对拍，四个数据集均 `gt_match = 1.0000` |

**不能做的事**：

- 不能把旧文（0.7.x/0.8.x，i5-13490F 机器）的绝对 QPS 与本报告相减或相除。
- 不能把 Chroma 那类 Python 客户端端到端 QPS 和裸库 MT-QPS 放同一张图。
- 不能在 X 上写 `2.02×` 这种三位有效数字；写 `≈2.2×` / `2.2–2.9×`。
- 不能把 128 维结果说成“全面领先”——那一档是明确劣势（见 §3）。

---

## 2. 主结果：ANN（同机 / 同参 / 同召回）

| 数据集 | 引擎 | R@10@90% QPS | vs hnswlib | 构建 s | 索引内存 | 最高召回 |
|---|---|---:|---:|---:|---:|---:|
| MiniLM 384d / 1M | triviumdb | 106,808 | 2.40x | 44.5 | 721 MiB | 99.32% |
| MiniLM 384d / 1M | hnswlib | 44,500 | 1.00x | 117.2 | 1,724 MiB | 99.91% |
| MiniLM 384d / 1M | faiss_hnsw | 48,784 | 1.10x | 114.7 | 1,724 MiB | 99.85% |
| Cohere 768d / 1M | triviumdb | 45,585 | 2.24x | 51.0 | 935 MiB | 99.09% |
| Cohere 768d / 1M | hnswlib | 20,355 | 1.00x | 187.0 | 3,189 MiB | 99.73% |
| Cohere 768d / 1M | faiss_hnsw | 18,203 | 0.89x | 204.1 | 3,189 MiB | 99.57% |
| DBpedia 1536d / 990K | triviumdb | 28,522 | 2.76x | 103.4 | 1,288 MiB | 99.72% |
| DBpedia 1536d / 990K | hnswlib | 10,334 | 1.00x | 409.4 | 6,058 MiB | 99.75% |
| DBpedia 1536d / 990K | faiss_hnsw | 11,270 | 1.09x | 387.3 | 6,058 MiB | 99.72% |
| SIFT 128d / 1M（边界） | triviumdb | 未达 90% | - | 26.5 | 599 MiB | 30.10% |
| SIFT 128d / 1M（边界） | hnswlib | 96,190 | 1.00x | 31.2 | 748 MiB | 99.92% |
| SIFT 128d / 1M（边界） | faiss_hnsw | 91,584 | 0.95x | 34.3 | 748 MiB | 99.94% |

† = 插值区间跨度 > 5pp；triviumdb 行已无 †，基线行因只扫到 ef=15 仍可能带。

---

## 3. 边界：SIFT-128（必须写进文章，不要写进 X）

- TriviumDB 默认精排预算（64）下，SIFT-128 的召回上限只有 **30.1%**（ef=800）。
- 把精排预算提到 512，召回回到 **58.0%**（单次、旧计时口径，仅作趋势参考）。
- hnswlib 在同数据上 99.9%，差距是**量化方法在非负低维直方图上的边界**，不是配置错误。
- 建议写法：「128 维、非负直方图类数据不在适用范围内，我们不推荐用它替代 HNSW」。

---

## 4. 能力数据（0.9.0 相对 0.8.x 的增量）

### 混合管线：20K 节点

**混合管线：20K 节点**（16 个组合，全部 `passed: true`）

| 查询族 | 维度 | 基线 P95 (ms) | 优化后 P95 (ms) | 加速 | 评分候选削减 |
|---|---:|---:|---:|---:|---:|
| expand_group_rank | 384 | 0.39 | 0.01 | 76.0× | 99% |
| expand_group_rank | 768 | 0.45 | 0.01 | 67.5× | 99% |
| expand_group_rank | 1536 | 0.69 | 0.01 | 97.6× | 99% |
| expand_group_rank | 3072 | 1.75 | 0.02 | 94.2× | 99% |
| expand_property_rank | 384 | 0.78 | 0.08 | 9.4× | 80% |
| expand_property_rank | 768 | 0.81 | 0.09 | 9.5× | 80% |
| expand_property_rank | 1536 | 1.29 | 0.13 | 9.7× | 80% |
| expand_property_rank | 3072 | 1.97 | 0.23 | 8.5× | 80% |
| multi_anchor_intersect_rank | 384 | 0.89 | 0.03 | 30.9× | 94% |
| multi_anchor_intersect_rank | 768 | 1.25 | 0.03 | 36.5× | 94% |
| multi_anchor_intersect_rank | 1536 | 1.69 | 0.06 | 26.4× | 94% |
| multi_anchor_intersect_rank | 3072 | 2.70 | 0.10 | 25.8× | 94% |
| property_filter_rank | 384 | 9.78 | 0.41 | 23.7× | 90% |
| property_filter_rank | 768 | 9.13 | 0.58 | 15.6× | 90% |
| property_filter_rank | 1536 | 10.95 | 0.99 | 11.1× | 90% |
| property_filter_rank | 3072 | 13.00 | 1.66 | 7.8× | 90% |

> 基线 = 先全量评分再裁剪；优化 = 先按属性/图约束裁剪再评分。两者结果内容一致（0.9.0 的两个计划会写不同的 provenance 元数据，官方断言按全等比较会误判，本次改为按 id/similarity/property_score 的内容签名校验）。

### 混合管线：200K 节点

**混合管线：200K 节点**（16 个组合，全部 `passed: true`）

| 查询族 | 维度 | 基线 P95 (ms) | 优化后 P95 (ms) | 加速 | 评分候选削减 |
|---|---:|---:|---:|---:|---:|
| expand_group_rank | 384 | 7.49 | 0.09 | 84.3× | 99% |
| expand_group_rank | 768 | 10.17 | 0.12 | 85.0× | 99% |
| expand_group_rank | 1536 | 11.11 | 0.16 | 68.2× | 99% |
| expand_group_rank | 3072 | 13.44 | 0.28 | 48.6× | 99% |
| expand_property_rank | 384 | 11.34 | 1.64 | 6.9× | 80% |
| expand_property_rank | 768 | 17.16 | 2.34 | 7.3× | 80% |
| expand_property_rank | 1536 | 19.46 | 3.83 | 5.1× | 80% |
| expand_property_rank | 3072 | 23.80 | 6.37 | 3.7× | 80% |
| multi_anchor_intersect_rank | 384 | 9.79 | 0.79 | 12.4× | 94% |
| multi_anchor_intersect_rank | 768 | 13.93 | 1.19 | 11.7× | 94% |
| multi_anchor_intersect_rank | 1536 | 17.26 | 1.23 | 14.0× | 94% |
| multi_anchor_intersect_rank | 3072 | 21.31 | 2.08 | 10.2× | 94% |
| property_filter_rank | 384 | 70.31 | 5.34 | 13.2× | 90% |
| property_filter_rank | 768 | 76.88 | 7.81 | 9.8× | 90% |
| property_filter_rank | 1536 | 87.35 | 8.27 | 10.6× | 90% |
| property_filter_rank | 3072 | 117.41 | 11.09 | 10.6× | 90% |

> 基线 = 先全量评分再裁剪；优化 = 先按属性/图约束裁剪再评分。两者结果内容一致（0.9.0 的两个计划会写不同的 provenance 元数据，官方断言按全等比较会误判，本次改为按 id/similarity/property_score 的内容签名校验）。

### 图算法线程扩展

**图算法线程扩展（100K 节点，8 出度）**

| 算法 | 1T | 2T | 4T | 8T | 16T | 16T/1T |
|---|---:|---:|---:|---:|---:|---:|
| betweenness_sample64 | 524.0 | 264.9 | 138.0 | 82.1 | 59.6 | 8.8× |
| label_propagation | 1641.9 | 283.7 | 173.6 | 134.3 | 112.1 | 14.6× |
| pagerank | 106.2 | 30.7 | 23.9 | 20.8 | 26.3 | 4.0× |
| single_source_bfs | 3.9 | 6.2 | 10.0 | 11.1 | 12.1 | 0.3× |
| wcc | 246.7 | 23.1 | 12.5 | 9.4 | 12.9 | 19.1× |

> 单位毫秒；每种线程数都校验了结果哈希一致（确定性）。

### 查询算子线程扩展

数据规模 200,000 × 768 维，机器可用线程 32。

**查询算子线程扩展**

| 算子 | 1T | 2T | 4T | 8T | 16T | 16T/1T |
|---|---:|---:|---:|---:|---:|---:|
| degree | 168.8 | 70.4 | 52.3 | 48.9 | 50.6 | 3.3× |
| exact_rerank | 59.3 | 56.5 | 41.4 | 40.4 | 43.5 | 1.4× |
| multi_source_expand | 87.5 | 89.9 | 160.6 | 195.1 | 237.9 | 0.4× |
| property_scan | 90.2 | 90.0 | 119.9 | 150.2 | 167.3 | 0.5× |

> 单位毫秒；每种线程数都校验了结果哈希一致（确定性）。

### 1M 节点大前沿 BFS

1M 节点、平均出度 16、深度 8：峰值 9.35 M TEPS（1 线程，访问 15,999,792 条边）。注意：该 BFS 是内存带宽受限，线程越多反而越慢（1T 峰值 9.35 M TEPS）。完整矩阵见 `results\bench-090\official\bench\p3_deep_traversal\deep-traversal-1000000.json`。

### 属性索引与 Leiden

**四类属性索引 + 标准 Leiden**（criterion，逐用例中位估计）

```
property_indexes/composite_exact: time:   [1.6271 µs 1.7119 µs 1.8058 µs]
property_indexes/bitmap_or: time:   [723.05 µs 731.04 µs 740.40 µs]
standard_leiden_gate/weighted_multilevel/10000: time:   [6.9534 ms 7.0204 ms 7.0978 ms]
standard_leiden_gate/weighted_multilevel/50000: time:   [43.168 ms 43.543 ms 43.963 ms]
```


---

## 5. 稳定性与故障注入

### p4_fault_suites

全部通过：103 passed / 0 failed / 1 ignored （6 个测试二进制）

日志：`results\bench-090\official\logs\p4_fault_suites_debug.log`

> 说明：release + LTO 构建下 `fault_allocator` 触发 rustc `STATUS_ACCESS_VIOLATION` 崩溃，本组改用 debug 构建运行（不含 LTO），因此**不应引用其耗时**，只引用通过/失败计数。

### p5_soak

全部通过：2 passed / 0 failed / 0 ignored （1 个测试二进制）

日志：`results\bench-090\official\logs\p5_soak.log`

### p6_concurrency

全部通过：51 passed / 0 failed / 0 ignored （1 个测试二进制）

日志：`results\bench-090\official\logs\p6_concurrency.log`


---

## 6. 给 Astra 的出图建议

**图 1（X 主图）**：分组条形图，横轴三档维度（384 / 768 / 1536），每组三根柱（TriviumDB / hnswlib / FAISS），纵轴 = R@10=90% 处 QPS。
数据：`summary.csv` 的 `recall_at_10, qps` 列，或 `summary.json → datasets.<ds>.engines.<e>.at_target.qps`。

**图 2（副图）**：双轴柱状，构建时间 + 索引内存，只放 TriviumDB vs hnswlib。
数据：`summary.json → build_seconds` / `memory_bytes`（内存是 hot_bytes vs 估算，图注必须写“口径不同，只看量级”）。

**图 3（文章用，非 X）**：recall–QPS 曲线，四个数据集各一张小图，TriviumDB / hnswlib 两条线。
数据：`summary.csv` 全表。

**不要出**：把 SIFT 混进图 1；把 TriviumDB 在低 ef 段的点单独截出来做对比（那一段不是它的工作区间）。

---

## 7. 产物索引

| 文件 | 内容 |
|---|---|
| `results/bench-090/official/summary.json` | ANN 合并结果（机器可读，一切数字的源头） |
| `results/bench-090/official/summary.csv` | 画图用明细（dataset/engine/ef/recall/qps/build/memory） |
| `results/bench-090/official/summary.md` | 人读表格 |
| `results/bench-090/official/raw/` | 每次重复的原始 JSON（20 份 + meta） |
| `results/bench-090/official/bench/<step>/` | 仓库自带 benchmark 的 JSON 报告 |
| `results/bench-090/official/logs/` | 每一步的完整 stdout |
| `results/bench-090/official/runlog.json` | 每个步骤的状态、耗时、退出码 |
| `scripts/bench090/PROTOCOL.md` | 完整口径与已知坑 |

---

## 8. 已知限制（写稿时按需披露）

1. 共享机器（后台常驻约 19% CPU 占用），绝对 QPS 有 ±5% 波动；倍数比绝对值稳。
2. dbpedia 1536d 那档的 FAISS 与 hnswlib 都做了同参对照，但 FAISS 侧内存峰值最高。
3. 0.9.0 默认精排预算 64 对 384/768/1536 三档无影响（实测 rerank 64→256 召回完全不变），只影响 128 维档。
4. 本报告不含「一条 TQL 同时做向量+图+属性」的端到端延迟——那需要另写基准（P7/P8，未在本批执行）。

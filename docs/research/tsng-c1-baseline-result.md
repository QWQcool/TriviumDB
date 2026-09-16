# TSNG C0/C1 基线结果 —— 三信号导航的首次实测

> **基准**：`benches/bench_tsng_c0.rs`、`benches/bench_tsng_c1.rs`（**仓库自带，此前从未运行**）
> **报告**：`target/bench-reports/tsng-c0.json`、`target/bench-reports/tsng-c1-matched-recall.json`
> **状态**：已完成。**零代码改动**（仅运行）。`src/` 未动。

## 0. 裁定

**TSNG 在 C1 的三个场景里全部不是最快的执行路径（慢 1.4–42.2×），且 2/3 场景的 Gate 失败。**

| 场景 | 最快方法 | 最小 ef | R@10 | P95 ms | **TSNG 最快达标点** | **TSNG 慢** | Gate |
|---|---|---|---|---|---|---|---|
| `vector_property` | **`bq_prefilter`** | 64 | 90.31% | **0.0963** | ef=2048, 90.62%, 4.0591 ms | **42.2×** | passed（见 §2 附注） |
| `vector_graph` | **`industrial_density`** | 64 | 100% | **0.1829** | ef=256, 84.37%, 0.5650 ms | **3.1×** | **FAILED** |
| `three_signal` | **`industrial_fixed`** | 1024 | 83.75% | **1.1606** | ef=1024, 85.62%, 1.6598 ms | **1.4×** | **FAILED** |

Gate 失败理由（两场景一致）：
> `密度感知模式未降低 P95、向量页读取或候选精排工作量`

**⇒ 这是与 T1、T2 完全同型的第三个结果**：机制精巧，实测收益为零，被更简单的基线支配。
**⇒ TSNG 的"三模导航"尚未在任何测量中显示出优势。**（外部效度限制见 §4。）

---

## 1. 方法与口径

`bench_tsng_c1` 在同一固定 seed 数据集上比较**六条执行路径**，
每条扫 `ef ∈ {64,128,256,512,1024,2048,4096}` 及 bonus/quota/graph-seed 参数：

| 路径 | 说明 |
|---|---|
| `post_filter` | 先向量检索再按属性过滤 |
| `bq_prefilter` | BQ 预筛 + 属性 |
| `graph_union` | 图信号并集 |
| `tsng` | **三信号导航（本仓库的核心机制）** |
| `industrial_fixed` / `_selectivity` / `_density` | 工业自适应选择的三个变体 |

**本报告的口径**（与 C1 的 gate 一致，但按方法逐一给出）：
对每个场景、每个方法，取「满足 `target_recall=0.80` 且 `mean_result_count ≥ 10`」的
曲线点中 **P95 最小**者。这是**严格 matched-recall** 比较。

---

## 2. C1 详细结果（matched recall，target=0.80）

### 场景 `vector_property`（属性过滤）

| 方法 | 最小 ef | R@10 | NDCG@10 | P95 ms | 重排候选 | 导航打分 |
|---|---|---|---|---|---|---|
| **`bq_prefilter`** | **64** | 90.31% | 0.9531 | **0.0963** | 64.0 | 4416 |
| `industrial_selectivity` | 256 | 100% | 1.0000 | 0.2370 | 256.0 | 4416 |
| `industrial_density` | 256 | 100% | 1.0000 | 0.2609 | 256.0 | 4416 |
| `industrial_fixed` | 256 | 100% | 1.0000 | 0.3308 | 256.0 | 4416 |
| `post_filter` | 2048 | 90.62% | 0.9062 | 2.8879 | 2048.0 | 9129 |
| **`tsng`** | **2048** | 90.62% | 0.9062 | **4.0591** | 2048.0 | 9129 |

> **附注（Gate 为何"通过"）**：该场景 `passed=true`，但：
> - `density_page_read_reduction = 0.0`，`density_candidate_reduction = 0.0`（**两项工作量指标均为零**）
> - `density_p95_speedup = 1.13` 是相对 **`selectivity` 变体**算的，不是相对 `fixed`
> - 若与 `fixed` 比：`density@ef=128` = 1.9094 ms vs `fixed@ef=256` = 0.3308 ms ⇒ **慢 5.8×**
>
> ⇒ 这个"通过"没有实质内容。

### 场景 `vector_graph`（图信号过滤）

| 方法 | 最小 ef | R@10 | NDCG@10 | P95 ms |
|---|---|---|---|---|
| **`industrial_density`** | **64** | 100% | 1.0000 | **0.1829** |
| `industrial_selectivity` | 64 | 100% | 1.0000 | 0.1891 |
| `graph_union` | 64 | 100% | 1.0000 | 0.1896 |
| `industrial_fixed` | 64 | 100% | 1.0000 | 0.2681 |
| **`tsng`** | **256** | 84.37% | 0.9288 | **0.5650** |
| `post_filter` | 2048 | 90.31% | 0.9050 | 2.5224 |

### 场景 `three_signal`（三信号联合）

| 方法 | 最小 ef | R@10 | NDCG@10 | P95 ms | 重排候选 |
|---|---|---|---|---|---|
| **`industrial_fixed`** | 1024 | 83.75% | 0.9570 | **1.1606** | 236.7 |
| `industrial_selectivity` | 1024 | 83.75% | 0.9570 | 1.3759 | 236.7 |
| `industrial_density` | 1024 | 83.75% | 0.9570 | 1.4466 | 236.7 |
| `graph_union` | 1024 | 83.75% | 0.9570 | 1.4851 | 1149.6 |
| **`tsng`** | 1024 | 85.62% | 0.9038 | 1.6598 | 1024.0 |
| `post_filter` | 2048 | 86.56% | 0.8821 | 2.6573 | 2048.0 |

### 2.1 值得注意的三点

1. **没有单一赢家**：三个场景分别由 `bq_prefilter` / `industrial_density` / `industrial_fixed` 胜出。
   ⇒ 工业自适应选择器**并未收敛到一致的最优策略**。
2. **`tsng` 的召回与 `post_filter` 完全相同**（`vector_property`：两者都是 90.62% @ ef=2048，
   `mean_navigation_scores` 都是 9129）⇒ **在该场景下 TSNG 退化为 post-filter 行为**，
   只多了耗时（4.06 vs 2.89 ms）。
3. **`tsng` 在 `three_signal` 场景召回最高（85.62% > 83.75%）却仍不是最快**，
   且 `NDCG@10` 反而更低（0.9038 vs 0.9570）⇒ 召回换不到质量，也换不到延迟。

---

## 3. C0 精确基线（参考）

| 场景 | p50 ms | p95 ms | qps | 候选扫描 | 向量比较 |
|---|---|---|---|---|---|
| `exact_vector` | 29.40 | 30.79 | 33.91 | 100,000 | 100,000 |
| `exact_vector_property` | 26.63 | 31.73 | 36.84 | 100,000 | 1,000 |
| `exact_vector_graph` | 38.04 | 63.77 | 23.68 | 100,000 | 100,000 |
| `exact_three_signal` | 26.03 | 32.07 | 37.46 | 100,000 | 1,000 |

⇒ 精确三信号路径相对精确向量仅 **1.13×**（26.03 vs 29.40 ms）。**机制在精确模式下也没有显著增益。**

---

## 4. 外部效度限制（必须声明）

| # | 限制 | 影响 |
|---|---|---|
| **E1** | **数据是合成的**：`nodes=100,000`、`dim=64`、`CLUSTERS=32`、固定 seed | 合成簇结构未必能体现真实多模态数据的三信号相关性。**"TSNG 无价值"未被完全确立，只确立了"在其自身的合成基准上无价值"** |
| **E2** | 规模小：100K 节点（cohere 实验是 1M） | 小图上路径差异被摊平 |
| **E3** | 属性/图选择性固定 5%（`50_000 ppm`） | 未扫选择性维度 |
| **E4** | 单机、无 AVX-512 | 与 T1/T2 同一口径 |

**⇒ 结论的正确表述是**：**TSNG 在仓库自带的合成基准上，未能在任何场景中胜过更简单的路径，
且 2/3 场景连自身的 Gate 都未通过。** 这足以判定"当前实现没有可发表的正向结果"，
但不足以判定"三信号导航这个想法本身不可行"——后者需要在**真实多模态数据**上重测。

---

## 5. 建议

1. **不要在当前实现上投入论文写作**。三个场景、六条路径、matched-recall 口径下，
   TSNG 一次都没赢，且 Gate 自身给出的理由就是"未降低任何工作量"。
2. **若仍要保留 TSNG 路线**，前置条件是**把它挪到真实数据**（当前是合成簇），
   并**先解释为什么在合成基准上连 Gate 都过不了**——否则换数据只是重新掷骰子。
3. **优先做成本更低的独立核验**：跑 hnswlib / FAISS 竞品基线
   （`pip install hnswlib faiss-cpu`，分钟级），这是任何方向的论文都绕不过的缺口。

---

## 6. 交付物

| 类型 | 路径 |
|---|---|
| 报告（未入库，在 target/） | `target/bench-reports/tsng-c0.json`、`target/bench-reports/tsng-c1-matched-recall.json` |
| 本文 | `docs/research/tsng-c1-baseline-result.md` |
| 源码改动 | **无** |

复现：
```powershell
cargo bench --bench bench_tsng_c0
cargo bench --bench bench_tsng_c1
```

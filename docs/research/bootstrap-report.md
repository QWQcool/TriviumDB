# QuIVer 后继研究 — 阶段0 代码库摸底报告

> **文档性质**：只读分析产物。本次会话未修改任何现有功能代码。
> **基线**：`upstream/dev` @ `043c328`（= 本仓库 `src/` 与上游逐字节一致）
> **研究分支**：`research/quiver2-pipnn-rabitq-tsng`（基于 `043c328` 创建）
> **生成日期**：2026-09-16

## 目录

- [0. 执行摘要](#0-执行摘要)
- [1. 架构地图](#1-架构地图)
  - [1.1 模块全景](#11-模块全景)
  - [1.2 QuIVer 完整实现链路](#12-quiver-完整实现链路)
  - [1.3 冷热分离与持久化](#13-冷热分离与持久化)
  - [1.4 引擎切换（BruteForce ↔ QuIVer）](#14-引擎切换bruteforce--quiver)
  - [1.5 TSNG 现状](#15-tsng-现状)
  - [1.6 评测与回归基础设施](#16-评测与回归基础设施)
- [2. QuIVer 数据结构与复杂度分析](#2-quiver-数据结构与复杂度分析)
- [3. TSNG 实现现状评估](#3-tsng-实现现状评估)
- [4. 研究改造点清单](#4-研究改造点清单)
- [5. 风险与未知项](#5-风险与未知项)
- [6. 与上游（YoKONCy/TriviumDB）的分叉差异](#6-与上游yokoncytriviumdb的分叉差异)
- [7. Git 状态与研究分支](#7-git-状态与研究分支)
- [8. 下一阶段（基线复现 L1）行动清单](#8-下一阶段基线复现-l1行动清单)

---

## 0. 执行摘要

| 项 | 结论 |
|---|---|
| QuIVer 是否可独立替换量化层 | **可以，但需同时改 4 处**（签名结构 / 距离内核 / Store / 序列化），因为 `Bq2Signature` 是 `#[repr(C)] + Pod` 的定长栈结构，直接参与 `.quiver` 落盘 |
| 图构建是否已分区化 | **否**。当前是「单张全局扁平邻接表 + HNSW 式层次 + Vamana RobustPrune」，无分区/簇概念。PiPNN 改造属于**结构性重构**，非局部替换 |
| TSNG 是否可用于论文对照 | **可用于方法级对照**，已有 Recall@K/NDCG@K、7 种 AccessPath 对照、matched-recall 基准与 CI 化 ground truth；但 API 未语义冻结（`src/tsng.rs:6` 自述），且尚无 L 层级（RaBitQ 误差界）的理论量 |
| 评测基础设施成熟度 | **高于预期**。已有 28 个 benchmark、9 数据集自动准备、HNNSW/FAISS/USearch/VSAG + FAISS RaBitQ 基线脚本、CI 80% 行覆盖率门禁、视觉回归基线 |
| 最关键的即时发现 | ①`QuIVer::load_from_bytes` 名为 mmap 加载但实际把每个数组 `collect()` 成独立 `Vec`，**并非零拷贝驻留**；②自动建图存在**双阈值**（`auto_quiver_node_threshold(dim)` vs 硬编码 `10_000`） |

---

## 1. 架构地图

### 1.1 模块全景

```
TriviumDB/
├── src/
│   ├── lib.rs / error.rs / node.rs / vector.rs / filter.rs / hook.rs
│   ├── cognitive.rs            # 认知/疲劳度等业务侧概念
│   ├── observability.rs        # IndexMemoryStats / StorageWriteStats
│   ├── tsng.rs                 # ★ TSNG 三信号导航（实验线，1427 行）
│   ├── index/                  # 派生索引层（全部"可重建加速层"）
│   │   ├── mod.rs
│   │   ├── bq.rs               # ★ BQ/BQ2 量化签名与 SIMD 距离内核（1272 行）
│   │   ├── quiver.rs           # ★ QuIVer BQ-native 图索引（3636 行）
│   │   ├── brute_force.rs      # 精确 Top-K 基线（rayon 并行）
│   │   ├── exact.rs            # 给定 NodeId 集合的精确打分
│   │   ├── property.rs         # 属性索引（Hash/Ordered/Composite/Bitmap）
│   │   ├── art.rs              # ART 有序索引
│   │   └── text.rs             # BM25 + Aho-Corasick 文本索引
│   ├── storage/
│   │   ├── memtable.rs         # ★ 权威内存工作区 + 派生索引协调（2492 行）
│   │   ├── vec_pool.rs         # 分层向量池：mmap 基础层 + delta + COW merged
│   │   ├── file_format.rs      # .tdb/.vec/.quiver/.text sidecar 读写 + meta 校验
│   │   ├── payload_store.rs / graph_blocks.rs / wal.rs / snapshot.rs
│   │   ├── compaction.rs / generation.rs / fs.rs
│   ├── query/
│   │   ├── pipeline.rs         # ★ 算子实现（含 QuiverVectorSearch / 暴力回退）
│   │   ├── cascades.rs         # ★ 物化算子选择 + 成本模型
│   │   ├── planner.rs / parallel.rs / tql_*.rs
│   ├── database/
│   │   ├── mod.rs              # Database 外壳 + SearchHandle（2586 行）
│   │   ├── pipeline.rs         # ★ 查询准备/路由/QuIVer 构建调度（1626 行）
│   │   ├── facade.rs           # 对外门面
│   │   └── config.rs / transaction.rs
│   ├── graph/                  # 业务图算法（reachability/pathfinding/analytics/subset）
│   └── bindings/               # python.rs / nodejs.rs
├── crates/triviumdb-cli, crates/triviumdb-server  # 独立交付物
├── benches/                    # 28 个 benchmark（见 §1.6）
├── scripts/                    # 数据准备 + UI 冒烟 + 视觉基线
└── tests/                      # 25 个测试分类目录
```

**权威数据与派生索引的分界**（`src/index/mod.rs:1-4` 明示）：主文件与 MemTable 是权威数据，所有索引（BQ/QuIVer/属性/文本）均为可重建加速层；sidecar 独立版本化，加载失败按 `MissingIndexPolicy` 决定回退/重筑/fail-closed。

### 1.2 QuIVer 完整实现链路

#### (a) 量化签名生成

| 环节 | 位置 | 说明 |
|---|---|---|
| 维度上限 | `src/index/bq.rs:19-20` | `MAX_BQ_CHUNKS = 48`，`MAX_BQ_DIM = 48 × 64 = 3072` |
| 1-bit 签名 | `src/index/bq.rs:28-77` | `BqSignature { data: [u64; 48] }`，`from_vector` :52（`v > 0.0` 置位），`hamming_distance` :70 |
| **2-bit 签名（生产）** | `src/index/bq.rs:83-141` | `Bq2Signature { pos: [u64;48], strong: [u64;48] }`；`from_vector` :107 先求 `α = mean(|x|)`，再做**双阈值**编码：`v > 0` → `pos` 位；`|v| > α` → `strong` 位 |
| 紧凑 SoA 存储 | `src/index/bq.rs:913-920` | `Bq2Store { pos: Vec<u64>, strong: Vec<u64>, chunks: ceil(dim/64), n }`（按 chunk 交错，同节点两数组相邻） |
| 编码入口 | `src/index/bq.rs:951-981` | `push_from_vector`（一趟求 α + 一趟填位，O(d)） |
| 签名重建 | `src/storage/memtable.rs:1313-1323` | `rebuild_bq_signatures`（复用旧容量，逐 slot 流式读 mmap） |

#### (b) 距离比对

`Bq2Signature::distance`（`src/index/bq.rs:149-188`）是**运行时派发器**：

```
dim % 64 != 0                → distance_scalar           (bq.rs:192)
AVX-512 VPOPCNTDQ + AVX-512F → distance_avx512           (bq.rs:246)
AVX2                         → bq2_distance_raw_avx2     (bq.rs:621)
aarch64 NEON                 → bq2_distance_raw_neon     (bq.rs:727)
其他                          → distance_scalar
```

**加权语义**（`distance_scalar`，`bq.rs:200-235`）：把 pos/strong 两类位组合成 6 个掩码 —— `same∩both_strong`（权重 4）、`diff∩both_strong`（−4）、`same∩one_strong`（2）、`diff∩one_strong`（−2）、`same∩both_weak`（1）、`diff∩both_weak`（−1）；`dot` 累加后返回 `4·dim − dot`，即**值域 `[0, 4·dim]`**。

**廉价距离**（导航专用）：
- `Bq2Store::distance_to_sig_cheap`（`bq.rs:1045-1080`）：只做 `(pos_i ^ pos_j).count_ones() + (strong_i ^ strong_j).count_ones()`，**无权重组合**，值域 `[0, 2·dim]`，成本约为完整距离的 1/3。
- `distance_to_sig_cheap_384`（`bq.rs:1083-1100`）：384 维专用 popcnt 内核，硬编码 `off = idx * 6`。
- 384 维还有专属完整距离/预取路径（`bq.rs:393-423`、`dim384` 系列测试 `bq.rs:1201-1362`）。

**消融开关**：`FORCE_NO_AVX512`（`bq.rs:11`，环境变量 `TRIVIUM_NO_AVX512=1`）、`FORCE_NO_384_KERNEL`（`bq.rs:13`）。注意 AVX-512 内核带 `#[cfg(not(coverage))]`，**CI 覆盖率统计不包含这些分支**。

**预取**：`Bq2Store::prefetch_sig`（`bq.rs:1002-1029`），x86 用 `_mm_prefetch(T0)`，chunks>8 时补第二条 cache line。

#### (c) 图构建

数据结构：
- `QuIVer`（`src/index/quiver.rs:915-947`）持有：`bq_store`（hot）、`layer0: FlatAdj`（hot）、`upper_layers: Vec<Vec<Vec<u32>>>`、`node_max_layer: Vec<u8>`、`ids: Vec<u64>`、`slot_indices: Vec<usize>`、`id_to_internal: HashMap<u64,u32>`、`tombstones: Vec<bool>`、`dirty_count`、`prefilter_slot_cache`、`visited: Bitset`。
- `FlatAdj`（`quiver.rs:200-420`）：**单张全局扁平邻接表**，布局 `[degree, nb0..nb_{stride-2}]`，`stride = m0*2 + 1 = 4m + 1`（2× headroom，为惰性剪枝留空间）。空槽哨兵 `EMPTY_NB = u32::MAX`（`:198`）。
- `ConcurrentFlatAdj`（`quiver.rs:424-561`）：`Box<[UnsafeCell<u32>]>` + 分条自旋锁 `StripedSpinLocks`（`:225-281`，条纹数 `clamp(nodes,256,65536).max(m*64)` 向上取 2 的幂，`lock_timed` 提供自旋等待计时）。
- 层次分配：`QuIVer::random_level`（`:1025-1031`），`ml = 1/ln(m)` → **HNSW 式几何层次**。

构建路径（三条）：

| 入口 | 位置 | 用途 |
|---|---|---|
| `insert` | `quiver.rs:1033-1211` | 单节点增量：高层贪心下降 → `beam_search_upper` → 逐层 `vamana_select` + **全量双向重剪**（每条反向边都跑一次 O(deg²) 剪枝） |
| `batch_build` | `quiver.rs:2140-2305` | rayon 并行算签名后**顺序**插入（旧路径） |
| **`batch_build_from_store`** | `quiver.rs:2326-2408` | **生产路径**。外部已编码 `Bq2Store` → 每 256 个节点一批 `into_par_iter` → `connect_node_fast` → 全部 `final_prune` |
| `batch_build_experimental_v2*` | `quiver.rs:2307/2316/2434/2533` | 兼容入口（`memtable.rs:1496` 仍调用 v2 版本） |

核心算法件：
- `ExperimentalBuildView`（`quiver.rs:563-834`）：`beam_search_l0_locked`（`:578`，建图期 beam search，用**完整** 2-bit 距离）→ `connect_node_checked`（`:635`，eager）/ `connect_node_fast`（`:696`，惰性）→ `final_prune`（`:817`，把 `deg > m0` 一次性收敛）。
- `QuIVer::vamana_select`（`quiver.rs:1627-1671`）：Vamana RobustPrune（`α` 放宽），判定式 `dist(c, s) < α · dist(c, target)`（`:1646-1649`）；选不满 `max_k` 时**按距离序补足**（`:1656-1668`）——注意这一点与原始 Vamana（不补足）不同，会牺牲部分多样性。
- **惰性剪枝**（`quiver.rs:755-805`）：邻接表未满则 `push_neighbor_raw` O(deg)，仅当容量用尽才触发完整剪枝。注释自述把昂贵的 `vamana_select` 从「每条反向边」降到「约每 m0 条一次」。
- 随机采样候选（`quiver.rs:652-662` / `:720-730`）：除 beam search 结果外，额外注入 `ef.min(128).max(m0*2)` 个**确定性伪随机**（splitmix 变体）节点作为候选，缓解早期图稀疏。
- 性能探针 `BuildProfile`（`quiver.rs:285-356`），环境变量 `TRIVIUM_BUILD_PROFILE=1`，分段统计 bitset/beam/前向/反向锁等待/反向工作。
- A/B 开关：`TRIVIUM_EAGER_PRUNE=1`（`quiver.rs:2379`、`:2483`）恢复「每条边全量剪枝」。

MemTable 侧接线：`quiver_build_snapshot`（`memtable.rs:1405-1433`）→ `build_quiver_snapshot`（`:1435-1444`）→ `publish_quiver_if_current`（`:1446-1457`，代际校验防并发覆盖）→ `build_quiver_impl`（`:1463-1509`，流式读 mmap、跳过 tombstone）。峰值内存估算在 `quiver_build_peak_bytes`（`memtable.rs:1236-1260`）。

调度方：`src/database/pipeline.rs:137-186`（内存上限检查 → 拿构建锁 `try_start_quiver_build` → 锁外构建 → 代际校验后发布）。

#### (d) 查询导航

`QuIVer::search`（`quiver.rs:1684-1695`）→ `search_with_scorer`（`:1941-2060`）：

1. **高层贪心下降**（`:1962-1984`）：逐层沿最邻近邻居下降，全 BQ 距离。
2. **Stage 1 — Layer0 beam search**：`beam_search_l0_impl`（`:1255-1326`）或 384 维专用 `beam_search_l0_384_with_scorer`（`:1499-1564`）。导航用 `distance_to_sig_cheap`，结果集最后用**完整** 2-bit 距离重排（`:1317-1323` / `:1555-1561`）。
   - `visited` 与 384 维 scratch 用 `thread_local!` 复用（`:1988-1991`），避免每查询堆分配。
3. **Stage 2 — f32 精排**（`:2037-2059`）：对 `rerank_limit` 个候选调 `get_vec_f32(slot, buf)` 回调取冷向量，`tombstones` 与 `scorer.accept_result` 双重过滤，用 `cosine_similarity_f32` 打分。384 维走 `rerank_candidates_384`（`:2062-2104`，带查询范数复用）。

其他搜索入口：
- `search_dual_queue`（`:1858-1938`）+ `beam_search_l0_dual`（`:1328-1497`）：TSNG 专用，vector/signal 双优先队列按 `signal_quota_ppm` 配额交错出队与合并。
- `prefilter_candidates`（`:1759`）/ `prefilter_candidates_profiled`（`:1771-1855`）：纯 BQ2 粗排 + `PrefilterSlotCache`（`:836-913`，LRU 64MB 上限，key = `(posting_identity, property_generation)`）。
- `vector_density_skew`（`:1701-1754`）：候选集合 BQ2 空间相对密度（等距采样 + 相邻对均值）。
- `search_flat`（`:2110-2131`）：连续数组便捷封装（测试/纯内存）。

**扩展点**：`NavigationScorer` trait（`quiver.rs:46-52`）只有 2 个方法 —— `score(node_id, bq_distance) -> u32`（越小越优先）与 `accept_result(node_id) -> bool`（结果过滤钩子）。默认实现 `BqNavigationScorer`（`:56-63`）恒等返回 `bq_distance`，即"与历史 QuIVer 完全等价"。

#### (e) 增量插入与墓碑删除

| 机制 | 位置 | 行为 |
|---|---|---|
| 增量插入（单节点） | `memtable.rs:807-818`（insert）、`:878-890`、`:2530-2541`（update_vector） | 若索引存在且未暂停同步 → `quiver.insert(...)` + `dirty_count_inc()` |
| 事务内暂停 | `memtable.rs:396-398`、`:1364-1368` | `quiver_sync_paused`，commit 期间不同步，commit 后由 `quiver_sync_tx_entries`（`:1531-1586`）回放 WAL 条目统一同步 |
| 墓碑 | `quiver.rs:2821-2835` `soft_delete` | 只置 `tombstones[idx] = true` + `dirty_count += 1` + 清空 prefilter 缓存；**节点仍参与图遍历作为中转**（不修拓扑） |
| 退化重建阈值 | `quiver.rs:2839-2841` `needs_rebuild` | `n > 0 && dirty_count * 4 > n`（即 **>25%**） |
| 丢弃点 | `memtable.rs:815-818`、`:886-889`、`:1518-1523`、`:1565-1567` | 超过阈值 → `quiver_index = None`，下次查询前自动重建 |
| 计数接口 | `quiver.rs:2845/2851/2857` | `active_count` / `total_count` / `dirty_count_inc` |

**关键观察**：`update_vector` 走的是「soft_delete 旧 + insert 新」（`memtable.rs:2534-2537`），因此一次更新会**消耗两个 dirty 配额**，且旧节点永久留在图里当中转。`insert`（`quiver.rs:1033`）是**单线程全量双向重剪**，增量吞吐远低于批量构建 —— 这是 PiPNN 分区式构建最直接的收益来源。

#### (f) 冷热分离

| 层 | 内容 | 驻留 | 位置 |
|---|---|---|---|
| **Hot** | BQ2 签名（`Bq2Store`）+ Layer0 扁平邻接表 + upper layers + id↔slot 映射 + tombstones | 常驻内存 | `quiver.rs:924-928` |
| **Cold** | f32 原始向量（`.vec` 文件，mmap MAP_PRIVATE） | 按需分页 | `src/storage/vec_pool.rs` |
| 冷读接口 | `get_vec_f32(slot, buf) -> bool` 闭包回调 | — | `quiver.rs:1684-1691` |
| 访问建议 | `advise_random()`（图遍历随机访问） | — | `memtable.rs:1455`、`:1502`；`vec_pool.rs:69-74` madvise 封装 |
| 内存统计 | `quiver.rs:2739-2764` `stats()` → `hot_bytes = bq_store.hot_bytes + layer0.data.len()*4 + upper 估算` | — | `observability.rs` |

对 `merge` 缓存的精细控制：`ensure_vectors_cache(materialize_flat)`（`memtable.rs:1286-1310`）在纯 QuIVer 路径下**不物化** merged（避免把整个 mmap 复制入堆）；`materialize_flat = force_brute_force || payload_filter.is_some()`（`database/pipeline.rs:149`）。

### 1.3 冷热分离与持久化

#### `.quiver` 文件（POD memcpy）

`QuIVer::save_to_file`（`quiver.rs:2879-2966`），格式注释在 `:2866-2878`：

```
[Magic "QUIV" 4B] [Version u32 4B] [Header 40B: dim,n,m,m0,ef_c,alpha,entry_point,max_level,dirty_count,reserved]
[BQ chunks u32] [pos: n×chunks×8B] [strong: n×chunks×8B]
[Layer0 FlatAdj: n × stride × 4B]
[Tombstones: n × 1B]
[IDs: n × 8B]
[SlotIndices: n × 8B (写作 u64)]
[NodeMaxLayer: n × 1B]
[Upper Layers: u32 num_upper + 每层 u32 node_count + 每节点 (u16 deg + deg×u32)]
```

- `QUIVER_VERSION = 1`（`quiver.rs:2864`）+ `QUIVER_MAGIC = b"QUIV"`（`:2863`）。
- 原子写：先写 `{path}.quiver.tmp` → `sync_all` → Windows 先 `remove_file` 再 `rename`（`:2949-2957`）。
- 文档瑕疵：注释写 `n × 128B`，实际单节点签名 = `16 · ceil(dim/64)` 字节（128B 对应 512 维；768 维为 192B）。

`load_from_bytes`（`quiver.rs:2975-3302`）：
- 全字段边界检查，`checked_end`（`:2980-2990`）防乘加溢出；维度 / chunks / entry_point / max_level / upper layer 数量 / 邻居越界 / ID 重复为 0 等逐项拒绝；反序列化固定头部截断、畸形计数、48 字节 fuzz 样本均有专门测试（`:3891/3910/3927/3947`）。
- ⚠️ **重要性能观察**：`load_from_file`（`:2969-2973`）用 `memmap2::MmapOptions::new().map(&file)` 建立 mmap，但 `load_from_bytes` 内部把所有数组 `.collect()`/`.to_vec()` 复制进**新的 `Vec`**（`:3092-3103` 签名、`:3126-3131` Layer0、`:3153-3158` IDs、`:3169-3174` SlotIndices、`:3185` NodeMaxLayer、`:3233-3242` upper adj）。也就是说文件映射只是"零拷贝**读取**"，**并未零拷贝驻留**；进程内存仍≈ hot_bytes，PageCache 另有一份。这会影响 §5 的 SSD 冷/热实验口径。

#### `.quiver.meta`（提交点）

- 路径：`file_format.rs:281-283` → `{db}.quiver.meta`
- 写：`write_quiver_meta`（`file_format.rs:285-308`），48B，Magic `QMET` + version 1 + `tdb_size` + `vec_size` + `quiver_size` + `node_count` + `dim` + `quiver_crc32`
- 校验：`validate_quiver_meta`（`file_format.rs:310-339`），三项文件尺寸 + 节点数 + 维度 + **quiver 文件 CRC32** 全部匹配才认账
- 落盘：`file_format.rs:401-423`（`save` 后顺带持久化 quiver + meta；quiver 不存在时清理残留两个文件）
- 加载：`file_format.rs:1556-1614`（sidecar 缺失/校验失败/解析失败三态，按 `MissingIndexPolicy` 决定 Err 或静默回退；`repair_sidecars` 为真时删除坏文件）

#### `.vec`（冷向量）

`src/storage/vec_pool.rs`：`MAP_PRIVATE` mmap 基础层（磁盘只读、COW 私有页）+ 内存 `delta` 层 + 惰性 `merged` 连续视图；`flush` 按 `has_dirty_base` 选 O(delta) 追加或 O(total) 原子重写。

### 1.4 引擎切换（BruteForce ↔ QuIVer）

#### 阈值定义

```rust
// src/storage/memtable.rs:21-30
const AUTO_QUIVER_TARGET_COMPONENTS: usize = 8_000_000;
const AUTO_QUIVER_MIN_NODES: usize = 2_500;
const AUTO_QUIVER_MAX_NODES: usize = 10_000;

pub fn auto_quiver_node_threshold(dim: usize) -> usize {
    AUTO_QUIVER_TARGET_COMPONENTS
        .div_ceil(dim.max(1))
        .clamp(AUTO_QUIVER_MIN_NODES, AUTO_QUIVER_MAX_NODES)
}
```

即 **`threshold(dim) = clamp(ceil(8_000_000 / dim), 2500, 10000)`** —— 语义是「让暴力扫描的近似向量分量工作量（n × dim）达到 8M 个分量」。

实际取值：
| dim | ceil(8e6/dim) | 生效阈值 |
|---|---|---|
| 128 | 62500 | 10000 |
| 384 | 20834 | 10000 |
| 512 | 15625 | 10000 |
| 768 | 10417 | 10000 |
| 1024 | 7813 | **7813** |
| 1536 | 5209 | **5209** |
| 3072 | 2605 | **2605** |

`clamp` 的含义：**dim ≤ 768 时阈值一律 10000；dim ∈ (800, 3072] 时才真正按分量模型缩放**。

#### 判据与路由

| 环节 | 位置 | 逻辑 |
|---|---|---|
| 是否需要自动建图 | `memtable.rs:1205-1210` `auto_quiver_build_needed` | `dim ≤ MAX_BQ_DIM && auto_build_quiver && payloads.len() ≥ threshold(dim) && quiver_index.is_none()` |
| ⚠️ 另一处硬编码 | `memtable.rs:1296-1302` `ensure_vectors_cache` | 用**硬编码 `active >= 10_000`**，未走 `threshold(dim)` |
| 准备调度 | `database/pipeline.rs:153-186` | `auto_quiver_build_needed()` → 内存峰值检查 → `try_start_quiver_build` 拿锁 → 锁外 `build_quiver_snapshot` → `publish_quiver_if_current`；随后 `prepare_search_cache(materialize_flat)` |
| 主查询路由 | `database/pipeline.rs:288-295` | `route = if !force_brute_force && mt.quiver().is_some() { quiver } else { brute }`，写入 observation `vector_route_quiver` |
| 查询内回退 | `database/pipeline.rs:560-575` | `quiver_pipeline` 因 payload 过滤导致结果不足时 → `brute_force_pipeline` 精确扫描 |
| 算子级选择 | `query/cascades.rs:1304-1353` | `QueryEntry::Search { .. } if mt.quiver().is_some() → QuiverVectorSearch`，否则 `ExactVectorSearch` |
| 成本模型 | `query/cascades.rs:1334-1340` | approximate: `rows.max(1).ilog2() as f64 * dim`；exact: `node_count * dim` |
| 属性 | `query/cascades.rs:1416-1431` | QuIVer = `Approximate` + `ApproximateSimilarity`；Exact = `Exact` + `ExactSimilarity` |
| 算子实现 | `query/pipeline.rs:607-668` | `QuiverVectorSearch`，无索引时退化为 `ExactVectorSearch`（`:625-631`） |
| 维度超限回退 | `memtable.rs:1206/1296/1359/1392`、`quiver.rs:995/3026` | `dim > 3072` → 不建/不存/不加载，直接 BruteForce |
| BruteForce 实现 | `index/brute_force.rs:12` `search`、`:47` `search_filter_map` | rayon `par_chunks` 并行 + 稳定排序（线程数不改结果） |

> **双阈值不一致**：生产实际生效的是 `auto_quiver_build_needed()` 的 `threshold(dim)`；`ensure_vectors_cache` 内的 `10_000` 只在 dim ∈ (800, 3072] 时与之不符，且该函数主要被测试路径以 `materialize_flat=true` 调用（`pipeline.rs:1084/1116/1139/1155/1186/1270/1286`）。属**语义重叠的冗余判据**，不是活跃缺陷，但改造时需统一。

### 1.5 TSNG 现状

`src/tsng.rs`（1427 行）自述「实验性混合检索研究线…该 API 尚未语义冻结，不应与生产默认的 TQL/search 管线混为一谈」（`tsng.rs:1-6`）。

#### 公开类型

| 类型 | 位置 | 备注 |
|---|---|---|
| `GraphSignalQuery` | `tsng.rs:19-25` | `anchor_id` / `direction` / `labels` / `min_edge_weight` / `max_hops` |
| `TsngWeights` | `tsng.rs:28-42` | `{vector, property, graph}`，默认 `{1.0, 0.0, 0.0}` |
| `TsngBudget` | `tsng.rs:45-61` | 候选/访问节点/扫描边/前沿四项预算（默认 1e6/1e6/5e6/1e6） |
| `TsngQuery` | `tsng.rs:64-71` | `vector` / `payload_filter` / `graph` / `top_k` / `weights` / `budget` |
| `TsngHit` | `tsng.rs:74-82` | 逐信号分项：`final_score` / `vector_similarity` / `vector_signal` / `property_signal` / `graph_signal` / `graph_depth` |
| `TsngCost` / `TsngGroundTruth` | `tsng.rs:85-97` | 精确基线成本（候选/属性检查/向量比较/图访问节点/图扫描边） |
| **`TsngSearchConfig`** | `tsng.rs:100-121` | 4 个旋钮（见下） |
| **`TsngSearchMetrics`** | `tsng.rs:124-148` | 25 个指标字段 |
| `IndustrialAccessPath` | `tsng.rs:152-161` | 7 种对照策略枚举 |
| `QueryMemoryBudget` | `tsng.rs:164-194` | 默认 8MB 候选 id / 1.6MB union / 256MB 精排向量 / 1e6 页读 |
| `BeamAdaptation` | `tsng.rs:196-201` | `Fixed` / `Selectivity` / `SelectivityAndDensity` |
| `IndustrialSearchConfig` | `tsng.rs:203-240` | 工业路径配置（direct 12MB / union 128MB 精排字节） |
| `TsngQualityMetrics` | `tsng.rs:248-252` | `recall_at_k` / `ndcg_at_k` |

#### 三路信号权重如何计算

**导航期**（`TsngNavigationScorer`，`tsng.rs:284-358`）：

```rust
// tsng.rs:254
const NAVIGATION_SCALE: u32 = 1_000_000;

// tsng.rs:295-315  构造：权重归一化到 1e6
let sum = weights.vector + weights.property + weights.graph;
let fixed = |w: f32| ((w / sum) * NAVIGATION_SCALE as f32).round() as u32;
property_weight = fixed(weights.property);
graph_weight    = fixed(weights.graph);
max_bq_distance = (dim * 2).max(1);       // 对应 cheap 距离值域上界

// tsng.rs:326-357  score()
vector_distance = min(bq_distance, max_bq_distance) * 1e6 / max_bq_distance;
property_signal = property_match(node) ? 1e6 : 0;
graph_signal    = clamp(graph_signals[node].0, 0, 1) * 1e6;
property_bonus  = property_weight * property_signal / 1e6;
graph_bonus     = graph_weight    * graph_signal    / 1e6;
metadata_bonus  = property_bonus + graph_bonus;
bonus_cap       = vector_distance * metadata_bonus_cap_ppm / 1e6;
final           = vector_distance.saturating_sub(min(metadata_bonus, bonus_cap)).min(1e6)
```

**语义**：属性/图信号**不改变向量距离本身，只做有界抵扣**（"bonus"），且抵扣上限 = 向量距离的 `metadata_bonus_cap_ppm / 1e6` 比例。默认 `200_000` → 最多抵消 20% 向量距离。这是一个**保守设计**（保底不劣化纯向量召回），代价是信号影响很弱。

**精排期**（`exact_rerank_candidates`，`tsng.rs:1101-1148`）：

```rust
// tsng.rs:1107, 1124-1128
weight_sum    = w.vector + w.property + w.graph;
vector_signal = ((cosine_similarity + 1.0) * 0.5).clamp(0.0, 1.0);
final_score   = (w.vector * vector_signal
               + w.property * property_signal
               + w.graph * graph_signal) / weight_sum;
```

注意：导航期与精排期是**两套不同公式**（一个是有界抵扣、一个是加权平均），存在**排序不一致风险**（导航认为近的候选，精排后可能排在后面）。这是 TSNG 目前最值得理论化的地方。

**图信号取值**（`exact_graph_signals`，`tsng.rs:1275-1336`）：从 `anchor_id` 做 BFS（受 `max_hops` / `labels` / `min_edge_weight` 约束），`signal = 1.0 / depth`（`:1329`），深度从 1 起算，anchor 自身被移除（`:1325`）。

**属性信号**：`filter.matches(&payload)` 二值 → 1.0/0.0（`:1112-1119`）。快路径用 `Filter::extract_must_have_mask` + `fast_tag_for_id` 位图（`:1008-1023`）。

#### 实验开关（当前默认值）

| 旋钮 | 类型 | 默认 | 作用 | 生效位置 |
|---|---|---|---|---|
| `ef_search` | usize | `max(16·k, 64)` | Layer0 beam 宽度 | `tsng.rs:114` |
| `candidate_pool` | usize | `max(16·k, 64)` | 候选池大小 | `tsng.rs:115` |
| `metadata_bonus_cap_ppm` | u32 | **200_000** | 元数据最多抵扣向量距离的比例（20%） | 导航 `score` `tsng.rs:352-355` |
| `signal_queue_quota_ppm` | u32 | **0（关闭）** | 双队列中 signal 队列的扩展配额 | `beam_search_l0_dual` `quiver.rs:1420-1429`、合并 `:1467-1486` |
| `graph_seed_limit` | usize | **0（关闭图通道）** | 注入 signal 队列的业务图候选上限 | `tsng.rs:1062-1079` |

`signal_queue_quota_ppm = 0 && graph_seed_limit = 0` 时 `approximate_search` 退化为普通 `search_with_scorer`（`tsng.rs:1080-1091`），即默认行为下 TSNG 与 QuIVer **只差一个 scorer**。这是上手实验最方便的切入点。

**实验/对照策略**（全部 `pub(crate)`，经 `Database` 暴露）：

| 策略函数 | 位置 | 说明 |
|---|---|---|
| `approximate_search` | `tsng.rs:990-1099` | **主实验路径**。纯向量权重 → 原始 QuIVer scorer；否则 `TsngNavigationScorer` + 可选 dual-queue |
| `post_filter_search` | `tsng.rs:936-988` | 串行对照：原始 ANN 后完整过滤 |
| `graph_union_search` | `tsng.rs:858-934` | ANN ∪ 精确图候选并集 |
| `bq_prefilter_search` | `tsng.rs:797-856` | BQ2 粗排强基线 |
| `industrial_search` | `tsng.rs:509-795` | 7 种 AccessPath 成本模型自动选择 |
| `exact_ground_truth` | `tsng.rs:1150-1220` | ground truth（含图信号） |
| `quality_metrics` | `tsng.rs:1381-1437` | Recall@K + NDCG@K |

`Database` 侧 API：`database/mod.rs:1839`（ground truth）、`:1848`（`search_tsng`）、`:1858`、`:1868`、`:1878`、`:1888`；门面 `database/facade.rs:73-100`。

**工业路径自适应**（`industrial_search`，`tsng.rs:509-795`）：
- 5 条候选路径成本估算（`:556-602`）→ 排序取最优 → `access_path`
- `selectivity_ef = candidate_pool · node_count / selectivity`（`:568-577`）
- `BeamAdaptation::SelectivityAndDensity` 时再乘 `sqrt(vector_density_skew)`（`:639-644`），并 clamp 到 `[ef_search, 2·selectivity_ef]`
- 密度来源：`memtable.cross_modal_stats` → `vector_density_skew`（`memtable.rs:2084-2086`）

### 1.6 评测与回归基础设施

#### benchmark（28 个，全部在根 `Cargo.toml` 显式注册，`autobenches = false`）

| 分类 | 套件 |
|---|---|
| A 日常能力 | `bench_queries`、`bench_indexes_and_leiden`、`bench_index_graph_baseline`、`bench_memory_pressure`、`ci_report` |
| B 三模管线 Gate | `bench_tsng_c0`、`bench_tsng_c1`、`bench_tsng_pipeline`、`bench_pipeline_gate` |
| C 图/查询并行 | `bench_query_parallel`、`bench_graph_parallel`、`bench_deep_traversal` |
| **D QuIVer 规模与质量** | `bench_cohere1m`、`bench_random1m`、`bench_random_sphere`、`bench_recall_at_k`、**`bench_rbq2_precision`**、`bench_sensitivity`、`bench_quiver_ablation` |
| E 研究消融（需 `--features ablation`） | `bench_encoding_ablation`、`bench_ssd_cold_hot`、`bench_variance` |

#### Ground Truth 与 Recall 评测

- `benches/bench_cohere1m.rs` 是主评测器：`exact_flat_topk_normalized`（`:226`）、`brute_force_topk`（`:256`），输出 `ef / rerank / Recall@10 / MT-QPS / lat(ms) / vs BF`（`:539-588`），`TRIVIUM_RESULT_PATH` 落 JSON（`:604-630`）。
- 增量衰减实验：`TRIVIUM_ANN_INCREMENTAL`（先批量构建 f%，再增量插入剩余），用于**佐证 25% 重建阈值**（`bench_cohere1m.rs:355-369`）。
- 9 数据集自动准备：`scripts/prepare_all.py`（cohere/minilm/bge_m3/dbpedia1536/dbpedia3072/wolt_clip/sift128/gist960/glove100）；`scripts/prepare_msmarco.py`（1M/5M 可扩展性）；`scripts/convert_hdf5_to_f32.py`（VIBE）；`scripts/convert_to_fbin.py`（DiskANN）。
- **竞品基线**：`benches/bench_baselines.py`（hnswlib / FAISS HNSW / USearch / VSAG，支持 `BASELINES` 环境变量选择与 `TRIVIUM_BL_M/EFC/EF` 参数扫描）；`benches/bench_rabitq_refine.py`（FAISS IVF + RaBitQfs + Refine）。
- **BQ2 vs RaBitQ 公平对比**：`benches/bench_rbq2_precision.rs`（100K×768；BQ2 2-bit SM 无旋转 vs RaBitQ-sym 4 轮 FHT-Kac 旋转 + 1-bit + Hamming vs RaBitQ-asym 旋转 + 1-bit + f32 非对称点积 + 修正因子）。这是**未来 RaBitQ 替换工作的第一个对拍基准**。
- 任务要求对比的竞品中，**Milvus QG / Filtered-DiskANN / ACORN 目前尚无脚本**，仅有 hnswlib / FAISS(HNSW, IVF+RaBitQ) / USearch / VSAG。

#### CI 与门禁（`.github/workflows/`）

| Workflow | 内容 | 是否门禁 |
|---|---|---|
| `ci.yml` | `check`（fmt/clippy）、`test`（`:127` `cargo test --lib --tests -- --test-threads=1`）、doc test、CLI test、ARM64 QEMU、ASan | ✅ |
| `ci.yml:375-414` **Coverage Gate** | `cargo llvm-cov --workspace --exclude triviumdb-cli --lib --tests`；`:405` `--fail-under-lines 80` | ✅ **行覆盖率 80%** |
| `fault-injection.yml` | `long_running soak`、`fault_io`、`fault_power`、`fault_crash`、`fault_hardware`、`compaction_core` | ✅ |
| `fuzz.yml` | cargo-fuzz | ✅ |
| `benchmark-reports.yml:4` | 「所有 benchmark job 都只产出报告 artifact，**不作为合并门禁**」 | ❌ 仅报告 |
| `webui.yml` | fork 侧新增（WebUI 冒烟 + 视觉回归） | ✅（与本研究无关） |

**覆盖率排除了 bench target**（`ci.yml:397-399` 注释明确），所以新加的 benchmark 不会拖累 80% 门禁 —— 这对研究期快速加 bench 很重要。

#### 其他回归资产

- `tests/` 25 个分类：`contracts` / `core` / `differential` / `fault_allocator|crash|hardware|io|lock|power` / `format_mutation` / `format_spec` / `generation` / `graph` / `hardening` / `long_running` / `model` / `node` / `pipeline` / `python` / `query` / `storage` / `tools` / `unit` / `visual` / `concurrency`
- TSNG 专项：`tests/pipeline/tsng_c1.rs`（896 行，覆盖 dual-queue / seed limit / bonus cap / beam adaptation 组合）
- 格式变异测试：`tests/format_mutation/`（对 `.quiver` 的畸形输入容错）—— 改序列化格式时必须同步维护
- 视觉回归：`scripts/visual-baseline.mjs` + `tests/visual/baseline/win32/*.png`（7 张，与本研究无关）
- `docs/TEMP-TODO/triviumdb-roadmap.md`、`triviumdb-engineering-plan.md` 等规划文档（**注意**：`Cargo.toml` 的 `exclude` 目录名写成 `docs/TEMP-todo/**`，与实际 `TEMP-TODO` 大小写不符，属无害笔误）

---

## 2. QuIVer 数据结构与复杂度分析

### 2.1 符号

| 符号 | 含义 | 默认值 |
|---|---|---|
| `n` | 节点数 | — |
| `d` | 维度（≤ 3072） | 768 |
| `C` | `ceil(d / 64)` 个 u64 chunk | 12（d=768） |
| `m` | 图最大度（`QuIVerConfig.m`） | 16（论文口径 32） |
| `m0` | Layer0 最大度 = `2m` | 32（论文口径 64） |
| `S` | `FlatAdj.stride = 4m + 1` | 65（m=16）/ 129（m=32） |
| `ef_c` | `ef_construction` | 128 |
| `ef_s` | `ef_search` | 变量（64~1024） |

### 2.2 内存布局（单节点）

| 组件 | 字节 | d=768, m=32 时 |
|---|---|---|
| BQ2 签名（pos + strong） | `16·C` | 192 |
| Layer0 邻接表 | `4·S = 16m + 4` | 516 |
| Upper layers | 摊销 `~4m + 24` /节点/层 × `max_level` 层 | 小（`max_level ≈ log_m n`） |
| `tombstones` | 1 | 1 |
| `ids` | 8 | 8 |
| `slot_indices` | 8（`usize`） | 8 |
| `node_max_layer` | 1 | 1 |
| `id_to_internal` HashMap | 摊销 ~24–32 | ~28 |
| **合计 hot** | | **≈ 754 B/节点** |

→ 1M 节点 ≈ **754 MB**；5M 节点 ≈ 3.8 GB（不含 `upper_layers` 的实际分配开销与 HashMap 装载因子浪费）。BQ 部分只占 25%，**邻接表是 hot 内存主项** —— 这是 PiPNN 分区化（按分区压缩邻接表）在内存维度上的直接收益点。

### 2.3 构建复杂度

**（旧）`batch_build`**（`quiver.rs:2140`）：签名并行 O(n·d / T)，然后**顺序**插入，每节点 `beam_search_l0` + 逐层 `vamana_select` + **每条反向边全量重剪**：
```
T_build = O( n · [ ef_c·m0·C + ef_c·C + m0 · (m0·C + m0²·C) ] )
        = O( n · ef_c · m0 · C + n · m0³ · C )    ← 反向全量剪枝是主项
```

**（生产）`batch_build_from_store`**（`quiver.rs:2326`）：
- 每节点：1 次 `beam_search_l0_locked`（`O(ef_c·m0)` 次**完整** 2-bit 距离）+ 1 次前向 `vamana_select`（`O(ef_c·m0)` 次距离）
- 反向：**惰性追加** O(deg)，仅约每 `m0` 条反向边触发一次 `vamana_select`（`O(deg²)`，`deg ≤ 2m0`）→ 摊销 `O(m0 · C)` 每次反向边
- `final_prune`：`O(n)` 次单节点剪枝

```
T_build = O( n · [ ef_c·m0·C + ef_c·m0·C + m0 · (m0·C) ] )
        = O( n · ef_c · m0 · C )                    ← 主项
并行度：÷ T（每轮 256 节点 par_iter；反向边加条带锁，测得为主要争用源）
```

代入 d=768 (C=12), m=32 (m0=64), ef_c=128 → 每节点 ≈ `128 × 64 × 2 × 12 ≈ 2.0×10⁵` 次 u64 popcount 操作 ≈ `2.0×10⁵ / 8 ≈ 2.4×10⁴` 条 AVX-512 指令。

> **论文口径对照**：README_QUIVER.md §5.7 报告 5M 向量（1024 维）构建；`bench_cohere1m` 的增量实验用于测「增量图 vs 全量重建图」的 recall 衰减以佐证 25% 阈值。

**增量插入 `insert`**（`quiver.rs:1033`）**是 O(n)-级别的单次成本**：
```
T_insert = O( ef_c·m0·C  +  m0 · (m0·C + m0²·C) )
         = O( ef_c·m0·C + m0³·C )     ← 反向全量重剪（非惰性！）
```
单线程、每条反向边都跑 `vamana_select`。**这与批量路径的惰性剪枝优化不对称**，是大规模增量写入的明确瓶颈，也是 PiPNN「避免全量 KNN 图构建开销」能对上的痛点。

### 2.4 查询复杂度

`search_with_scorer`（`quiver.rs:1941`）：

```
高层贪心下降:  O(max_level · m) 次 BQ 距离   (max_level ≈ log_m n)
Stage 1 beam:  O(ef_s · m0) 次 cheap 距离  +  O(ef_s · C) 次完整距离重排
Stage 2 精排:  最多 rerank_limit ≤ ef_s 次冷向量读取 O(d) + 余弦 O(d)
```

```
T_query = O( ef_s · m0 · C  +  ef_s · C  +  ef_s · d )
        = O( ef_s · (m0·C + d) )
```
- **计算项** `ef_s · m0 · C`：d=768, m0=64, ef_s=128 → `128×64×12 ≈ 9.8×10⁴` 次 u64 popcount ≈ 1.2×10⁴ 条 AVX-512 指令。
- **I/O 项** `ef_s · d`：d=768, ef_s=128 → 128 × 768 × 4B = **393 KB 冷读/查询**（随机页，页粒度 4KB → 最多 ~128 次随机页读）。**冷路径的 I/O 是 QPS 上界的主约束**，与 `bench_ssd_cold_hot` 的测量目标一致。

**384 维专用路径**（`bq.rs:393/423/1083` + `quiver.rs:1499/2062`）：用硬编码 chunk 数（6）与专用 popcnt 内核，绕过运行时派发与通用循环。这是维度特化优化的先例 —— RaBitQ 若替换编码，**需要重新评估这类特化内核的收益**（RaBitQ 的旋转使"按维度切片"不再直接对应原始语义）。

**内存 peak**：查询期额外 `O(ef_s)` 候选堆 + `O(n/64)` visited bitset（thread_local 复用，`quiver.rs:1988-1991`）。

### 2.5 持久化复杂度

| 操作 | 复杂度 | 备注 |
|---|---|---|
| `save_to_file` | `O(hot_bytes)` 顺序写 + 2 次 fsync | 原子 tmp → rename；Windows 需先 delete |
| `load_from_bytes` | `O(hot_bytes)` 读 + **一次完整复制**（mmap → 各 `Vec`） | 维度/chunks/邻接/ID 逐项校验 |
| `.quiver.meta` 校验 | `O(|quiver|)` **CRC32 全文件扫描** | `file_format.rs:294` + `:322`，每次打开数据库都做 |
| 文件大小（d=768, m=32） | `n × (192 + 516 + 18) + upper ≈ 726 B/节点` | 1M 节点 ≈ 726 MB |

> **两处值得改造的持久化成本**：
> 1. `load_from_bytes` 非零拷贝（§5 风险 R2）—— 直接复制会让"热数据驻留"的成本翻倍（PageCache + 进程堆）。
> 2. `validate_quiver_meta` 每次打开数据库全量 CRC32 一个数百 MB 文件（§5 风险 R3）—— 冷启动延迟随索引线性增长。

---

## 3. TSNG 实现现状评估

### 3.1 已有基础（可直接复用）

| 能力 | 位置 | 评价 |
|---|---|---|
| 三信号查询契约 | `tsng.rs:19-82` | 完整，含 `graph_depth` 溯源 |
| 7 种 AccessPath 对照 | `tsng.rs:152-161` | **论文级对照实验框架已就位** |
| Ground truth（含图信号） | `tsng.rs:1150-1220` | 可按权重口径重算期望排序 |
| Recall@K / NDCG@K | `tsng.rs:1381-1437` | 标准实现，含 ID 去重 |
| 预算与成本记账 | `tsng.rs:45-61` / `:461-507` | 清晰的字节/页读/候选上界 |
| Matched-recall Gate | `benches/bench_tsng_c1.rs` | 含 Fixed/Selectivity/Density 三方对照 |
| 双队列导航 | `quiver.rs:1328-1497` | 有 `signal_queue_quota_ppm` 配额机制 |
| 导航 scorer 扩展点 | `quiver.rs:46-52` | 干净，仅 2 个方法 |

### 3.2 现状评估要点

**A. 权重语义尚不统一（最需要理论化）**
- 导航期 = **有界抵扣**（`tsng.rs:326-357`）：信号只减少距离，最多减 20%。
- 精排期 = **加权平均**（`tsng.rs:1107-1128`）：信号与向量相似度线性组合。
- 两者不是同一目标函数的近似 → 排序可能不一致。**这是 TSNG 最自然的第一篇方法改进点**：把两阶段统一到同一个（可证明单调的）目标函数，或给出「导航期抵扣 vs 精排期加权」的一致性条件。

**B. 图信号的计算成本未做预算化**
- `exact_graph_signals`（`tsng.rs:1275-1336`）每次查询都做一次**全量 BFS**，并对 `direction = Incoming|Both` 走 `get_incoming_sources` 逐源回查边（`tsng.rs:1366-1376`，最坏 O(Σ indeg)）。
- 该成本**不计入** `TsngSearchMetrics.navigation_scores`，只在 `graph_visited_nodes` / `graph_examined_edges` 单独记账（`tsng.rs:1168-1169`）。
- → 论文中报"图信号带来的收益"时必须显式分离这部分预处理成本，否则会被质疑不公平。

**C. `graph_seed_limit` / `signal_queue_quota_ppm` 只在一条路径生效**
- 仅在 `approximate_search` 内被消费（`tsng.rs:1062-1091`）。
- `graph_union_search`（`:914`）用 `graph_seed_limit` 做**候选截断**，语义与 dual-queue 的"种子注入"不同 → **同名字段两种含义**，实验时极易误配。

**D. 指标字段多为"估算"而非实测**
- `TsngSearchMetrics`（`tsng.rs:124-148`）中 `estimated_temp_bytes` / `estimated_vector_page_reads` / `estimated_payload_page_reads` / `estimated_graph_page_reads` 由 `checked_candidate_metrics`（`:461-507`）**公式推算**，不是实测计数器。
- 有实测计时的是 BQ 预筛四项（`bq_posting_lookup_ns` / `bq_node_mapping_ns` / `bq_heap_scan_ns` / `bq_output_sort_ns`，`:784-791`）。
- → 报 I/O 收益时需明确标注"估算"。

**E. 属性信号是二值的**
- `property_signal ∈ {0, 1}`（`:1112-1119`），无"部分匹配"概念；`MetadataBonus` 因此只能表达"命中即抵扣固定比例"。
- 若要扩展到多属性加权 / 软匹配，需改 `score` 与 `exact_rerank_candidates` 两处。

**F. 无 L 层级理论量**
- 当前完全没有任何 RaBitQ 式的误差界、距离估计方差、或"导航可靠性"度量。这是 Phase-2（RaBitQ 融合）必须新加的模块 —— 从零开始。

**G. API 未冻结但有测试保护**
- `tsng.rs:6` 自述未语义冻结，但同时有 896 行专项测试（`tests/pipeline/tsng_c1.rs`）+ 两个 benchmark。→ **可以放心重构，只要测试同步更新**；反之若想快速出结果，也可以按现状冻结 API 只加新字段。

---

## 4. 研究改造点清单

> 改动半径用 [S]/[M]/[L] 标注：S = 单文件局部；M = 跨 2–3 文件 + 测试；L = 跨模块 + 格式/契约变更。

### T1. 量化码替换（BQ2 → RaBitQ + 误差界）

| 目标位置 | 文件:行号 | 改动内容 | 半径 |
|---|---|---|---|
| 签名结构定义 | `src/index/bq.rs:83-88` | `Bq2Signature { pos, strong }` → RaBitQ 的 `{ code: [u64;48], factor: f32 }`（或独立新类型） | **[L]** `#[repr(C)] + Pod` 参与落盘 |
| 编码函数 | `src/index/bq.rs:107-141` | `from_vector`：加 FHT-Kac 旋转（可复用 `benches/bench_rbq2_precision.rs:36-70` 的 `FhtKacRotator`）+ 1-bit 量化 + 修正因子 | [M] |
| 距离语义（对称） | `src/index/bq.rs:149-188`、`:192-235`（标量）、`:246`（AVX-512）、`:621`（AVX2）、`:727`（NEON） | 由"加权 Hamming"改为"Hamming + 修正项" | **[L]** 4 套 SIMD 内核 |
| 距离语义（非对称 ADC） | 新增 | RaBitQ 核心：`⟨q, x̂⟩ ≈ f(q, code) · ‖q‖/−…`；现有 `NavigationScorer::score(node, bq_distance: u32)` 签名**不够用**（需要 f32 结果或修正因子） | **[L]** 需改 trait |
| 紧凑存储 | `src/index/bq.rs:913-920` `Bq2Store` | 若签名含 f32 因子，SoA 布局需加 `factors: Vec<f32>` | [M] |
| 距离读取接口 | `src/index/bq.rs:1033` `distance_to_sig`、`:1045` `distance_to_sig_cheap`、`:1083` `distance_to_sig_cheap_384` | 全部需重写；`cheap` 概念在 RaBitQ 下语义要重新定义（是否保留"两段估计"） | **[L]** |
| 维度上限 | `src/index/bq.rs:19-20` | `MAX_BQ_CHUNKS = 48` → 若 RaBitQ 用旋转后维度扩张（fbin padding），需重新核算 | [M] |
| 消费方（导航） | `src/index/quiver.rs:1255-1326`（`beam_search_l0_impl`）、`:1499-1564`（384 专用）、`:1567-1624`（upper）、`:1627-1671`（`vamana_select`）、`:578-633`（建图 beam） | 全部换距离函数 | **[L]** |
| 消费方（其它） | `src/index/quiver.rs:1771-1855`（prefilter）、`:1701-1754`（density skew）、`:1328-1497`（dual queue）、`src/storage/memtable.rs:1313-1323`（`rebuild_bq_signatures`）、`src/storage/file_format.rs:3062-3104`（反序列化） | 跟进 | [M] |
| 序列化 | `src/index/quiver.rs:2863-2864`（MAGIC/VERSION）、`:2902-2906`（写签名）、`:3061-3105`（读签名） | 格式变更 → **`QUIVER_VERSION` 必须升到 2**；旧文件按现有 `:3012-3020` 逻辑拒绝（会丢失向后兼容） | **[L]** |
| 测试资产 | `tests/format_mutation/`、`tests/format_spec/`、`src/index/bq.rs:1155-1420`（现有 20+ 位级一致性测试） | 位级一致性测试是**改编码时的回归护栏**，必须同步重写 | [M] |

**已有可直接复用的 RaBitQ 参照实现**：`benches/bench_rbq2_precision.rs:36-70`（`FhtKacRotator`：4 轮随机翻转 + FHT-Kac 旋转，`trunc_dim = 2^floor(log2 dim)`，`fac = 1/sqrt(trunc_dim)`）。这是仓库里唯一现成的旋转实现，应先在 bench 层验证再下沉到 `src/`。

### T2. 图构建算法（引入 PiPNN 分区式）

| 目标位置 | 文件:行号 | 改动内容 | 半径 |
|---|---|---|---|
| **唯一生产建图入口** | `src/index/quiver.rs:2326-2408` `batch_build_from_store` | 插入分区阶段：先聚类/分区 → 分区内建图 → 跨分区桥接 | **[L]** |
| 建图核心（并行） | `src/index/quiver.rs:563-834` `ExperimentalBuildView`：`connect_node_checked` `:635`、`connect_node_fast` `:696`、`final_prune` `:817` | 分区内复用；跨分区需新逻辑 | [L] |
| 邻接表结构 | `src/index/quiver.rs:200-420` `FlatAdj`（单张全局表，`stride = 4m+1` 定长） | 分区化后需 per-partition 结构或分区 id 位段编码 → **影响 stride 语义** | **[L]** |
| 并发原语 | `src/index/quiver.rs:424-561` `ConcurrentFlatAdj`、`:225-281` `StripedSpinLocks` | 分区天然降低跨线程争用，可简化或改分区级锁 | [M] |
| 入口点策略 | `src/index/quiver.rs:1033`（`entry_point` 更新）、`:935-936` 字段 | PiPNN 需多入口（每分区一个代表点）→ `entry_point: u32` 要变 `Vec<u32>` | **[L]** |
| 增量插入 | `src/index/quiver.rs:1033-1211` `insert` | 从"全局双向量重剪"改为"定位分区 + 分区内插入"，这是 PiPNN 的最大收益点 | [L] |
| MemTable 接线 | `src/storage/memtable.rs:1405-1433` `quiver_build_snapshot`、`:1435-1444` `build_quiver_snapshot`、`:1463-1509` `build_quiver_impl`、`:1236-1260` `quiver_build_peak_bytes` | 分区元数据需进 snapshot；峰值估算要重算 | [M] |
| 调度 | `src/database/pipeline.rs:137-186` | 分区构建可拆成多轮发布（流式可见），也是论文卖点 | [M] |
| 序列化 | `src/index/quiver.rs:2879-2966` / `:2975-3302` | 需新增分区表段 | [L] |
| 消融开关 | `src/index/quiver.rs:2379`、`:2483`（`TRIVIUM_EAGER_PRUNE`） | 新增「分区 vs 全局」A/B 开关，沿用同一模式 | [S] |
| 已有层次结构 | `src/index/quiver.rs:927-928` `upper_layers` / `node_max_layer`、`:1025-1031` `random_level` | ⚠️ **当前是 HNSW 式层次 + Vamana 剪枝**（非论文所述纯 Vamana 单层）。做 PiPNN 对比时**必须澄清基线到底是哪一层**，否则「vs Vamana」的比较不成立 | — 认知风险 |

**关键认知**：现有实现是 **HNSW 层次 + Vamana RobustPrune + 惰性剪枝**的混合体。任何与 PiPNN、DiskANN/Vamana 的对比，都需先通过消融（`upper_layers` 置空 vs 保留）确认基线语义。

### T3. 导航打分函数（TSNG 融合 + RaBitQ 误差利用）

| 目标位置 | 文件:行号 | 改动内容 | 半径 |
|---|---|---|---|
| **核心融合公式** | `src/tsng.rs:326-357` `TsngNavigationScorer::score` | 三路融合 + 若引入 RaBitQ 则需接入误差界/置信度 | [M] |
| 权重建模 | `src/tsng.rs:294-315` `new`（`fixed()` 归一化）、`:254` `NAVIGATION_SCALE` | 整数量化到 1e6，若引入 f32 置信度需换数值域 | [M] |
| Scorer trait | `src/index/quiver.rs:46-52` `NavigationScorer` | `score(node, bq_distance: u32) -> u32` —— RaBitQ ADC 需要 f32，**签名要改**；`accept_result` 可保留 | [M] |
| 双队列 | `src/index/quiver.rs:1328-1497` `beam_search_l0_dual` | 配额机制保留，信号来源换成"误差上界驱动的探索" | [M] |
| 精排融合 | `src/tsng.rs:1101-1148` `exact_rerank_candidates` | 与导航公式统一（§3.2-A） | [S] |
| 工业路径成本模型 | `src/tsng.rs:509-795` `industrial_search`（成本估算 `:556-602`、自适应 ef `:620-651`） | 若导航变贵，成本模型需重标定 | [M] |
| 图信号成本 | `src/tsng.rs:1275-1336` `exact_graph_signals`、`:1338-1379` `exact_graph_neighbors` | 预算化 / 采样化，并计入 metrics | [M] |
| 指标扩展 | `src/tsng.rs:124-148` `TsngSearchMetrics` | 新增"导航可靠性"类指标（估计误差、剪枝率） | [S] |
| 调用方 | `src/database/mod.rs:1848-1895`、`src/database/facade.rs:73-100`、`benches/bench_tsng_c0.rs`、`benches/bench_tsng_c1.rs:256-261/344-346`、`tests/pipeline/tsng_c1.rs:334-511` | 公开 API 变更的联动面 | [M] |

### T4. 阈值 / 路由（研究期需可强制指定）

| 目标位置 | 文件:行号 | 改动内容 | 半径 |
|---|---|---|---|
| 阈值常量与函数 | `src/storage/memtable.rs:21-30` | 消融需固定 `n` 与 `dim` 组合 → 提供环境变量覆盖 | [S] |
| 硬编码 10000 | `src/storage/memtable.rs:1296-1302` | 统一到 `auto_quiver_node_threshold(dim)`（消除双判据） | [S] |
| 算子选择 | `src/query/cascades.rs:1304-1353`（`:1310` 判据、`:1330-1340` 成本模型） | 成本模型是 `rows.log2()*dim`（近似）vs `node_count*dim`（精确）→ 新索引的成本模型需重标定，否则 planner 可能选错算子 | [M] |
| 查询路由 | `src/database/pipeline.rs:288-300`、`:555-575` | 新增引擎需在此登记 `vector_route_*` observation | [S] |
| 算子实现 | `src/query/pipeline.rs:607-668` `QuiverVectorSearch` | 新建 `RaBitQVectorSearch` / `PipnnQuiverVectorSearch` 算子 | [M] |
| ROM/immutable 策略 | `src/database/config.rs`（`MissingIndexPolicy`） | 新索引的 sidecar 缺失语义 | [S] |

### T5. 持久化格式

| 目标位置 | 文件:行号 | 改动内容 | 半径 |
|---|---|---|---|
| `.quiver` 写 | `src/index/quiver.rs:2879-2966` | 新段：分区表 / 因子数组 | [L] |
| `.quiver` 读 | `src/index/quiver.rs:2975-3302` | 同步 + 版本分支 | [L] |
| 版本常量 | `src/index/quiver.rs:2863-2864` | `QUIVER_VERSION: u32 = 1` → 2（**当前逻辑对非 1 版本直接拒绝**，无迁移路径） | [S] |
| `.quiver.meta` | `src/storage/file_format.rs:281-339`（写/校验）、`:401-423`（落盘）、`:1556-1614`（加载） | 若 quiver 尺寸/CRC 语义不变则免改；新增 sidecar 需复制此模式 | [S] |
| 内存统计 | `src/index/quiver.rs:2739-2764` `stats()`、`src/storage/memtable.rs:2150-2155/2650-2662` | 新结构需计入 `IndexMemoryStats` | [S] |

### T6. 评测扩展（无需改 src/）

| 目标 | 新增/复用 |
|---|---|
| RaBitQ 编码对拍 | 复用 `benches/bench_rbq2_precision.rs`，扩展为含 ADC + 误差界 |
| 分区构建消融 | 复用 `benches/bench_quiver_ablation.rs` 模式 + `TRIVIUM_EAGER_PRUNE` 同款环境变量开关 |
| 增量吞吐 | 复用 `bench_cohere1m.rs:355-369` 的 `TRIVIUM_ANN_INCREMENTAL` 框架 |
| 冷/热 I/O | 复用 `benches/bench_ssd_cold_hot.rs`（需 admin 权限）；注意 §5-R2 的非零拷贝问题会影响口径 |
| 竞品补齐 | `benches/bench_baselines.py` 需新增 **Milvus QG / Filtered-DiskANN / ACORN**（当前只有 hnswlib / FAISS / USearch / VSAG） |

---

## 5. 风险与未知项

### 5.1 已确认的代码级问题（改造前必须处理或规避）

| # | 问题 | 位置 | 影响 | 建议 |
|---|---|---|---|---|
| **R1** | **自动建图双阈值**：`auto_quiver_build_needed()` 用 `auto_quiver_node_threshold(dim)`，`ensure_vectors_cache` 用硬编码 `10_000` | `memtable.rs:26-30` vs `:1296-1302` | dim ∈ (800, 3072] 时两者不一致（如 dim=1536 → 5209 vs 10000）。生产走前者、测试多走后者 → **消融实验可能在非预期规模触发建图** | 统一到 `threshold(dim)`；实验期加环境变量固定 |
| **R2** | **`.quiver` 加载非零拷贝**：`load_from_file` 建 mmap，但 `load_from_bytes` 把所有数组 `collect()` 成新 `Vec` | `quiver.rs:2969-2973` vs `:3092/3126/3153/3169/3185/3233` | 冷启动后进程堆 + PageCache 双份占用；与「mmap 混合引擎」的宣传口径不符；影响 SSD 冷/热实验的"冷"定义 | 改造为 borrow 式视图（`&[u64]` 直接指向 mmap）或明确记录为已知行为 |
| **R3** | **每次打开数据库全量 CRC32 扫 `.quiver`** | `file_format.rs:294`（写）+ `:322`（校验） | 数百 MB 索引 → 冷启动线性延迟；benchmark 反复 open 时污染测量 | 研究期考虑 `mmap` 惰性校验或分块校验 |
| **R4** | **增量插入与批量构建不对称**：`insert` 每条反向边全量 `vamana_select`（O(m0³·C)），批量路径已改惰性 | `quiver.rs:1141-1167`（insert）vs `:755-805`（惰性） | 大规模增量写入明显慢；`update_vector` 走 `soft_delete + insert` 双计费 | PiPNN 分区化的直接靶点；短期可先给 `insert` 落同样的惰性剪枝 |
| **R5** | **墓碑不修拓扑**：`soft_delete` 只标记，节点永久当中转 | `quiver.rs:2821-2835` | 长周期删改后图质量退化；25% 阈值是经验值（`bench_cohere1m` 的增量实验佐证） | 明确这是设计取舍；若做 RaBitQ 需重新标定该阈值 |
| **R6** | **`vamana_select` 会补足候选**（选不满 `max_k` 时按距离序补齐） | `quiver.rs:1656-1668` | 与原始 Vamana（不补足、保留 α-diversity 语义）不同 → **「vs Vamana」的对比基线不纯** | 论文对比前先用消融确认影响，或加开关 |
| **R7** | **层次结构是 HNSW 式，非纯 Vamana** | `quiver.rs:927-928`、`:1025-1031` | 与 DiskANN/Vamana 单层语义不同；PiPNN 也是单层分区 → **基线语义必须先钉死** | 加「单层 vs 多层」消融 |
| **R8** | **AVX-512 内核被 `#[cfg(not(coverage))]` 排除** | `bq.rs:155`、`:244` 等 | 覆盖率门禁不覆盖最快路径 → 换编码时这些分支**无 CI 保护** | 改编码时同步补非 SIMD 等价性测试（现有 `bq.rs:1201-1362` 已是此模式） |
| **R9** | **`save_to_file` 注释与实际尺寸不符**（"n × 128B" 实际为 `16·ceil(dim/64)`） | `quiver.rs:2871` vs 实际 | 文档误导，易算错容量规划 | 顺手修正 |
| **R10** | `Cargo.toml:26` `exclude = ["docs/TEMP-todo/**"]` 与实际目录 `TEMP-TODO` 大小写不符 | `Cargo.toml` | 打包时可能未排除（Windows 不敏感、Linux 敏感） | 顺手修正 |

### 5.2 研究层面的未知项

| # | 未知项 | 为什么重要 | 怎么解 |
|---|---|---|---|
| **U1** | **论文基线本身可复现吗？** | 要发后续工作，必须先能复现 QuIVer 的 Table 4/5 | 见 §8 L1：跑 `bench_cohere1m` 对齐 README_QUIVER.md 报告的数字 |
| **U2** | RaBitQ 的**旋转**是否破坏 QuIVer 的"训练无关 + 免索引旋转"卖点？ | QuIVer 的核心叙事是 training-free 无旋转；引入 FHT 旋转后需论证「仍无需数据依赖训练」 | 理论 + 消融：旋转只依赖 `dim` 与随机种子（`bench_rbq2_precision.rs:47` 已如此实现）→ 可作为论证基础 |
| **U3** | RaBitQ 的 **ADC 需要 f32 查询侧修正**，而 `NavigationScorer::score` 只接受 `u32 bq_distance` | 接口不兼容会阻塞融合 | 先扩 trait（加 f32 通道），或并行加一个新的 `AdcScorer` trait |
| **U4** | PiPNN 的**分区质量**依赖什么？在无标签场景如何分区？ | 决定 PiPNN 能否搬到通用向量库 | 需文献调研 + 在 Cohere-1M 上先做「随机分区 vs KMeans 分区 vs 图分区」预实验 |
| **U5** | 三模态信号与向量误差界的**联合理论**（TSNG × RaBitQ） | 这是论文的核心贡献点，目前**完全空白** | 需先建立"导航期距离估计 + 属性/图抵扣"的联合上界 |
| **U6** | 竞品 Milvus QG / Filtered-DiskANN / ACORN 无现成脚本 | 审稿必问 | 需写 Python 基线脚本（工作量中等） |
| **U7** | `docs/TEMP-TODO/triviumdb-roadmap.md` 是否已有与本研究冲突的路线？ | 避免与上游规划撞车 | **待读**（本次未展开） |
| **U8** | 现有的 `bench_rbq2_precision`（100K×768）只比 top-K 精度，不比 QPS/内存 | 无法直接支撑"RaBitQ 替代 BQ2"的性能论证 | L1 阶段扩展到 QPS + 内存 + 端到端 Recall |

---

## 6. 与上游（YoKONCy/TriviumDB）的分叉差异

### 6.1 结论：**核心源码零分叉**

```powershell
git diff --stat upstream/dev...HEAD          # 仅 WebUI 相关
git diff --stat upstream/dev...HEAD -- src/ benches/ Cargo.toml
# → 空（src/、benches/、Cargo.toml 与上游逐字节一致）
```

在 `feature/webui-test-infra`（`686890f`）上，相对 `upstream/dev`（`043c328`）的差异总计 **16 文件 / +11754 行**，全部是 WebUI 交付物，**不含 `src/`、`benches/`、`scripts/`（除 UI 脚本）**：

| 文件 | 变化 | 类别 |
|---|---|---|
| `crates/triviumdb-server/web/index.html` | +10487 | Web Console 单文件前端（`include_str!` 内嵌） |
| `crates/triviumdb-server/src/lib.rs` | +16 | `/`、`/ui`、`/ui/` 路由 + no-cache 头 |
| `crates/triviumdb-server/tests/http_contract.rs` | +17 | 路由契约测试 |
| `.github/workflows/webui.yml` | +111 | WebUI CI（冒烟 + 视觉回归） |
| `scripts/ui-smoke.mjs` / `scripts/visual-baseline.mjs` | +632 / +389 | 测试脚本 |
| `tests/visual/baseline/win32/*.png` | 7 张 | 视觉基线 |
| `docs/server.md` / `docs/webui-api-gaps.md` / `docs/webui-testing.md` | +1 / +42 / +59 | 文档 |

### 6.2 对本研究的意义

- ✅ **研究基线完全干净**：`src/` 与上游一致 → 任何 `src/` 改动都是纯研究改动，diff 可读性极高，未来开 PR 到上游无冲突。
- ✅ **不存在"上游已修但 fork 未同步"的隐患**（本报告的 R1–R10 都是上游问题，需一并反馈）。
- ⚠️ `upstream/dev`（`043c328`）与 `upstream/master`（`f4bdfe3`）**源码树完全相同**（`git diff --stat upstream/dev upstream/master` 为空；master = dev 的 merge commit）。因此研究分支选 `043c328` 即是当前上游最新源码。
- 📌 **上游未跟踪文件**（工作区可见、非仓库内容）：`.claude/`、`.codebuddy/`、`AGENTS.md`、`CLAUDE.md`、`audit-home.yaml`、`home2` —— 其中 `AGENTS.md` / `CLAUDE.md` / `.claude/` 由 GitNexus 索引工具注入，与本研究无关，**不要提交**。

### 6.3 建议反馈上游的缺陷清单

R1（双阈值）、R2（非零拷贝加载）、R3（全量 CRC 冷启动）、R4（增量剪枝不对称）、R6（`vamana_select` 补足）、R9（注释尺寸错误）、R10（`TEMP-todo` 大小写）—— 这些是**独立于本研究的工程质量问题**，适合先单独提 issue/PR 到上游，与研究分支解耦。

---

## 7. Git 状态与研究分支

### 7.1 摸底时的状态（会话开始时）

```
On branch feature/webui-test-infra        # = fork 的 PR-C 分支
up to date with 'origin/feature/webui-test-infra'
Untracked: .claude/  .codebuddy/  AGENTS.md  CLAUDE.md  audit-home.yaml  home2
```

- 远端：`origin` = `https://github.com/QWQcool/TriviumDB`（fork，用户账号）；`upstream` = `https://github.com/YoKONCy/TriviumDB.git`
- fork 上存在 **20+ 个 `feature/webui-*` 分支**（WebUI 流水线产物，全部待用户开 PR），与研究无关
- 工作区**无已跟踪文件改动** → 切分支安全（已执行的切换未触碰任何文件内容）

### 7.2 已创建的研究分支

```
research/quiver2-pipnn-rabitq-tsng    @ 043c328  (= upstream/dev 源码树)
```

**创建理由**：

1. **基线必须干净且可追溯**。研究结论要经得起"在哪个基线上测的"追问，`043c328` 是 `upstream/dev` 的精确 tip（也与 `upstream/master` 源码树一致），是唯一无歧义的起点。
2. **不要把研究改动堆在 `feature/webui-test-infra` 上**。那是 fork 的 PR-C 分支，含 +10487 行的 `index.html`。若在其上做研究提交，将来 `git diff` / PR review 会被 WebUI 噪音淹没，且研究 PR 与 WebUI PR 无法独立合并。
3. **从 `upstream/dev` 而非 fork 的 webui 分支切出**，可让研究分支相对上游的 diff **只包含 `src/` + `benches/` + 研究文档**，未来向 `YoKONCy/dev` 提交学术性 PR 时是最小化、可审查的改动集。
4. **不与 WebUI 工作竞争**：两个分支树互不干扰，WebUI 可以继续 push，研究独立推进。
5. **分支名自述研究内容**（quiver2 / pipnn / rabitq / tsng 四要素），符合仓库既有的 `feature/webui-*` 命名习惯，便于长期并存多个研究线（如将来 `research/quiver2-eval-only`）。

**回退方式**：`git switch feature/webui-test-infra`（或 `git switch -`）。

### 7.3 建议的分支/提交策略

| 项 | 建议 |
|---|---|
| 主研究分支 | `research/quiver2-pipnn-rabitq-tsng`（当前） |
| 评测/基线专属分支 | `research/quiver2-baseline-eval` —— 只含 dataset 准备脚本 + 结果 JSON + 复现说明，**不含 `src/` 改动**，便于论文 artifact 打包 |
| 工程缺陷分支 | `fix/quiver-engine-hardening` —— R1/R2/R3/R4/R9/R10 单独提上游 issue/PR，与研究解耦 |
| 提交粒度 | 每个改造点（T1–T5）至少一个提交，且**必须先通过 L1 基线再动 `src/`**（否则 recall 变化无法归因） |
| 兼容旧分支 | 研究分支不要 rebase 到 fork 的 webui 分支；只从 `upstream/dev` 拉取 |
| 提交前检查 | 沿用仓库既有规范：`cargo test --lib --tests -- --test-threads=1`、`cargo llvm-cov report --fail-under-lines 80`、`cargo fmt --check`、`git diff --check` |

---

## 8. 下一阶段（基线复现 L1）行动清单

### 8.0 目标

在**不修改任何 `src/` 代码**的前提下，得到一份可复现、可对拍的 QuIVer 基线数字，作为后续所有改造的 anchor。

### 8.1 前置：环境与数据（L1-A，0.5–1 天）

| 步骤 | 命令 | 验收标准 |
|---|---|---|
| A1. 工具链与编译配置对齐论文 | `rustup update stable`；`$env:RUSTFLAGS="-C target-cpu=native"` | `cargo --version`、`RUSTFLAGS` 生效；release profile 已有 `lto=true, codegen-units=1`（`Cargo.toml:[profile.release]`） |
| A2. Smoke test（无外部数据） | `cargo test --lib "index::quiver::tests::test_quiver_中等规模搜索" -- --exact` | `1 passed; 0 failed`（README_QUIVER.md Quick Start 口径） |
| A3. 硬件指纹记录 | 记录 CPU 型号 / AVX-512-VPOPCNTDQ 支持 / 核数 / RAM / 磁盘型号 | 写入 `docs/research/l1-baseline.md`；**论文 §5.1 用的是 AMD Ryzen 7 7840HS（Zen4, AVX-512 VPOPCNTDQ）**，若机器不同则所有绝对 QPS 数字都需标注不可直接对比 |
| A4. Python 依赖 | `python -m pip install numpy tqdm h5py datasets huggingface-hub hnswlib faiss-cpu usearch pyvsag` | `python -c "import hnswlib, faiss"` 成功；**记录哪些竞品装上了**（`pyvsag` 常失败） |
| A5. 主数据集（Cohere-1M 768d） | `python scripts/prepare_all.py cohere` | 生成 `cohere_train.f32`（1M×768）、`cohere_test.f32`、`cohere_groundtruth.i32`；校验文件尺寸 = N×D×4 |
| A6. Ground truth 自校验 | 抽样 100 条 query 用 `brute_force_topk` 重算 top-10，与 `_groundtruth.i32` 比对 | **100% 一致**（不一致则 GT 生成有 bug，后续所有 recall 都不可信） |

### 8.2 基线复现（L1-B，1–2 天）

| 步骤 | 命令 / 位置 | 验收标准 |
|---|---|---|
| B1. 主结果（§5.2 Table 4） | `cargo bench --bench bench_cohere1m`（默认 cohere-1m, m=32, ef_c=128, α=1.2） | 产出 `ef / rerank / Recall@10 / MT-QPS / lat / vs BF` 表；与 README_QUIVER.md 报告的趋势一致（**不要求绝对数字一致，硬件不同**） |
| B2. 结果落 JSON | 加 `TRIVIUM_RESULT_PATH=results/l1/cohere1m.json` | JSON 含 build 时间、exact QPS、每个 ef 的 recall/qps/latency |
| B3. ef 扫描覆盖 | `TRIVIUM_ANN_EF="64,128,256,512,1024"` | 得到 Recall-QPS 曲线；**曲线形状**（而非单点）才是后续改造的比较对象 |
| B4. 参数敏感性（§5.4） | `TRIVIUM_SENSITIVITY_MODE=all cargo bench --bench bench_sensitivity` | 1a–1f 六组子实验完成；记录 m / ef_c / α 的最优点 |
| B5. 编码消融（§5.5） | `cargo bench --features ablation --bench bench_encoding_ablation` | 1-bit sign vs 2-bit SM vs 2-bit SQ 的 top-10 overlap + ns/call + Recall@10/QPS —— **这是 T1（RaBitQ 替换）的直接对照组** |
| B6. BQ2 vs RaBitQ 精度（§附录） | `cargo bench --bench bench_rbq2_precision` | 三方案（BQ2 / RaBitQ-sym / RaBitQ-asym）top-K overlap；**这是 T1 的起点数字** |
| B7. 增量衰减（25% 阈值佐证） | `TRIVIUM_ANN_INCREMENTAL=100` vs `=80` vs `=50` | 得到"增量图 vs 全量重建图"的 recall 差值曲线，验证 25% 重建阈值 |
| B8. 构建方差与尾延迟 | `cargo bench --features ablation --bench bench_variance` | 5 次独立构建的 recall RSD、P50/P95/P99；**方差是论文必须报的诚实指标** |
| B9. 规模扩展（§5.7，可选/较慢） | `TRIVIUM_ANN_NAME=msmarco-1m` → `msmarco-5m`（需先 `python scripts/prepare_msmarco.py --sizes 1000000 5000000`） | 1M/5M 构建时间与召回；**5M 需 64GB RAM 级机器** |
| B10. 竞品基线 | `python benches/bench_baselines.py`（`BASELINES` 选择性跑）；`python benches/bench_rabitq_refine.py` | hnswlib / FAISS-HNSW / USearch / VSAG / FAISS-IVF+RaBitQ 的 matched-recall QPS |

### 8.3 改造前的护栏（L1-C，0.5 天）

| 步骤 | 内容 | 目的 |
|---|---|---|
| C1. 冻结基线数字 | 把 B1–B10 的结果 JSON + 环境指纹写入 `docs/research/l1-baseline.md` | 后续每次 `src/` 改动都与此表对拍 |
| C2. 建立"研究专用"benchmark 骨架 | 新 bench 命名 `bench_quiver2_*`，按 `benches/README.md:77-85` 的 7 条要求写文件头（被测能力/分布/oracle/计时边界/非目标） | 保证研究代码不进默认路径 |
| C3. 环境变量开关预留 | 按 `TRIVIUM_EAGER_PRUNE` / `TRIVIUM_BUILD_PROFILE` 既有模式，为「分区 vs 全局」「RaBitQ vs BQ2」预留开关 | 一处开关 = 一个消融图 |
| C4. 覆盖率基线确认 | `cargo llvm-cov report --fail-under-lines 80` 本地通过 | 改造后不能跌破 80%（`ci.yml:405`） |
| C5. 缺陷反馈（可选，建议做） | 把 R1/R2/R3/R4/R9/R10 独立成上游 issue | 与本研究解耦，避免研究分支被迫夹带工程修复 |

### 8.4 L1 完成判据（Definition of Done）

- [ ] `docs/research/l1-baseline.md` 包含：环境指纹 + 主结果表（≥5 个 ef 点）+ 敏感性最优参数 + 编码消融三方对比 + BQ2/RaBitQ 精度对比 + 增量衰减曲线 + 竞品 matched-recall 表
- [ ] 所有结果有对应 JSON 产物，可被第三方脚本重算
- [ ] GT 自校验 100% 通过
- [ ] `cargo test --lib --tests -- --test-threads=1` 全绿、覆盖率 ≥ 80%
- [ ] **`git diff upstream/dev -- src/` 为空**（证明本阶段零源码改动）

### 8.5 L1 之后的路线（供决策，不在本阶段执行）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **L2-a** | RaBitQ 编码替换（T1），先只做 1-bit + 旋转 + 对称距离，验证 Recall 不劣化 | L1 完成（B5/B6 作对照） |
| **L2-b** | RaBitQ ADC + 误差界接入导航（需扩 `NavigationScorer`，T3 前置） | L2-a |
| **L3-a** | PiPNN 分区构建（T2）——先做"随机分区基线"，再做 KMeans/图分区 | L1 完成 + U4 预实验 |
| **L3-b** | 增量插入分区化（T2 的 `insert` 改造，直击 R4） | L3-a |
| **L4** | TSNG 融合理论化：统一导航期/精排期目标函数 + 误差界联合上界（U5） | L2-b + L3-a |
| **L5** | 补齐竞品（Milvus QG / Filtered-DiskANN / ACORN） | L1 完成 |
| **L6** | 论文 artifact 打包（`research/quiver2-baseline-eval` 分支） | 全部 |

---

## 附录 A：关键行号速查

| 主题 | 位置 |
|---|---|
| `MAX_BQ_DIM = 3072` | `src/index/bq.rs:19-20` |
| `Bq2Signature::from_vector` | `src/index/bq.rs:107-141` |
| 2-bit 加权 Hamming（标量） | `src/index/bq.rs:192-235` |
| SIMD 派发 | `src/index/bq.rs:149-188`；AVX-512 `:246`；AVX2 `:621`；NEON `:727` |
| `Bq2Store` | `src/index/bq.rs:913-920`；`distance_to_sig` `:1033`；`_cheap` `:1045`；`_cheap_384` `:1083` |
| `QuIVer` 结构 | `src/index/quiver.rs:915-947` |
| `FlatAdj`（单张全局邻接表） | `src/index/quiver.rs:200-420` |
| `vamana_select` | `src/index/quiver.rs:1627-1671` |
| 惰性剪枝 | `src/index/quiver.rs:755-805` |
| **生产建图** `batch_build_from_store` | `src/index/quiver.rs:2326-2408` |
| 单节点增量 `insert` | `src/index/quiver.rs:1033-1211` |
| 查询 `search_with_scorer` | `src/index/quiver.rs:1941-2060` |
| 双队列 `beam_search_l0_dual` | `src/index/quiver.rs:1328-1497` |
| `soft_delete` / `needs_rebuild` | `src/index/quiver.rs:2821-2835` / `:2839-2841` |
| `.quiver` 写 / 读 | `src/index/quiver.rs:2879-2966` / `:2975-3302` |
| `NavigationScorer` trait | `src/index/quiver.rs:46-52` |
| 阈值常量与函数 | `src/storage/memtable.rs:21-30` |
| 硬编码 10000 | `src/storage/memtable.rs:1296-1302` |
| 建图调度 | `src/database/pipeline.rs:137-186` |
| 查询路由 | `src/database/pipeline.rs:288-300`、`:555-575` |
| 算子选择 + 成本模型 | `src/query/cascades.rs:1304-1353` |
| `QuiverVectorSearch` 算子 | `src/query/pipeline.rs:607-668` |
| TSNG 导航打分 | `src/tsng.rs:284-358`（核心 `:326-357`） |
| TSNG 精排融合 | `src/tsng.rs:1101-1148` |
| TSNG 配置 | `src/tsng.rs:100-121` |
| TSNG 7 种 AccessPath | `src/tsng.rs:152-161`；选择逻辑 `:509-795` |
| TSNG 图信号 BFS | `src/tsng.rs:1275-1336` |
| TSNG quality metrics | `src/tsng.rs:1381-1437` |
| `.quiver.meta` | `src/storage/file_format.rs:281-339`、`:401-423`、`:1556-1614` |
| CI 覆盖率门禁 80% | `.github/workflows/ci.yml:375-414`（`:405`） |
| RaBitQ 旋转参照实现 | `benches/bench_rbq2_precision.rs:36-70` |

## 附录 B：本次会话的只读性声明

- 未修改 `src/`、`benches/`、`scripts/`、`tests/`、`Cargo.toml` 中任何内容。
- 唯一新增文件：本报告 `docs/research/bootstrap-report.md`。
- 唯一 git 状态变更：从 `feature/webui-test-infra` 创建并切换到 `research/quiver2-pipnn-rabitq-tsng`（基点 `043c328`，工作区文件内容未变）。

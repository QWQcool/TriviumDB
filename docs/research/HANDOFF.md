# 交接文档 —— QuIVer 后继研究（会话交接）

> **分支**：`research/quiver2-pipnn-rabitq-tsng`（基点 `upstream/dev @ 043c328`）
> **提交**：`3637954` → `d66142f` → `b0b85a4` → `f132334` → `4c28ffe`
> **源码状态**：**`src/` 零改动**（全部工作 = 新 bench + Python 脚本 + 研究文档）
> **日期**：2026-09-17

---

## 0. 一句话状态

原定三腿（PiPNN + RaBitQ + TSNG）**全部测完，全部未成立**；
但竞品基线**首次复现了仓库自己的核心宣称（高维上快 HNSW 4–5×）**，
并暴露出一个**可用可分性预测的精度-维数边界** —— **论文形状已从"融合三个技术"改为"BQ2 的维度适用边界"**。

---

## 1. 环境与口径（必须延续）

| 项 | 值 |
|---|---|
| 机器 | i9-14900K / 24C32T / 63.7 GB / Win11 Pro |
| **AVX-512** | **不可用**（实测 `Avx512F=False`）⇒ 绝对 QPS 不可与论文（Zen4+AVX512）对比 |
| 编译 | `RUSTFLAGS="-C target-cpu=native"` |
| Python | 项目内 `.venv`（numpy 2.5.3 / h5py / datasets / hnswlib 0.8.0 / faiss-cpu 1.15.0 / usearch 2.26.2） |
| 控制台 | PowerShell 是 GBK ⇒ **Python 脚本开头必须 `sys.stdout.reconfigure(encoding="utf-8")`**，命令前加 `[Console]::OutputEncoding=[System.Text.Encoding]::UTF8` |

### 数据集

| 名称 | 规模 | 协议 | 文件前缀 | GT |
|---|---|---|---|---|
| cohere | 1M × 768 | **原始数据未归一化**（benches 内部归一化） | `cohere` | 官方，K=1000 取前 10 |
| sift128 | 1M × 128 | `prepare_all.py` 做过 **L2 归一化 + cosine 重算 GT**（**非标准 SIFT-L2 协议**，不可与公开数字对比） | `sift128` | 重算，K=10（已独立校验 500/500=100%） |

`prepare_all.py` 还支持 `gist960 / glove100 / minilm / bge_m3 / dbpedia1536 / dbpedia3072 / wolt_clip`（未下载）。

---

## 2. 五条已裁定的结论

### T1 — RaBitQ 误差界剪枝：**整族关闭**（`t1-v1-pruning-tradeoff.md`）
| # | 原因 | 证据 |
|---|---|---|
| R1 | 候选剪枝能力**不可迁移** | 10 万原始候选上 72% → 图遍历 ef 候选集上 **0.0–0.6%** |
| R2 | **成本倒挂** | 5-bit 估计量 **435 ns** > 它要省的 f32 精排 **313 ns**（慢 39%） |
| R3 | **展开剪枝结构性失效** | 判据需 `ε < θ − est_u`，而实测 **`θ − est_u < 0`（−0.019~−0.049）** ⇒ **即使 ε=0（无限精度码）也无法触发** |

R3 最强：失效源于堆序遍历结构（`frontier.pop()` 必然是 est 最大的未展开节点，按构造即 Top-k 候选者），**与量化精度正交**。

### T2 — PiPNN 分区式构建：**被平凡解击败**（`t2-b2-result.md`、`t2-pipnn-recon.md`、`t2-sift-crosscheck.md`）
- **C1 靶点**：批量建图 **81.35%**（cohere）/ **81.65%**（SIFT）花在**全局束搜索**；反向剪枝仅 5.5%，**锁争用 0.03%**
- **C2 并行已耗尽**：CPU/墙钟 = **26.1×/32 线程（84%）** ⇒ 完美并行上限仅 1.16–1.22×
- **B2-0 裁定（cohere，4 次运行 ±0.04pp）**：

| ef_c | 建图 | R@10@ef_s=128 |
|---|---|---|
| 128（基线） | 1.00× | 97.52–97.56% |
| **64** | **0.63–0.66×** | **97.19–97.24%** ⇒ 稳定达标 |
| 32 | 0.55–0.57× | 96.34–96.63% ⇒ **骑在门槛上** |
| 16 | 0.46× | 92.12–92.55% ⇒ 地板 |

⇒ **固定成本地板 0.46×，PiPNN 可争夺空间仅 1.39×，而其池扫描约 2.4× 更贵** ⇒ **零代码的平凡解（ef_c=64，1.55× 加速）已占据全部价值**
- **B1**（全量 64M 边的可达率上界）：cohere k=16/J=3 → **91.4%**；SIFT → **82.4%**；**SIFT k=64/J=3 跌到 49.6%（跌破 70% 门槛）**
- **跨分区边率：SIFT 全面高于 cohere**（k=16: 51.6% vs 32.4%）⇒ 低维反而更不可行

### TSNG — 三信号导航：**从未胜出**（`tsng-c1-baseline-result.md`）
`bench_tsng_c1` **此前从未运行**。matched-recall（target=0.80）下六条路径：

| 场景 | 最快方法 | P95 ms | **TSNG 慢** | Gate |
|---|---|---|---|---|
| vector_property | bq_prefilter | 0.0963 | **42.2×** | passed* |
| vector_graph | industrial_density | 0.1829 | **3.1×** | **FAILED** |
| three_signal | industrial_fixed | 1.1606 | **1.4×** | **FAILED** |

\*唯一通过者 `page_read_reduction=0.0` 且 `candidate_reduction=0.0`（**两项工作量指标全零**）；其 `density_p95_speedup=1.13` 是相对 `selectivity` 算的，与 `fixed` 比**慢 5.8×**。
**2/3 场景 Gate 失败**，理由统一为"密度感知模式未降低 P95、向量页读取或候选精排工作量"。
⚠️ **外部效度限制：数据是合成的**（100K 节点 / 64 维 / 32 簇 / 固定 seed）⇒ 只能判定"当前实现无正向结果"。

### 竞品基线 — ★ **第一个正向结论**（`baseline-competitors.md`）
口径：L2 归一化 cosine、M=32、ef_c=128、**32 线程**、同机同 GT。自检 `faiss_exact` cohere **100.00%** / SIFT **99.94%**。

**cohere-768：仓库"4–5×"宣称成立**
| 方法 | R@10 | MT-QPS | 建图 s |
|---|---|---|---|
| **QuIVer** ef_s=128 | **97.52%** | **31,276** | **35.5** |
| hnswlib ef=128 | 98.16% | 4,735 | 187.1 |
| FAISS HNSW ef=128 | 98.15% | 5,039 | 186.8 |
| USearch ef=128 | 98.21% | 5,748 | 191.5 |
| IVF-Flat nprobe=128 | 97.51% | 434 | 102.6 |

⇒ 在 97.52% 处对齐：**hnswlib 5.0× / FAISS HNSW 4.6× / USearch 4.1× / IVF 72×**；建图快 **5.3×**

**SIFT-128：严格被支配**
QuIVer 天花板 **47.21%**（ef_s=1024, 18,247 QPS）vs **hnswlib ef=64 → 97.46% @ 45,118 QPS**。
三个 HNSW 的最低召回都 ≥96.9%，**从不进入 QuIVer 能达到的区间** ⇒ 曲线无交点。

**机制**：可分性 `(GT1−GT10)/cos_std`：cohere **0.796σ** / SIFT **0.129σ**（需求 6×）；
签名长度 **1536 bit** / **256 bit**（供给 6×）。f32 精排救不了 ⇒ 问题在**候选获取**阶段。

### α 默认值 — **1.2 是平台期最差点**（`alpha-default-reeval.md`）
| 数据集 | α=1.0 vs 1.2 @ef_s=128 | @ef_s=1024 | 建图代价 |
|---|---|---|---|
| cohere | 98.58% vs 97.56% ⇒ **+1.02pp** | +0.20pp | +14% |
| SIFT | 26.84% vs 21.82% ⇒ **+5.02pp** | **+8.64pp** | +22% |

**α ≥ 1.05 后完全平台化**；最优 **α ≈ 0.95–1.0**（1.0 是收益/代价拐点）。
机制：`vamana_select` 的**补足路径**（`quiver.rs:1656-1668`）——α 越小越频繁触发"选不满按距离补齐"，图边长更短但建图更慢。**这也是本仓库与 Vamana 原论文（推荐 1.2）不符的原因**。

### 附带的方法论发现（`t2-b2-result.md` §3）
**并发建图的边集不可逐位复现**（3 次运行 × 2 次重复，L0 指纹全不同；根因是条纹锁 + 惰性追加依赖线程交错），
**但召回极差 ≤0.01pp** ⇒ 建图是「**边集不确定、质量确定**」的。
⇒ **召回/QPS 级结论稳定可比；图结构级结论（B1 覆盖率、跨分区边率）是单次采样估计。**

---

## 3. 文件索引

### 研究文档（`docs/research/`）
| 文件 | 内容 |
|---|---|
| `bootstrap-report.md` | 阶段0 架构地图 / 改造点清单 / 风险 |
| `l1-baseline.md`、`l1-followup.md` | L1 基线复现、α 消融、T1 基准修正 |
| `t1-epsilon-scaling-decision.md` | ε 上界随位宽缩放（5 bit 门槛 72%） |
| `t1-v1-pruning-tradeoff.md` | **T1 裁定**（V1 + V1b） |
| `t2-pipnn-recon.md` | T2 摸底（C1–C9）、B1 可达率 |
| `t2-b2-design.md` | **B2 设计**（`PartitionCtx` + 单分支注入点，保留未实现） |
| `t2-b2-result.md` | **B2-0 裁定**（平凡解 + G-det） |
| `t2-sift-crosscheck.md` | **SIFT 外部效度复核** + 召回崩塌根因 |
| `tsng-c1-baseline-result.md` | **TSNG 首次实测** |
| `baseline-competitors.md` | **★ 竞品基线（正向结论 + 论文形状）** |
| `alpha-default-reeval.md` | **α 默认值重评** |

### Bench（`benches/`，均 `required-features = ["ablation"]`）
`bench_alpha_mechanism` / `bench_rbq2_equal_bits` / `bench_rabitq_epsilon_scaling` /
`bench_pruning_tradeoff`（T1 六配置）/ `bench_t2_build_recon`（建图成本 + CSR 导出）/
`bench_t2_b2_partitioned`（B2-0 + α 扫描）

**仓库自带未改**：`bench_tsng_c0` / `c1` / `tsng_pipeline` / `pipeline_gate` / `bench_cohere1m` / `bench_sensitivity` / `bench_ssd_cold_hot` / `bench_variance`

### 环境变量开关（已实现）
| 变量 | 作用 | 适用 |
|---|---|---|
| `T2_PREFIX` / `T2_DIM` | 选数据集 | build_recon / b2 / probe / baseline |
| `T2_N` | 规模上限（0=全部） | build_recon / b2 / baseline |
| `T2_CSR` / `T2_OUT` | CSR 路径 / 探针输出 | probe |
| `T2_ALPHA` / `T2_EFC` / `T2_SKIP_DET` | α / 单一束宽 / 跳 G-det | b2 |
| `T2_FROZEN_RECALL` | 供守卫 G1（非 cohere 需显式） | b2 |
| `TRIVIUM_BUILD_PROFILE=1` | 建图五段式探针（**仓库自带**） | build_recon |
| `TRIVIUM_EAGER_PRUNE=1` | 反向剪枝 A/B（**仓库自带**） | build_recon |
| `BL_M` / `BL_EFC` / `BL_THREADS` | 竞品参数 | baseline |

### 脚本（`scripts/research/`）
`t2_partition_probe.py`（分区质量 + B1）、`baseline_competitors.py`（竞品）、
`l1_*` / `t1_*`（历史验证脚本）

### 结果（`results/`）
`l1/cohere1m.json`、`t2/partition_probe.json`（cohere）、`t2/partition_probe_sift128.json`、
`baseline/competitors_cohere.json`、`baseline/competitors_sift128.json`

---

## 4. 未决事项

| # | 项 | 状态 |
|---|---|---|
| U1 | **维度轴只有 2 个点**（768 / 128），边界在哪未知 | **最高优先** |
| U2 | α 默认值改动**尚未实施**（会动 `src/`，需确认） | 待批 |
| U3 | B2 的 `PartitionCtx` 设计**保留未实现** | 仅在冷层/超大规模重估时再启 |
| U4 | TSNG 只在**合成数据**上测过 | 需真实多模态数据 |
| U5 | B1 / 跨分区边率的**结构抖动未量化** | 可用多次建图重算得到置信区间 |
| U6 | 竞品只扫了一个 M=32 | M=16/48 可能改变倍差（但 3 个实现一致 ⇒ 量级稳） |
| U7 | `bench_t2_b2_partitioned` 的 **P1 判据在基线退化时失效**（SIFT 上所有臂都"达标"） | 判据需加绝对下限 |

---

## 5. 下一步（按优先级）

### P1（最高）——补维度轴，把 2 个点变成曲线
```powershell
& .venv\Scripts\python.exe scripts\prepare_all.py gist960    # 960 维（中点以上）
& .venv\Scripts\python.exe scripts\prepare_all.py glove100   # 100 维（低维端）
```
> ⚠️ gist960/glove100 走 `hdf5` 路径，**需要先手动下载** `gist-960-euclidean.hdf5`（~3.6GB）
> 与 `glove-100-angular.hdf5`（~460MB）到仓库根（`http://ann-benchmarks.com/`）。
> **glove100 是 angular ⇒ 直接用 HDF5 里的 GT，不重算。**

对每个数据集跑同一套：
```powershell
$env:T2_PREFIX="gist960"; $env:T2_DIM="960"
cargo bench --features ablation --bench bench_t2_b2_partitioned      # 建图 + R@10 + QPS
& .venv\Scripts\python.exe scripts\research\baseline_competitors.py  # 竞品
& .venv\Scripts\python.exe scripts\research\t2_partition_probe.py    # 分区结构（可选）
```

### P2（论文核心）——拟合"可分性 × 签名长度 → 召回"的预测关系
对每个数据集计算：
- 可分性 `(GT1−GT10)/cos_std`（诊断脚本已有，在 `t2-sift-crosscheck.md` §4 的口径）
- 签名长度 `2 × ceil(dim/64) × 64` bit
- QuIVer 最高召回（ef_s 扫描到饱和）
- 与最强竞品的同召回倍差

**目标**：给出一个**可预测的边界判据**（例如"可分性 < X 时 QuIVer 失效"），这是论文的核心图。

### P3 —— 落实 α 默认值（需批准）
`QuIVerConfig::default().alpha` `1.2 → 1.0`；`quiver.rs:952` 注释改为"1.0=推荐值"。
**注意**：α 已写入 `.quiver` 文件头 ⇒ 改默认值不影响已落盘索引。

### P4（可选）——工程收尾
- `ef_construction` 默认 `128 → 64`（1.55× 建图加速，−0.32pp）
- `load_bytes` 非零拷贝（摸底 R2）
- `layer0` 扩容 119ms 尾部

---

## 6. 方法论约定（**必须延续**）

1. **`src/` 零改动**是当前阶段的原则；一切实验 = 新 bench + Python + 文档
2. **所有臂同进程执行**（消除跨运行抖动）
3. **回归守卫**：任何改动后，cohere `ef_c=128` 必须复现 **97.52–97.56%**（±0.04pp）；偏离即参数化被破坏
4. **先预注册判据**，再跑实验；判据要设在**实测噪声地板之上**（T2 的 −1pp 曾恰好落在 ef_c=32 的噪声带里）
5. **每次实验都要有可证伪的守卫**（旋转正交性 / 界成立 / 保真度 / 剪枝零召回损失 / 注入点等价性 / 导出完整性）
6. **图结构级指标须标注"单次采样估计"**（G-det 已证边集不可复现）
7. **外部效度优先**：得出"某技术不成立"的结论前，必须先换维度/数据集复核（本次 SIFT 就证伪了我自己的假设）

---

## 7. 已知的坑

| # | 坑 | 规避 |
|---|---|---|
| K1 | PowerShell 是 GBK，中文/制表符会乱码或抛 `UnicodeEncodeError` | 脚本开头 `reconfigure(encoding="utf-8")`；命令前设 `[Console]::OutputEncoding` |
| K2 | 含中文的 `Select-String` 正则 + 引号嵌套会解析失败 | 别在 PowerShell 里写复杂正则；用 `search_content` 工具或写脚本 |
| K3 | `Get-Content` 无 `-Encoding` 会被安全策略拦截 | 显式 `-Encoding UTF8` |
| K4 | `git checkout -- <file>` 等会触发审批（可能超时） | 优先用"重新生成"而非 git 回滚 |
| K5 | `T2_N=0` 表示全部，但**等于数据量时增量插入样本为 0** | 测增量插入要设 `T2_N=数据量-若干` |
| K6 | 探针的 `T2_OUT=""` 传空串会静默不写文件 | 要么不设该变量，要么给显式路径 |
| K7 | 大数据集文件已被 `.gitignore` 覆盖（`*.f32` / `*.i32` / `*.hdf5`） | 无需担心误提交 |
| K8 | `bench_alpha_mechanism` **不测 recall**，只测拓扑机理；且硬编码 cohere | α 的 recall 效果要用 `T2_ALPHA` 走 b2 基准 |

# 交接文档 —— QuIVer 后继研究（会话交接）

> **分支**：`research/quiver2-pipnn-rabitq-tsng`（基点 `upstream/dev @ 043c328`）
> **提交**：`3637954` → `d66142f` → `b0b85a4` → `f132334` → `4c28ffe` → `d0e44e1` → **`33100ed`（实验 A，见 §2.6）**
> **源码状态**：**`src/` 已首次改动（仅 F1，默认关闭）**：`bq.rs`/`quiver.rs`/`tsng.rs` 新增
> `TRIVIUM_NAV_WEIGHTED` 开关（L0 查询导航换 6 类加权度量），**默认路径逐位不变**，
> 冻结值仍是回归守卫（`f1-metric-consistency.md`）。其余全部工作仍为零改动。
> **日期**：2026-09-17

---

## 0. 一句话状态

原定三腿（PiPNN + RaBitQ + TSNG）**全部测完，全部未成立**；
但竞品基线**首次复现了仓库自己的核心宣称（高维上快 HNSW 4–5×）**，
并暴露出一个精度-维数边界 —— 论文形状已从"融合三个技术"改为"BQ2 的适用边界"。

> ⚠️ **（2026-09-17 修正）** 已发表版本是 **PVLDB Vol. 20, 2027**（arXiv `2605.02171`，作者 Wenxuan Xiao /
> Zhiyou Wang / Chengcheng Li），其**自述的核心贡献就是这条边界**，且**明确说"维度不是分界线"**：
> 分组是数据属性（**cosine-native ≥88% / CLIP 71–78% / Euclidean-native 或 structureless <15%**，
> 12 个百万级数据集）。⇒ **"发现边界不是维度"不能当卖点**；我们的可发表贡献必须是
> **更精确的机制 + 修好可预先计算的判据 + 可操作的修复**。
> 完整的就绪度评估与缺口清单见 **`paper-readiness.md`**。
>
> **（2026-09-17 之二）P1 闸门实验已做，主判据不成立**：我们自己提出的"码估计信噪比"预测器
> （`SNR_eff = min(SNR_w, SNR_c)`）与召回的秩相关只有 **ρ = +0.30**（含 Random-Sphere 对应臂时），
> 失败原因已定位（残差型 `σ_code` 尺度自由 ⇒ 无结构档失效）；`gap` 单独（ρ=0.75–0.83）反而更好。
> 事后实测最准的是 **cheap 度量自身的码 top-10 命中率（ρ=+0.9762）**。⇒ 论文核心改为
> "**评估 + 修好论文自己的探针**（指明用哪个度量 / 两度量取弱环 / 补图保真度轴）"。详见 **`p1-snr-predictor-result.md`**。

**⚠️ 本会话（实验 A）修正了上面那条"边界"的归因**：gist960 的召回崩塌**不是维度问题**，
而是**数据全非负 ⇒ BQ2 的 `pos` 符号面退化为常量 ⇒ 建图所用度量退化为"按候选 popcount 选邻居"**，
叠加**建图与查询使用两个不一致的度量**。同时证伪了"上游 FHT 旋转 512 段"的怀疑
（`src/` 里**根本没有旋转**）。详见 §2.6 与 `t2-gist960-collapse.md`。

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

### 实验 A — ★★ gist960 召回崩塌的根因（本会话，`t2-gist960-collapse.md`）

**裁定**（判据预注册，R@10 @ef_s=128）：

| # | 结论 | 关键数字 |
|---|---|---|
| ❌ **H1 维度相关** | **证伪** | T-sweep 平坦**偏降**：960→`2.81%`、768→`2.84%`、512→`2.49%`、256→`2.08%`、128→`1.61%` |
| ✅ **H2 分布相关** | **成立** | 同 128 维下 cohere `72.30%` vs gist960 `1.61%` = **45×** |
| ✅ **H3 共同均值方向** | **成立** | T-center（去均值）**`2.81% → 51.96%`**（+49.17pp）；α=1.0 时 `64.54%` |
| ⚠️ **T-ctrl 判据失效** | 随机高斯 `0.83%`，但其 top-10 与 #11 间隔仅 `3.9e-4`（近并列，任务不可解）⇒ **不构成"维度有罪"的证据**；补正臂 **T-plant `100.00%`** 证明 960 维无罪 |
| ✅ T-pad / T-center-sift | dim=960 机制对照 `97.11%`（零填充稀释 `alpha` 解释 −0.40pp）；SIFT 去均值 `21.88% → 44.16%`（外部效度） |

**根因链（有实测）**：GIST 逐维 ≥ 0 ⇒ `pos=(v>0)` 恒为 1（`pos` 面 Hamming 率 **0.0000**）
⇒ weighted BQ2 退化为 `3·dim − |h_a| − |h_b| − <h_a,h_b>`，排序被**候选 popcount `|h_b|`** 主导
（实测偏置 **+3.34σ**；cohere 仅 `+0.06σ`）⇒ 建出的 L0 边**忠实于该度量**（`L0∩weighted_top64 = 68.35%`）
但**只有 0.57% 是真 cosine 近邻**（cohere `56.84%`）⇒ 查询拿不到正确候选池 ⇒ `2.81%`。

**两条结构性发现（本会话新增，代码事实）**：
1. **建图与查询用两个不同度量**：建图/剪枝/上层用 `distance_to_sig`（6 类权重），
   **查询 L0 束搜索用 `distance_to_sig_cheap`（纯 Hamming）**（`quiver.rs:1272-1281`），
   而 `quiver.rs:1225` 的注释声称"之后用完整 2-bit BQ 距离重排候选"，**实现里没有这一步**（`:2044` 直接进 f32 精排）。
   **没有任何开关**可在运行期切回。
2. **BQ2 距离的解析形式**（已被守卫逐位验证，最大差 0）：
   `distance_weighted = 4·dim − <w_a,w_b>`，`w = (2pos−1)(1+strong) ∈ {−2,−1,+1,+2}^dim`。
   这条恒等式让"全扫描的码排序"可用一次 GEMM 精确算出 ⇒ 才有 §5 的 oracle 分解。

**对论文的影响**：上轮 P2 的"用**可分性**预测召回/边界"**被证伪**（反例：`sift128c` 可分性
`0.1224 < 0.1291` 而召回翻倍；`gist960` 可分性高于 SIFT 而召回仅 1/8）。修正判据需要**两个独立量**：
① `pos` 面 Hamming 率（度量是否退化）；② `L0 ∩ cos_top64`（图是否真近邻图，需 CSR 导出实测）。

### P1 — 码估计信噪比预测器（本会话，`p1-snr-predictor-result.md`）：**主判据不成立**

**结论**（预注册，闸门实验）：
| 项 | 结果 |
|---|---|
| 预注册判据 `SNR_eff` 与 R@10@ef=64 的 ρ ≥ 0.9 | ❌ **不成立**：含 Random-Sphere 对应臂（gauss960）时 **ρ = +0.30**（不含时 +0.80；4 点下多个量并列 1.0，**无分辨力**） |
| 失败诊断 | 残差型 `σ_code` **尺度自由** ⇒ 无结构数据局部 cosine 展布极小 ⇒ σ 被低估（gauss960 `0.015` < gist960 `0.025`）⇒ SNR 虚高而实际召回最低（`0.41%`）；`gap 单独`（ρ=0.75–0.83）反而优于 `snr_eff` |
| 事后最佳替代 | **cheap 度量自身的码 top-10 命中率**：ρ = **+0.9762**（8 行）/ +1.0000（论文 5 个对应行） |
| ★ 附带发现 | 论文的 *Practical Compatibility Test* **未指明用哪个 BQ 度量**；gauss960 上 weighted `16.70%` vs cheap `0.85%`（**20×**），cohere 上几乎相同（1.01×） |

**路径决定**：① 不以"新标量预测器"为论文核心；② 改为"**评估 + 修好已发表的探针**"（指明度量 / 两度量取弱环 / 补图保真度轴）；
③ P2 仍做，但目的改为**在论文自己的 12 行上评估论文自己的探针**；④ 无结构档（Random-Sphere）**不并入同一预测器**（论文 Finding 4 已单独解释）。

### P2（修订版）— 复现论文的 *Practical Compatibility Test*（本会话，`p2-revised-result.md`）

| 预注册判据 | 结果 |
|---|---|
| **P2-1** `cheap`、`S=10K` 探针与召回的 ρ ≥ 0.9 | ✅ **+0.9500**（n=9）；`S=100K` +0.9833；`S=1M` +0.9500。**对照：`weighted` 只有 +0.8167/+0.85/+0.85（不成立）** |
| **P2-2** `S=10K` 用 50% 阈值分开"崩塌档 / 竞争档" | ✅ 可分（w: 29.90 < 50 < 57.75；c: 19.65 < 50 < 54.95） |
| **P2-3** 两度量是否给出**相反 verdict** | ★ **确认**：`random`(Synthetic-LR, 召回 43.60%) **w 66.95% vs c 45.25%** |
| **P2-4** 探针随 `S` 的依赖幅度 | ★ 最大 **6.8×**（gauss960 cheap 4.40→0.65），方向是**样本越小越乐观** |
| 与论文对拍 | 论文 Table 10（Cohere-100K 2-bit SM = **64.7%**）vs 我们 `S=100K` **63.20/61.55%** ⇒ **可复现到 3pp** |

**跨口径校准累计 6/12 行**：cohere Δ−0.50 / glove100 +0.74 / sift128 +0.92 / gist960 +0.09 /
**Synthetic-LR +1.84** / **Random-Sphere +0.08**（后两个数据集是**仓库自带生成器，零下载**：
`bench_random1m`（k=64 低秩+Zipf 簇）与 `bench_random_sphere`（纯高斯球面））。

**⇒ 三条可写进论文的批评**：① 判据**未指定 BQ 度量**（两度量在 Synthetic-LR 上结论相反）⇒
修正为 **`min` 两度量**（ρ=+0.95，且在"建图度量才是瓶颈"的行上更保守）；
② **强依赖样本量**（6.8×，且 S 越小越乐观 ⇒ 50% 阈值在小样本下更难报警）；
③ 论文四档是**事后标签**，可替换为 P1+P2 给出的**先算后测**组合（`min` 双度量探针 + 图保真度 + `GT10−GT11`）。

### N1–N4（本会话，`audit-and-direction.md`）—— 三条重要更新

1. **去均值修复推广到全部四档**（`wolt_clip` 71.48% vs 论文 70.68% ⇒ 校准 **7/12 行**）：
   GIST `+37.6pp`、SIFT `+14.9`、**Wolt-CLIP `+5.3`**、GloVe `+3.3`、cohere `−1.2`（中性）、
   **各向同性对照（`‖μ‖=0.001`）`+0.03pp`** ⇒ 流水线无伪影。
   ⇒ **论文明确宣称 "zero preprocessing" 并只建议"改用 float32"**（N3 核对原文）⇒ **修复落在其空白处**。
2. ❌ **U14 撤回**：`glove100` 的 GT **无问题**（100.00% 一致）；84.85% 是**我自己的子采样伪影**（K23）。
3. ⚠️ **竞品地图推翻了"四档 = 竞争力"的读法**：**去均值前** 有竞品数据的 **3/4 档被 HNSW 严格支配**
   （wolt_clip：QuIVer 上限 86.81% < hnswlib ef=64 的 87.86%；glove100：71.69% < 82.05%；sift128：47.21% < 97.46%）
   ⇒ 明确获胜的只有最高档（cohere-768，4.6–5.0×）。
4. ✅ **D1/D2（后续本轮）**：
   - **D1 判据链**：`sign_info`（逐坐标符号熵的**均值**）是"是否可被去均值修复"的分诊量
     （0.000 = gist960 全系/sift128 ⇒ 可修；1.000 但 `probe_ef<50%` = sphere ⇒ 不可修）；22 臂 21 臂判定一致。
     ★ **硬发现**：论文默认的**加权 6 类**度量在 Random-Sphere 上给 **53.2%（>50% ⇒ "兼容"）**，
     而该集实测召回 **0.91%**；**取双度量最弱（`min`）恰给 4.7% 并修掉这个假阳性**。
   - **D2 修正 A9/A11**：去均值把 **CLIP 档从"严格支配"推入"曲线相交"**
     （≥89% 高召回区 QuIVer 9,356 QPS vs hnswlib 4,124–2,394 ⇒ 快 **2.3–3.9×**；低 ef 区 HNSW 快 1.1–1.3×）；
     `glove100c` 仍严格支配（73.31%@11,021 vs 83.98%@33,617）。 ⇒ **"不改变判定"的说法过于绝对**。

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
| `t2-gist960-collapse.md` | **★★ 实验 A：gist960 崩塌根因（H1/H2/H3 + 两个度量不一致 + 图质量实测）** |
| `paper-readiness.md` | **★★ 论文就绪度：对标已发表 QuIVer(PVLDB 2027) Table 11 的贡献定位、缺口 G1–G12、A/B/C 分层 DoD、P0–P7 执行顺序** |
| `p1-snr-predictor-result.md` | **★★ P1 闸门实验：SNR 预测器主判据不成立 + 失败诊断 + 路径决定（D1–D4）** |
| `p2-revised-result.md` | **★★ P2 修订版：复现论文的 compatibility test（P2-1~P2-4）+ 度量歧义 + 样本量依赖 + 三条可写批评** |
| `audit-and-direction.md` | **★★★ N1–N4 结果 + 旧结论逐条审查 + 新方向（D1–D4）+ 论文可行性（含停止条件）**；§9 = D2 竞品曲线与 A9/A11 修正 |
| `t2-deployability-gate.md` | **★★ D1 可部署性判据链**：`sign_info` 分诊 + 双度量最弱探针；含 Random-Sphere 上 **53.2% vs 0.91%** 的假阳性发现 |
| `scripts/research/deployability_gate.py` | D1 脚本（22 臂，产物 `results/t2/deployability_gate.json`） |
| `f1-metric-consistency.md` | **★★ F1 补丁（首个 `src/` 改动，默认关闭）+ 6 数据集 A/B：`sign_info` 完美预测 F1 的收益符号** |

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
`l1_*` / `t1_*`（历史验证脚本）、
**本会话新增**：`gist960_collapse_prepare.py`（派生数据集 + GT 重算 + 守卫）、
`bq2_code_ceiling.py`（码的 oracle 分辨力，**自带"分析式 vs `bq.rs` 逐位"守卫**）、
`graph_neighbor_quality.py`（L0 ∩ 真 top-64，图质量实测，需 `bench_t2_build_recon` 的 CSR 导出）、
`code_snr_probe.py`（P1：`gap` / `σ_code` / `SNR` / 码 top-10 命中率；`--report` 可离线重算；
**每数据集独立确定种子**）、`compat_probe_scaling.py`（P2：论文 compatibility test 的**样本量×度量**扫描；`--report`）

### 新增数据集（仓库自带生成器，**零下载**）
```powershell
cargo bench --features ablation --bench bench_random1m      # → random_{train,test}.f32 + GT（论文 Synthetic-LR 41.76%）
cargo bench --features ablation --bench bench_random_sphere # → sphere_{train,test}.f32 + GT（论文 Random-Sphere 0.40%）
```

### 结果（`results/`）
`l1/cohere1m.json`、`t2/partition_probe.json`（cohere）、`t2/partition_probe_sift128.json`、
`baseline/competitors_cohere.json`、`baseline/competitors_sift128.json`、
**本会话新增**：`t2/gist960_collapse/{12 个派生数据集}.json`（可分性/拥挤度/GT10−GT11 口径）、
`t2/gist960_collapse/code_oracle.json`（码 oracle 表）、`t2/gist960_collapse/graph_quality_*.json`（图质量表）

---

## 4. 未决事项

| # | 项 | 状态 |
|---|---|---|
| **U1** | ~~维度轴只有 2 个点~~ | ✅ **已闭环（本会话）**：补到 5 个维度点（128/256/512/768/960）+ cohere 四档对照，**结论反转** —— 维度**不是**主因（§2.6） |
| U2 | α 默认值改动**尚未实施**（会动 `src/`，需确认） | 待批，**优先级上调**：本会话新增 `gist960c` 上 `+12.58pp`（1.2→1.0） |
| U3 | B2 的 `PartitionCtx` 设计**保留未实现** | 仅在冷层/超大规模重估时再启 |
| U4 | TSNG 只在**合成数据**上测过 | 需真实多模态数据 |
| U5 | B1 / 跨分区边率的**结构抖动未量化** | 可用多次建图重算得到置信区间 |
| U6 | 竞品只扫了一个 M=32 | M=16/48 可能改变倍差（但 3 个实现一致 ⇒ 量级稳） |
| U7 | `bench_t2_b2_partitioned` 的 **P1 判据在基线退化时失效**（SIFT 上所有臂都"达标"） | 判据需加绝对下限 |
| **U8** | ✅ **F1 已实现并实测（2026-09-18）**：`TRIVIUM_NAV_WEIGHTED=1`（默认关闭 ⇒ 冻结值不变）。**结论反转**：不是纯 bug，而是**数据依赖的 trade-off** —— `sign_info ≥ 0.75` 全受益（glove100 **+21.8pp**、gauss960 2.9×、wolt_clip +0.9、cohere +0.5），`sign_info = 0.000` 全受损（sift128 **−13.4pp**、gist960 −1.3）；QPS 代价 ≲9% ⇒ 见 `f1-metric-consistency.md`。**F2 未做；F3（签名前去均值）已由 bench 侧的去均值臂替代（动磁盘契约的建议仍待产品侧）** |
| **U19** | **「去均值 + weighted 导航」组合臂未测**：`gist960c`/`sift128c` 的 `sign_info ≈ 0.92–0.98` ⇒ 按 D1→F1 的条件链应在去均值后打开加权导航 | 每个数据集 ~2 分钟（4 个臂） |
| **U9** | **图质量指标的抖动与置信区间** | `L0 ∩ cos_top64` 目前是**单次导出 + 256 节点采样**；需多次建图求区间（与 U5 同源） |
| **U10** | **去均值的部署语义** | `t2-gist960-collapse.md` §7.1 方案 A：门控指标（`pos` 面 Hamming 率 / `cos(x,μ)`）、`μ` 的库级持久化与增量一致性、是否改变产品语义 —— **需产品侧确认** |
| **U11** | 论文的"两个准入量"判据只在本轮 4 个数据集上验证 | 需 384/1024/1536 维更多点补曲线（`minilm`/`bge_m3`/`dbpedia1536`） |
| **U12** | **P1 的 SNR 预测器已被证伪**（`p1-snr-predictor-result.md`）；P2 已给出可用替代（`min` 双度量探针 ρ=0.95，见 `p2-revised-result.md`），但只在 **9 行**上验证 | 需补齐论文剩余 6 行（`minilm-384` / `wolt-clip-512` / `redcaps-512` / `bge-m3-1024` / `dbpedia-1536` / `dbpedia-3072`；**`redcaps-1m` 在本仓 registry 里不存在，可复现性未知**） |
| **U13** | ✅ **已量化**：论文判据**未指明度量**，且在 Synthetic-LR 上 w `66.95%` vs c `45.25%` 给出**相反 verdict**；另测出**样本量依赖 6.8×**（`p2-revised-result.md` §4） | 结论已定；剩下去 PDF 逐格复核论文原文的探针描述（是否指定度量 / 样本是"库"还是"库+查询"） |
| **U14** | ❌ **已撤回（2026-09-18 / N2）**：`glove100` 的 GT **没有问题**（原生 angular GT 与我们重算的 cosine top-10 **100.00%** 一致）。那个 84.85% 是 **`compat_probe_scaling.py` 的子采样伪影**（`S_LIST` 上限 1e6 < `n=1,183,514` ⇒ "S=全量"实为 84.49% 基底） | 已在脚本加"基底占比"列与警示；`p2-revised-result.md` §5-2 已更正 |
| **U15** | ✅ **已完成（D2）**：`wolt_clipc` **从严格支配 → 曲线相交**（≥89% 区 QuIVer 快 2.3–3.9×）；`glove100c` 仍严格支配 ⇒ **A9/A11 已修正**（`audit-and-direction.md` §9.4） | 余下：**`gist960c` 的竞品曲线未测**（U18） |
| **U18** | `gist960c` 的竞品曲线（预期仍被支配，但论文需要数字） | ~15 min（960 维建图慢） |
| **U16** | 论文剩余 5 行数据集（`minilm-384` / `bge-m3-1024` / `dbpedia-1536/3072`；`redcaps-512` 不在 `prepare_all` 注册表内，可能不可得） | 1–2 天 |
| **U17** | 图保真度 `L0∩cos_top64` 只有 4 个数据集 | 需补 ≥6（每个建图 + CSR 导出） |

---

## 5. 下一步（按优先级）

> **先读 `paper-readiness.md`**：它给出论文就绪度评估、缺口清单（G1–G11）、分层 DoD（Tier A/B/C）
> 与审稿人预演。**其中 P0（跨口径校准）是最高优先且最便宜（1–2 h）**：
> ```powershell
> $env:TRIVIUM_ANN_NAME="cohere-1m"; $env:TRIVIUM_SENSITIVITY_MODE="params"
> $env:TRIVIUM_SENSITIVITY_START="1d"; $env:TRIVIUM_SENSITIVITY_END="1d"
> cargo bench --bench bench_sensitivity     # 论文自己的 harness，与 bench_t2_b2_partitioned 对拍
> ```
> 判据：每点偏差 ≤0.5pp ⇒ 口径打通；>1pp ⇒ 必须改用论文 harness 重跑全部实验。

### ~~P1（闸门）—— 码估计信噪比预测器~~ ✅ **已完成 → 主判据不成立**
产物：`scripts/research/code_snr_probe.py` + `results/t2/gist960_collapse/snr_probe.json` +
**`p1-snr-predictor-result.md`**（8 行结果、失败诊断、路径决定 D1–D4）。
**结论**：`SNR_eff` ρ=+0.30（含 Random-Sphere 臂）⇒ 不以"新预测器"为核心；
改为"**评估 + 修好论文自己的探针**（指明度量 / 两度量取弱环 / 补图保真度）"。

### ~~P1-next（在论文自己的 12 行上评估论文自己的探针）~~ ✅ **已完成 → 见 §2 的 P2（修订版）**
产物：`scripts/research/compat_probe_scaling.py` + `results/.../compat_probe_scaling.json` +
**`p2-revised-result.md`**（9 行 × 3 个样本量 × 2 个度量）。

**诚实记账**：P1 文档里预注册的推论（"论文 Random-Sphere 一行若用 weighted 度量做探针会远高于 50%"）
**❌ 被证伪**——实测 sphere 的 weighted 探针 `29.85%（10K）/ 18.20%（全量）`，**低于** 50%，
即探针给出了**正确**的 "incompatible"。⇒ **该推论撤回**。
但同一担忧（判据未指定度量）在 **`random`（Synthetic-LR）** 一行上以另一种方式成立：
w `66.95%` vs c `45.25%` ⇒ **相反 verdict**（`p2-revised-result.md` §4.1）。

### 下一步（优先级已重排）
| # | 事项 | 说明 |
|---|---|---|
| **N1（最高）** | **补齐论文剩余 5 行**：`minilm-384` / `bge-m3-1024` / `dbpedia-1536/3072`（**`redcaps-1m` 不在 `prepare_all` 注册表内，可能不可得**） | 现在"竞争档"只有 1 行，P2-2 的判定样本仍薄（U12/U16） |
| ~~N2~~ | ✅ **已完成并撤回**（`glove100` GT 无问题，是子采样伪影） | 见 `audit-and-direction.md` §2 |
| ~~N3~~ | ✅ **已完成**：探针定义在 §6、**未指定度量**、**未说明样本来源**、**明确宣称 zero preprocessing**、失败建议只是"改用 float32" ⇒ 我们的修复落在其空白处 | 见 `audit-and-direction.md` §3 |
| **N4** | 修复臂竞品曲线 ✅（U15，除 `gist960c`）+ **F1 补丁端到端（仍待批准）** + α=1.0 A/B | `audit-and-direction.md` §7.2 |
| **D1** | ✅ 判据链建成 + 22 臂验证（`t2-deployability-gate.md`）；余：把它写成论文的"部署决策"一节 | — |
| **D2** | ✅ 见 U15；余：`gist960c`（U18） | — |

> ### ⚠️ 论文口径必须先修正（`audit-and-direction.md` §5 的两条）
> **A9**：去均值**只提高召回，不改变竞争判定**（gist960c 上限 79.4% / glove100c 73.3%，仍低于 HNSW 的最低工作点）。
> **A11**：论文的四档是**绝对召回梯度**，不是**竞争力**；有竞品数据的 **3/4 档被 HNSW 严格支配**（含"较高"CLIP 档）
> ⇒ **QuIVer 只在最高档（cohere-768）有优势**。
> **停止条件已写死**在 `audit-and-direction.md` §7.3（超过 2 周或 G-b 为负 ⇒ 只发 arXiv + 上游 PR）。

### ~~P1——补维度轴，把 2 个点变成曲线~~ ✅ **已完成（本会话）**
`gist960` / `glove100` / `sift128` / `cohere` 四点已在上一轮跑完；本会话又补了
`gist960k{768,512,256,128}` + `coherek{512,256,128}` + 5 个判别臂（见 §2.6）。
**结论已反转**：维度不是主因，主因是"数据全非负 ⇒ pos 面退化 ⇒ 建图度量失效 + 度量不一致"。

### P0（最高，需批准）—— 决定 U8 的走向
| 选项 | 内容 | 前置 |
|---|---|---|
| **N1** | 批准 **F1**（L0 查询导航换 weighted 度量）+ 同测 QPS 代价 | 需要在改后重跑 4 个数据集的召回与 QPS（含 cohere 回归） |
| **N2** | 先做**零 `src/` 改动**的规避：**签名前去均值**（在 bench 侧/应用侧实现），量化其代价与语义（U10） | 无需批准，但要产品侧确认语义 |
| **N3** | 只补**论文的判据**（`pos` 面 Hamming 率 + `L0 ∩ cos_top64` 两个准入量），暂不动 src | 需 U11：补 384/1024/1536 维数据点（`minilm` 384 / `bge_m3` 1024 / `dbpedia1536`） |

### P1 —— 补齐 U9/U11（把两个准入量做成"曲线"）
```powershell
# U9：图质量抖动（多次建图求区间）
$env:T2_PREFIX="gist960"; $env:T2_DIM="960"; $env:T2_DUMP=".tmp/l0_csr_gist960_r1.bin"
cargo bench --features ablation --bench bench_t2_build_recon       # 重复 3 次
& .venv\Scripts\python.exe scripts\research\graph_neighbor_quality.py gist960
# U11：补维度点（先 prepare_all.py 下载）
& .venv\Scripts\python.exe scripts\prepare_all.py minilm bge_m3
```

> ⚠️ gist960/glove100 走 `hdf5` 路径，**需要先手动下载** `gist-960-euclidean.hdf5`（~3.6GB）
> 与 `glove-100-angular.hdf5`（~460MB）到仓库根（`http://ann-benchmarks.com/`）。
> **glove100 是 angular ⇒ 直接用 HDF5 里的 GT，不重算。**

单数据集标准流程（换 `T2_PREFIX`/`T2_DIM` 即可）：
```powershell
cargo bench --features ablation --bench bench_t2_b2_partitioned      # 建图 + R@10 + QPS
& .venv\Scripts\python.exe scripts\research\baseline_competitors.py  # 竞品
& .venv\Scripts\python.exe scripts\research\t2_partition_probe.py    # 分区结构（可选）
& .venv\Scripts\python.exe scripts\research\bq2_code_ceiling.py      # 码的 oracle 分辨力（本会话新增）
```

### ~~P2（论文核心）——拟合"可分性 × 签名长度 → 召回"的预测关系~~ ⚠️ **判据已证伪，需重写（本会话）**
原判据把**可分性**当作唯一预测量。本会话给出三个反例（`t2-gist960-collapse.md` §8）：
`sift128c` 可分性更低而召回**翻倍**；`gist960` 可分性高于 SIFT 而召回仅 **1/8**；
`gauss960` 可分性 `0.5727`（高）而召回 `0.83%`（top-10 近并列，任务不可解）。

**修正后的目标**（下一轮继续证伪）：预测需**两个独立量**
1. **度量有效性**：`pos` 面随机对 Hamming 率 `< 0.02` ⇒ weighted 度量退化（本节 4 个数据点已测）
2. **图保真度**：`L0 ∩ cos_top64`（`graph_neighbor_quality.py` 直接测，4 个数据点已测）

再加一条**任务可解性**前置检查：`GT10 − GT11` 间隔（随机高斯云仅 `3.9e-4` ⇒ 任何方法都不可解）。

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
8. **（本会话新增）与 `src/` 的等价性必须逐位验证**：任何"用 Python 复现 Rust 内部量"的诊断脚本，
   必须自带一条**对 `src/` 实现逐位对拍**的守卫（`bq2_code_ceiling.py` 的 `guard()`：分析式 vs 6 类权重公式，最大差 0）。
   否则"根因"可能只是复现器的 bug。
9. **（本会话新增）判据的"分支预设"本身要能被证伪**：T-ctrl 的判据把"≥90% 或 ~3%"当完备划分，
   但两者之外还有第三种情况——**任务不可解**（top-10 近并列）。设计判据时要先问
   "若两种预期都落空，我能否区分'机制坏了'与'任务本身无解'？"（本会话为此追加 T-plant）
10. **（本会话新增）单变量对照必须逐项核对"是否真的只变了一个量"**：T-pad 看似只改维度，
   实则 `alpha = Σ|v|/len` 的分母也变了 ⇒ 码被改变。凡是"看起来很干净"的对照，都要把
   被变换量的**定义式**再读一遍。

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
| **K9** | `cargo` 不在新 shell 的 PATH 上（报"术语 'cargo' 不会被识别"） | 命令前加 `$env:PATH="$env:USERPROFILE\.cargo\bin;$env:PATH"` |
| **K10** | **`T2_ALPHA=""` / `T2_FROZEN_RECALL=""` 等价于"未设置"**（`env_var` 拿到空串 → `parse` 失败 → 走默认）。但 `T2_PREFIX=""` 会真的变成空前缀 ⇒ 找不到文件。跨命令残留的 env 会污染下一臂 | 每条 bench 命令里**显式重设全部 T2 变量**；env 在同 shell 内会延续 |
| **K11** | **`alpha = Σ|v| / vec.len()` 让"零填充到更高维"改变码**：补零不改 Σ|v| 但改分母 ⇒ 阈值 ×0.8 ⇒ strong 位增多 | 需要"保序"的对照时**不能**用零填充；见 `t2-gist960-collapse.md` §4.5 |
| **K12** | 生成脚本里"植入点"若用未单位化的扰动 `c + δ·g`（`g~N(0,I)`），`‖δg‖≈δ√dim ≫ ‖c‖`，植入点会退化成随机方向（cos `≈1/(δ√dim)`），**守卫会以 23.88% 命中率抓出** | 扰动必须**单位化**后再按 δ 加权；任何"构造性数据集"都要有"植入是否真的进入 GT"的断言 |
| **K13** | Python 里 `s[mask_index]` 用**全局下标**索引一个**子采样数组**会 `IndexError`（哨兵自校验踩过） | 子采样后要么用位置映射，要么直接对原数组取该行做点积 |
| **K14** | `np.abs(tr).sum(1) / np.linalg.norm(tr, axis=1)` 在全零行上产生 `nan` 并刷 warning（gist960 有 10 行全零） | 各向异性统计要加 `np.maximum(norm, 1e-12)` |
| **K15** | `bench_t2_build_recon` 的**守卫1 只对 cohere+1M+惰性生效**（安全用于其它数据集）；但它的 `T2_N=0` 表示全部 ⇒ **增量插入样本为 0，阶段 C 自动跳过**（与 K5 同源） | 想测增量插入必须 `T2_N=数据量-N` |
| **K16** | `bench_t2_b2_partitioned` 用 `T2_FROZEN_RECALL` 时是**硬断言**（偏差 >1pp ⇒ panic，位于 markdown 表打印之前 ⇒ 丢表） | 派生数据集要么不传该变量，要么确认真能复现；stderr 的逐臂行已足够留档 |
| **K17** | **"码排序质量"类指标必须用测试向量自己的签名**。P1 首版误用 `train[q]` 的行当查询码 ⇒ 码的 top-1 恒为候选自身 ⇒ 命中率恒 `0.00%`，σ/SNR 全部失真 | 任何这类指标都要与**已独立验证过的实现**对拍（`bq2_code_ceiling.py` 的 `code_only_*`：glove100 32.23/19.31、sift128 3.11/10.03），并写成**硬断言哨兵** |
| **K18** | `np.random.default_rng` 状态随"跑了哪些数据集 / 什么顺序"漂移 ⇒ 同一数据集抽样不同 ⇒ 数值不可复现（实测 glove100 的 `gap` 两次运行差 35%） | 每个数据集用**独立确定种子**：`default_rng([SEED, dim, Σord(prefix)])` |
| **K19** | `Remove-Item` 删 `results/` 下文件会触发审批（可能超时并打断整条命令链） | 需要"重跑"时**不要删**：结果 JSON 按前缀合并覆盖即可（`code_snr_probe.py` / `bq2_code_ceiling.py` 都支持） |
| **K20** | **"先评估后落盘"会让一个聚合异常吃掉整批结果**：`compat_probe_scaling.py` 的 `evaluate()` 在"竞争档为空"时 `min([])` 抛 `ValueError` ⇒ 该批 JSON 根本没写；分批跑时前一批全丢，直到 `--report` 只显示 4 行才发现 | ① **先写盘再评估**；② 分批长跑**每批结束都用 `--report` 核对行数**；③ 所有"某类可能为空"的聚合都要有空值分支（打印 `（无）` 而非崩溃） |
| **K21** | 仓库自带的两个"无结构/低秩"数据集生成器**不需要下载**，但会往**仓库根**写 ~3 GB：`bench_random1m` → `random_*`（Synthetic-LR）、`bench_random_sphere` → `sphere_*`（Random-Sphere）；`bench_sensitivity` 的 registry 名分别是 `random-1m` / `sphere-1m` | 想补论文 Table 11 的"无结构档"时**先跑这两个**（各 ~2 分钟），别去下载 |
| **K22** | **去均值的均值必须在"归一化后"的数据上算**：`derive()` 是"先归一化再 transform"，而 **cohere 的磁盘文件未归一化**（`hf_bin`/`hf` 源都可能如此）⇒ 直接减原始均值（`‖μ‖=11.5`）会得到 `随机对 cos = 0.9973` 的退化数据 | 守卫 **`‖μ‖ ≤ 1 + 1e-3`**（单位向量均值的范数不可能 >1）已写进 `center_generic`；`streaming_mean(..., normalize=True)` |
| **K23** | **`S_LIST` 的上限可能小于 `n`**：`compat_probe_scaling.py` 的 `S=1e6` 对 `glove100`（`n=1,183,514`）只是 **84.49% 子采样** ⇒ 该行"样本内 f32 top-10 ∩ 数据集 GT"只有 84.85%，**看起来像 GT 有问题**（我一度据此写了 U14，已撤回） | 所有"子采样 vs 全量"的对比都要打印**基底占比**；诊断量异常时先怀疑自己的采样，再怀疑数据 |
| **K24** | **竞品脚本里的 `faiss_exact` 是必要的"并列地板"检查**：`wolt_clip` 上它只有 **90.09%**（cohere/glove100 为 100.00%、sift128 99.94%）⇒ 该数据集的召回上限被并列锁死，**不可与其它集横比** | 报任何数据集的召回前，先看 `faiss_exact`；<99% 就要标注并列地板 |
| **K25** | `scripts/prepare_all.py` 的 `binary_vector` 分支假设向量是 **JSON 字符串**，而 `wolt_clip` 当前 revision 直接给 `list` ⇒ `TypeError: the JSON object must be str, ... not list` | 已做最小容错（`isinstance` 判断）；记入上游缺陷清单（第 4 条） |
| **K26** | **别把 MiB 当 MB**：`[math]::Round($_.Length/1MB,1)` 里的 `1MB` = 1,048,576 ⇒ `wolt_clip_train` 显示 "1953.1" 而实际是 **2,048,000,000 B = 1,000,000×512 行**。我据此误判"流式只取到 953,662 行"并写进限制 L3（已撤回） | 行数**一律**用 `Length / 4 / dim` 算；`.f32` 的字节数/4/dim 才是行数 |
| **K27** | **维度专用内核容易写错度量**：我第一版 `deployability_gate.py` 把 `pos` 写成 `v >= 0`（正确是 `v > 0`）、并即兴推了一个加权 6 类公式 | **永远从 `bq2_code_ceiling.py` 里已过守卫的三式复制**（`pos = v > 0`、`w = (2p−1)(1+s)`、cheap = `(｜p｜+｜s｜) − 2(<p,p>+<s,s>)`） |
| **K28** | **把"代码不一致"当 bug 之前先做 A/B**：F1（建图 weighted / 导航 cheap 的不一致）看着像疏漏，实测却是**数据依赖的 trade-off**——sift128 `−13.4pp` vs glove100 `+21.8pp`。上游把导航设成 cheap **是符号面退化数据上的保护** | 任何"两处用了不同度量/不同路径"的发现，先进 A/B；再问 D1 的 `sign_info` 属于哪一侧 |

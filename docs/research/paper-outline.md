# 论文骨架（Tier A 定位）

> **日期**：2026-09-20 ｜ **状态**：可动笔（缺口见 §6）｜ **依据**：`audit-and-direction.md`、`t2-deployability-gate.md`、`f1-metric-consistency.md`、`t2-gist960-collapse.md`、`p1-*`、`p2-*`

---

## 1. 一句话定位

> **第三方评估 + 构造性修复**：我们独立复现了 QuIVer（PVLDB'27）的适用性主张（12/12 行；其中 11 行无条件），
> 发现**它的"适用性档位"描述的是绝对召回而非竞争力**（有竞品数据的 3/4 档被 HNSW 严格支配），
> 定位了**崩塌档的共同机制**（`pos` 符号面退化），并给出**一条几秒钟可判、两步可修的流水线**——
> 它不是修补边角，而是把 2 个数据集从"被支配"推到"平价"、把最差档从 2.81% 提到 58.18%。

**性质**：评估/复现类（不是新算法）。**不做**"我们提出一个更好的索引"这种主张。

**标题候选**
1. *Applicability Is Not Competitiveness: An Independent Evaluation and a Data-Side Repair for BQ-Native Graph Indexing*
2. *When Does QuIVer Beat HNSW? Diagnosing the Sign-Plane Collapse and a Two-Step Repair*
3. *The Sign Plane Matters: Why 2-Bit Quantized Graph Indexes Collapse on Non-Negative Embeddings*

---

## 2. 贡献清单（每条都已实测，附证据位置）

| # | 贡献 | 强度 | 证据 |
|---|---|---|---|
| **C1** | **两步数据侧修复流水线**：`sign_info` 分诊 → 去均值 → 加权导航。GIST `4.38%→82.77%`（@ef_s=1024，≈19×）、SIFT `47.23→92.47`、GloVe `71.69→93.32`；各向同性数据 `+0.03pp`（无操作对照）；`sphere` 走完全流程仍 2.91%（诚实边界）。**并把 glove100 从"被支配"推到"平价"、sift128 差距 50pp→5pp** | ★★★ | `f1-metric-consistency.md` §4.1、`audit-and-direction.md` §9.5、`t2-gist960-collapse.md` |
| **C2** | **竞争力边界 ≠ 适用性梯度**：论文四档只描述绝对召回；有竞品数据的 3/4 档被 HNSW 严格支配（含论文称"较高"的 CLIP 档，且 QuIVer 上限 < HNSW 最低工作点 ⇒ 曲线无交点） | ★★★ | `audit-and-direction.md` §4.1 |
| **C3** | **判据的两处不完备**：① 未指定 BQ 度量 —— 按论文默认的**加权**口径实现，在 Random-Sphere（实测 0.91%）上给 **53.9%（>50% ⇒ "兼容"）的假阳性**；② 强依赖样本量（候选样本 6.8×、查询子集 4–7pp） | ★★☆ | `p2-revised-result.md`、`t2-deployability-gate.md` §3-②④ |
| **C4** | **可预先计算的判据链**（同 C1 的 `sign_info` 同时决定"该不该去均值/该用哪个导航度量" + 双度量最弱探针），26 臂验证 21 臂一致、K=3 复跑裁决全不变 | ★★☆ | `t2-deployability-gate.md` §1–§3 |
| **C5** | **两个工程缺陷**：建图/查询导航度量不一致（我们把 A/B 做全，发现它是**数据依赖的 trade-off** 而非纯 bug）+ `α` 默认值落在平台最差端 | ★★ | `f1-metric-consistency.md`、`alpha-default-reeval.md` |
| **C6** | **独立复现**：12/12 行（11 行无条件，RedCaps 行依赖声明的采样协议）、最大偏差 1.84pp；cohere 上 4.6–5.0× 加速用 4 个实现复核；并给出 `faiss_exact` 并列地板（wolt_clip 90.09%）这类**协议级警告** | ★★ | `audit-and-direction.md` §1.1 |

---

## 3. 章节骨架

| 节 | 内容 | 依赖 | 现状 |
|---|---|---|---|
| §1 Intro | 动机：BQ-native 索引的"能不能用"问题；我们的三个发现（复现→边界→修复）；贡献列表 | — | ✅ 素材齐 |
| §2 Background | QuIVer 的 2-bit SM 编码与 6 类加权距离；HNSW/IVF 基线；`pos/strong` 两位面的语义；**给出 `w=(2p−1)(1+s)` 与退化恒等式**（我们已逐位验证） | `t2-gist960-collapse.md` §2–3 | ✅ 素材齐 |
| §3 Methodology | 统一 harness（`bench_t2_b2_partitioned`）；四档划分；R@10/QPS 口径；**我们与论文的协议差异（euclidean→cosine 重算 GT）**；G-det 噪声 | HANDOFF §6 | ✅ 素材齐 |
| §4 Reproduction | **表 1：12/12 行校准**（RedCaps 行带 † 协议假设标注）（含 Δ 与 `redcaps` 不可复现的三条证据）；4.6–5.0× 加速复核；`faiss_exact` 地板 | `audit-and-direction.md` §1 | ✅ 齐 |
| §5 Boundary | **表 2：四档 × 竞品地图**；"绝对召回 ≠ 竞争力"；曲线无交点的判据 | §4.1 + §9 | ✅ 齐 |
| §6 Diagnosis | 崩塌机制（符号面零信息 ⇒ 加权距离退化为 `|h|` 偏置）；图保真度 `L0∩cos_top64`（GIST 0.57% vs cohere 56.8%） | `t2-gist960-collapse.md` | ⚠️ 只有 4 个数据集（G-c） |
| §7 The Judge | 论文探针的三处问题（度量未指定 / 样本量敏感 / top-10 仪器偏悲观）+ **修正版判据链**（26 臂） | `t2-deployability-gate.md` | ✅ 齐 |
| §8 Repair | C1 的两步流水线 + F1 的 A/B（`sign_info` 预测收益符号）+ 代价（≲9% QPS） | `f1-metric-consistency.md` | ✅ 齐 |
| §9 Discussion | 何时该用/不该用 BQ-native 索引的**决策表**；与 RaBitQ/PQ/OPQ 的关系（为何我们不引旋转/训练） | — | ⚠️ 待写 |
| §10 Limitations | 见 §5（下）**全部逐条写进正文，不放在附录** | — | ✅ 素材齐 |
| §11 Artifacts | 脚本/数据/复现命令 + 上游 issue/PR 链接 | — | ⚠️ 待写 |

**图**：① 四档 × 竞品曲线（含交点标注）；② `sign_info` vs 修复增益的散点（7/7 + 无操作对照）；
③ 流水线前后对比（GIST/SIFT/GloVe 三档）；④ 探针的样本量/查询子集敏感性。

---

## 4. 必须在正文声明的限制（写作时逐条落位）

| # | 限制 | 落位 |
|---|---|---|
| L1 | **单机、无 AVX-512**（本机 `Avx512F=False`）⇒ 绝对 QPS 不可与论文（Zen4+）对比，4.6–5.0× 是**本机口径**且倍差对 SIMD 敏感（QuIVer 吃 VPOPCNTDQ，HNSW 不吃） | §3 与 §4 |
| L2 | **协议差异**：GIST/SIFT 在 ann-benchmarks 是 euclidean，我们归一化后按 cosine 重算 GT ⇒ 不可与公开 GIST/SIFT 数字对比 | §3 与 §4 |
| L3 | **去均值改变了相似度定义**：C1 的 Δ 是"centered-cosine 任务上的召回"与"原任务召回"之差，**不是同一任务的提升**；centered 度量是 NLP 文献里已知的后处理（All-but-the-Top 系） | §8 开头 |
| L4 | **可分性口径 ~5% 不确定度**（`cos_std` 系统性偏 1.8–1.9%） | §6 |
| L5 | **`redcaps-512` 不可复现**（三条证据）；论文该行用什么源不可考 | §4 |
| L6 | **`wolt_clip` 有并列地板**（`faiss_exact` 90.09%）⇒ 该集召回不可横比，且"曲线相交"部分由并列造成 | §5 |
| L7 | 图保真度只测了 4 个数据集（G-c）；探针的 K 与极差须随数字一起给 | §6、§7 |
| L8 | 我们自己的两次"单一预测器"尝试**都已证伪**（可分性、SNR），最终判据是"分诊 + 必要条件"而非充分性承诺 | §7（作为方法学诚实的证据） |

---

## 5. 与论文作者互动的两条线（并行）

| 线 | 内容 | 状态 |
|---|---|---|
| **上游 issue/PR** | 4 条：① 建图/查询度量不一致（含我们的 A/B 与 `TRIVIUM_NAV_WEIGHTED` 开关）；② `α=1.2` 落在平台最差端；③ README 的 Table/Figure 编号错；④ `prepare_all.py` 的 `binary_vector` 对 wolt_clip 报 `TypeError` | 素材齐，**可直接写** |
| **论文内引用** | 若上游接受 PR，论文可写"已上游化"；若不接受，如实写"我们建议 X，作者可自行决定" | — |

---

## 6. 缺口（按重要性）

| # | 缺口 | 成本 | 是否阻塞动笔 |
|---|---|---|---|
| ~~G-c~~ | ✅ **已完成（2026-09-20）**：图保真度 **9 个数据集**（`audit-and-direction.md` §11.1） | — | — |
| **G-e** | 第二台 **AVX-512** 机器复测倍差 | 外部依赖 | ❌ 不阻塞（写清为限制） |
| G-h | §9 的"决策表"与相关工作（RaBitQ/PQ/OPQ/All-but-the-Top） | 0.5 天 | ❌ |
| ~~G-i~~ | ✅ **已完成**：关键点 3 次独立建图，极差 ≤0.27pp（§11.2） | — | — |
| ~~G-a~~ | ~~剩余 5 行数据集~~ | — | ✅ 已完成（12/12） |
| ~~G-b~~ | ~~修复臂竞品曲线~~ | — | ✅ 已完成（D2/U18/U19） |
| ~~G-d~~ | ~~F1 补丁 + 代价~~ | — | ✅ 已完成（默认关闭开关 + ≲9%） |

---

## 7. 写作顺序与 venue 策略

**建议顺序**（先写证据最强、最不依赖未做实验的部分）：
1. **§4 Reproduction**（表 1 已定稿）→ 2. **§5 Boundary**（表 2 已定稿）→ 3. **§7 The Judge** →
4. **§8 Repair** → 5. **§2/§3**（背景与方法，边写边冻结口径）→ 6. **§1/§9/§10**（最后写，全局清醒后收口）。

**venue 分层（沿用 `audit-and-direction.md` §7.3）**
- **Tier A0（现在就能做）**：上游 issue/PR（4 条）+ arXiv 技术报告。**无风险、有实用价值**。
- **Tier A1**：复现/评测类 venue（PVLDB 的 reproducibility 系列、SIGMOD 的 reproducibility、或 ANN 相关 workshop）。
  需要 G-c 补齐 + G-i 的重复实验。
- **Tier C（不建议现在启动）**：新估计器/新量化器 —— 与 RaBitQ 理论同源，且 T1 已实测失效。

**停止条件（未变）**：① G-e 拿不到 AVX-512 ⇒ 全篇按 single-platform 口径，**不再等**；
② 累计超过 2 周仍未完成 G-c/G-i ⇒ 只发 arXiv 技术报告 + 上游 PR；③ 若审稿人质疑"评估类工作缺少新方法"，
则把 C1 提升为主贡献并补 §8 的端到端加速表（届时需要竞品曲线在流水线臂上重跑）。

---

## 8. 写作时的三条纪律

1. **每个数字都标注 K / 重复次数 / 单次采样**（L7）；探针值必须带极差。
2. **"绝对召回 ≠ 竞争力"这条要在 §1 就立起来** —— 否则后面所有关于档位的讨论都会被误读。
3. **不主张"论文错"**：论文的机制描述（Finding 1）与我们是**一致**的；我们的增量是**修复、竞争力边界、判据完备性**。
   措辞用"论文未涉及/未指定"，不用"论文错误"。

# 上游交付材料（可直接粘贴的 issue / patch）

> **日期**：2026-09-22 ｜ **语气**：不挑刺、只补规格（论文的机制我们复现并同意）
> **背景数据**：全部来自本仓 `results/**` 与 `.tmp/*.log`，可复算
> **patch**：`patches/f1-nav-weighted.patch`（**默认关闭 ⇒ 行为逐位不变**）

---

## Issue 1 —— RedCaps-1M 的采样协议（唯一"数字对不上"的一行）

我们下载并校验了 §1c 指向的 Zenodo 13137120（22.12 GiB，MD5 一致）。
论文 Table 4 已经定下 **base = 1,000,000 / queries = 10,000 / Cosine**，所以问题只剩两点：

1. **1M 取哪一部分**：文件序前 1M → **69.66%**；随机 1M（seed 7 / 2026 / 42）→ **73.94 / 75.27 / 76.02%**。
2. **查询本身落在基底内时是否排除自匹配**：`random_test` 与 `train` 同池，约 **9.7%** 的查询命中自身；
   不排除 → **77.08%**（这是我们能得到的最高值）。

附带：该文件没有 `neighbors`，我们按"在选中的 1M 内重算 GT"处理 —— 只需确认这也是你们的做法。

**同一份产物在这四种读法下差 7.4pp**（69.66 ~ 77.08）。我们暂时按"随机 1M + `random_test` + 不排除自匹配"
报 **77.08%**（论文 Table 11 为 **78.41%**，最接近的读法仍差 **1.33pp**）。
⇒ 这一行是我们 12/12 里唯一没有完全复现的一行；请给规则，我们照着重跑并如实写。

---

## Issue 2 —— 查询 L0 导航用的度量与建图/剪枝**不是同一个**

**事实**：建图 / 剪枝 / 上层用的是 `distance_to_sig`（2-bit 的 **6 类加权**），
而**查询 L0 束搜**用 `distance_to_sig_cheap`（**纯 Hamming**）。共 **3 处**导航点：
`quiver.rs` 1272–1281（主路径）、1343–1346（dual/信号路径）、1513–1518（384 维 scratch 路径）。

**A/B 实测**（同二进制、`TRIVIUM_NAV_WEIGHTED` 开关、默认关闭；6 个数据集，`ef_s=64..1024`）：

| 数据集 | `sign_info` | ΔR@10@ef_s=64 | ΔR@10@ef_s=1024 | QPS 代价 |
|---|---|---|---|---|
| glove100-100 | 0.747 | **+21.8pp** | +21.6pp | −4.9% |
| gauss960-960 | 1.000 | **2.9×**（0.83→2.44%） | 4.6× | −9.3% |
| wolt_clip-512 | 0.747 | +0.9pp | +2.5pp | −6.1% |
| cohere-768 | 0.863 | +0.5pp | +0.2pp | −6.9% |
| sift128-128 | **0.000** | **−13.4pp** | −10.8pp | −5.7% |
| gist960-960 | **0.000** | −1.3pp | −1.2pp | −3.6% |

**规律（完美分离）**：`sign_info`（逐坐标符号熵的均值）≥ 0.75 ⇒ **全部受益**；= 0.000 ⇒ **全部受损**。
机制：符号平面若还有信息，加权度量利用幅度平面 ⇒ 更准；符号平面已退化时，加权把"幅度噪声"也带进导航。

**patch 说明**：`patches/f1-nav-weighted.patch` = `src/` 三处导航点 + `TsngNavigationScorer::max_bq_distance`
的截断上界（`2·dim → 4·dim`，因为加权距离上界是 `4·dim`，不改会让所有距离饱和）。
**开关默认关闭 ⇒ 未开时行为逐位不变**（我们用冻结值做了回归守卫：cohere 97.52 / gist960 2.79 / glove100 45.60 全部复现）。

**我们想确认的**：这是**刻意的设计**（例如用廉价度量换 QPS），还是**注释与实际不一致**？

**补充（核对论文后，两种可能的结论要分开写）**：论文 §3.2 说「Vamana's α-diversity pruning directly on
2-bit BQ **symmetric distances**」、§3.3 说「Beam search traverses the graph using **symmetric BQ distances
(XOR + Popcount)**」—— 读起来是**同一族**度量。而实现里：建图/剪枝 = `distance_to_sig`（6 类加权，
多次 popcount 组合），L0 查询 = `distance_to_sig_cheap`（纯 Hamming，两次 popcount）。
⇒ 若是**实现偏离论文口径**，那是一个可修的偏差；若你们本来就想用两种，那 §3.2/§3.3 的措辞值得更明确。
如果是刻意的，我们会在论文里按"设计选择 + 数据依赖的 trade-off"写，
并把 `sign_info` 作为"该不该打开"的判据（这正是 Issue 3 里判据链的一环）。

---

## Issue 3 —— Practical compatibility test 缺少三条规格

§6 的探针没有写明：**用哪个 BQ 度量**、**样本从哪来/多少个**、**用哪个仪器**。这不是文字问题，有实测后果：

| 观测 | 数字 |
|---|---|
| 按**全文默认的加权口径**实现探针 | **Random-Sphere**（该集实测 `R@10@ef=64` = **0.91%**）上得 **53.9% > 50% ⇒ 判"兼容"** ❌ 假阳性 |
| 改用 **`min(weighted, cheap)`** | **4.7%** ⇒ 正确警告 ✅（其它行的裁决不变） |
| 样本量敏感 | 探针值随样本量最大变化 **6.8×**，方向是"**样本越少越乐观**" |
| 查询子集敏感 | 不同查询子集间极差 **4–7pp** |
| 仪器选择 | 用"码 **top-10**"会把**可用档**误判；改用"码 **top-ef → f32 精排**"才与图召回可比（glove100：67.79% ↔ 实测 71.69%，ρ=+0.95） |

**建议写进 §6**：① 用哪个度量（建议**双度量取弱**）；② 样本量及其依据（"约 10K"的来源）+ 建议多次取均值；
③ 仪器定义（"码 top-ef → f32 精排"）——否则同一数据集换个度量/样本量就能在 go / no-go 之间翻转。

---

## Issue 4 —— 两处默认值 + 文档修正（一行一条）

1. **`QuIVerConfig::default().m = 16`**，而论文全部实验是 **m = 32** ⇒ 直接用库默认值的使用者跑在**另一个工作点**，建议 README 点一句。
2. **`alpha` 默认 1.2 恰在平台最差端**：我们的扫描 α ≥ 1.05 完全平台；**α = 1.0 在 cohere +1.02pp、SIFT +5.02pp**（代价：建图 +14~22%）。
   另：论文 Table 9 记的建图代价是 α=1.0 **225s** vs α=1.2 **93s**（**2.4×**），与我们测到的 **+14~22%** 不一致 —— 想确认哪个数对（可能是机器/构建差异）。
   机制侧面：像 `vamana_select` 的补足路径（`quiver.rs:1656-1668`）—— α 越小 ⇒ 通过 `d(v,w) < α·d(u,v)` 的候选越少 ⇒ 补足触发越频繁 ⇒ 边长更短。
3. **README 的编号**：`README_QUIVER.md` 写的 "§5.6 Table 10 & Figure 4" 实际是 **Table 11 / Figure 3**（Table 10 是编码消融）。
4. **"zero preprocessing" 的措辞建议**：机制上这是**最大的适用性前提**。建议写明"若符号平面退化（如 GIST/SIFT 的窄正区间），**一步去均值**是可选的修复"
   —— 我们在 6 个数据集上量了（GIST `2.10 → 39.74%`、SIFT `15.77 → 30.64%`、WOLT-CLIP `71.48 → 76.81%`、
   GloVe `32.82 → 36.11%`、cohere `94.63 → 93.48%`（中性）、各向同性对照 `+0.03pp`），且**去均值后 HNSW 几乎不变**（排除"centered 任务对所有人都更容易"）。

---

## Issue 5 —— 与你们"不做旋转"的设计选择对话：**种子随机旋转**让崩塌档恢复 44–58pp（且不改任务）

**先说我们读到的**：论文把"不旋转、不预处理"当作**明确的设计选择** ——
Abstract：「no codebook or **rotation training** (unlike PQ/OPQ/RaBitQ)」；§1：「no codebook training or
**rotation preprocessing** is required」；§7：「QuIVer uses a simple per-vector mean threshold with **zero preprocessing**」。
而且**仓库里你们已经做过** no-rotation vs rotation 的对比（`README_QUIVER.md`：
「**BQ2 (2-bit SM)**: Our approach, **no rotation**, weighted Hamming」 vs
「**RaBitQ-sym**: 4-round **FHT-Kac rotation** + 1-bit sign + Hamming」，见 `benches/bench_rbq2_precision.rs`）。

⇒ 所以这一条**不是"遗漏"**，而是：把你们那个对比**按数据分档**看之后的一个实测结论 ——
**在崩塌档上旋转是纯赚，在竞争档上是净亏**。这也是我们这边最强的一个实测结果：

对一个**固定种子**做 QR 分解得到的随机正交阵 `Q`（⇒ **零存储**，dim+seed 足够重建；无需训练）：

| 数据集 | 原始 @ef=64 | 去均值 @ef=64 | **旋转 @ef=64** | 原始 @ef=1024 | **旋转 @ef=1024** |
|---|---|---|---|---|---|
| GIST-960 | 2.10% | 39.74% | **60.22%** | 4.38% | **88.99%** |
| SIFT-128 | 15.77% | 30.64% | **60.24%** | 47.23% | **95.74%** |

**为什么它比"去均值"干净**：对单位向量 `cos(Qa, Qb) = cos(a, b)` ⇒ **相似度与 GT 都不变**
（我们实测旋转后 GT ∩ 原 GT = **99.87–100%**），变的只有**编码**（负值占比 ~0.49 ⇒ 符号面复活）。
⇒ 你们的 "zero preprocessing" 只需放宽为 "one seeded rotation"，**不需要改任务定义**；
而且这本来就是 RaBitQ 一系的标准做法。

**代价/边界（如实）**：① 竞争档（Cohere）上旋转**有害**（`94.63 → 89.82%` @ef=64，−4.8pp），
所以判据要跟上（符号面活着就别旋转）；② 旋转会**摊平幅度面** ⇒ 旋转后要配"该用哪个导航度量"的规则
（见 Issue 2：用 `probe_ef(加权) vs probe_ef(Hamming)` 谁大选谁，我们在 10 个臂上 9 个方向正确）；
③ 建图反而**变快** 2–6×（GIST 290s→47s、Cohere 202s→31s）。

**竞品后果**（因为任务没变，你们的 Table 11 场景下原有竞品曲线仍然有效）：
GIST-960 在 84% 召回处 QuIVer **快 hnswlib 1.32×**（84.41% @7,148 vs 84.11% @5,417），
而 60–84% 召回带里 HNSW 根本没有工作点（它最低 ef=64 就已经 84.11%）。

---

## Issue 6 —— ~~Table 4 的 "Euclidean" 标签~~ ❌ **已自我撤回（核对 §5.1 后）**

我们原本打算提这一条（Table 4 把 SIFT/GIST 标为 **Euclidean**，而 `prepare_all.py` 是"归一化 + 按 cosine 重算 GT"），
但**论文 §5.1 已经写明**：

> "SIFT-128 and GIST-960 are Euclidean CV descriptors (**L2-normalized, ground truth recomputed under cosine**)"
> "all baselines use inner-product (IP) mode on L2-normalized vectors, matching cosine similarity"

⇒ 我们的实测（12 行全部落在 ±1.84pp 内：gist960 `2.10 vs 2.01`、sift128 `15.77 vs 14.85`）**与论文口径一致，没有问题**。
**只剩一个可选的小建议**：Table 4 的 metric 列单看仍是 "Euclidean"，建议加个脚注指向 §5.1，
免得只读表的读者把它当 Euclidean 任务去比公开榜单。

---

## Issue 7 —— `prepare_all.py` 的 `binary_vector` 分支对 `wolt_clip` 报 `TypeError`

该分支假设向量是 **JSON 字符串**，而 `wolt_clip` 当前 revision 直接给 `list` ⇒
`TypeError: the JSON object must be str, bytes or bytearray, not list`。
我们做了最小容错（`isinstance(emb, (str, bytes, bytearray))` 判断）：
```python
if is_binary:
    import json
    if isinstance(emb, (str, bytes, bytearray)):
        emb = json.loads(emb)
    all_emb[count] = np.array(emb, dtype=np.float32)
```

# P8 队列报告（收官）—— 十步结果、cohere 口径陷阱与数字撤换

> **日期**：2026-10-09 ｜ **数据**：`.tmp/p8_queue.log`、`results/t2/p8_queue_summary.json`、分步日志 `.tmp/p8_*.log`
> **论文对应**：§5.6(a)(b)(c)、§6.4(ii)、§8.6、§10（L6/L14/L16）、§11.6 ｜ **交接文档**：`handoff-next-session.md` §1–§5

---

## 0. 一句话

十步中前九步 `exit=0`，**第 10 步首跑失败、用绝对路径重试成功**（根因见 §4-D5）。最大的发现不在队列设计里：
**cohere 的 shipped GT 是 cosine 口径，而磁盘上的 f32 文件是原始未归一化向量**——此前"精确 IVF-Flat 34.9 %
反而低于 RaBitQ+Refine 59.75 %"的伪矛盾、以及研究文档里"召回被候选池锁死在 ~60 %"的读法，**全部由此而来**。
归一化修正后，同族对照完全符合理论（RaBitQ+Refine ≤ 精确控制臂、随 `k_factor` 单调、全表 100 %）。
相关数字已在论文中撤换/替换（§5.6(b) 新写、§10-L16 新增），旧的 raw 口径产物保留为这一陷阱的证据链。

---

## 1. 十步结果总表

| 步 | 实验 | 状态 | 耗时 | 产物 | 关键数字 |
|---|---|---|---|---|---|
| 1 | IVF-Flat vs RaBitQ 召回诊断 | ✅ | 2.7 min | `results/t2/ivf_recall_diagnostic_cohere.json` | nprobe 生效（23.33→34.94 %）；`ParameterSpace` nprobe **穿透** base ✓；`k_factor` 经 ParameterSpace **不可设**（被旧脚本 `except: pass` 吞掉）；全表（nprobe=1024）**34.84 %** |
| 2 | RaBitQ+Refine 修正版（cohere，raw） | ✅ | 3.2 min | `results/t2/rabitq_refine_cohere.json` | k=20 → 36.58 %；k=200 → **35.08 %**（k 越大越低——此时已可判定口径有问题）；eff_* 字段已记录 |
| 3 | IVF-Flat 控制臂（cohere，raw） | ✅ | 8.2 min | `results/t2/ivfflat_control_cohere.json` | 64/256/512/1024 → 34.94/34.88/34.84/34.84 %（**饱和**） |
| 4 | RaBitQ 在 gist960c 跑一格 | ✅ | 0.9 min | `results/t2/rabitq_refine_gist960c.json` | k=200：nprobe64 → **95.38 %**、nprobe256 → **95.76 %**（gist960c 已归一化，无陷阱）|
| 5/6 | PQ 跨档位 sift128c | ✅ | 23.2 min | `.tmp/p7_pq_sift128c.log` + `results/t2/pq_matched_recall_sift128c.json` | PQ 最高 **99.94 % @ 2,151**；99.54 % @ 7,901；exact 100 %（无 tie） |
| 7/8 | 同召回对照 sift128c | ✅ | 0.0 min | `results/t2/pq_matched_recall_sift128c.json` | QuIVer 峰值 84.57 %（@ef=1024）**进不了任何 ≥99 % 档**；hnswlib 99.90 % @ 29,841 |
| 5/6 | PQ 跨档位 wolt_clipc | ✅ | 10.0 min | `.tmp/p7_pq_wolt_clipc.log` + `results/t2/pq_matched_recall_wolt_clipc.json` | PQ 最高 **89.66 % @ 3,809**；exact scan 只有 **96.1 %**（tie 地板）|
| 7/8 | 同召回对照 wolt_clipc | ✅ | 0.0 min | `results/t2/pq_matched_recall_wolt_clipc.json` | 全体（PQ 89.66 / hnswlib 90.07 / FAISS-HNSW 89.68 / USearch 89.74 / IVF-Flat 89.94）≈ tie 地板；QuIVer 89.05 % @ 9,788 |
| 9 | gauss960 竞品曲线 | ✅ | 60.0 min | `results/baseline/competitors_gauss960.json` | **全部崩塌**：hnswlib 1.10 %、FAISS-HNSW 1.30 %、USearch 1.39 %、IVF-Flat 2.41 %（@ef=64；@1024 亦仅 15.15/16.26/15.01/18.67）——"索引无关崩塌"第二个证人 |
| 10 | 引擎侧旋转复现 rc 臂 | ❌→✅ | 0.0 → ≈10 min（重试） | `.tmp/p8_10_engine_rc.log` / `.err` | 重试（`TRIVIUM_SIGN_ROTATE=20260923`+`TRIVIUM_NAV_WEIGHTED=1`，gist960c）：**80.12 % @ef=64 / 97.13 % @ef=1024** vs 数据侧 rc 臂 80.17 / 97.53（≤0.4 pp）|

队列整体：**10:51:32 → 12:39:50 ≈ 108 min**（交接文档预估 90–100 min；超出的主因是步骤 9 的 USearch 建图
2,143.7 s）。步骤 7/8 耗时 0.0 min 属正常——它们是**读日志的分析步**，不是实跑。

---

## 2. cohere 伪矛盾诊断链（步骤 1–3 + 三个探针，结论链闭合）

### 2.1 假设 A"RaBitQ 参数从未生效"——部分成立、但不是根因

* `ParameterSpace().set_index_parameter(wrapper, "nprobe", 256)` **会穿透**到 `base_index`（诊断产物
  `paramspace_reaches_base: true`，`base.nprobe = 256`）⇒ nprobe 一直有效。
* 真正失效的是 **`k_factor`**：faiss 1.15 经 ParameterSpace 设置报
  `could not set parameter k_factor`，而**旧脚本把这个异常 `except: pass` 吞了**，于是 k_factor 一直是默认
  **1.0**——这解释了 09-24 旧产物里"四个 k 值召回完全相同（59.75 %）"的怪象。
* 修正版改成**直接赋值** `base.nprobe` / `refine.k_factor`，并把生效值写进产物（`eff_nprobe`/`eff_k_factor`）。

### 2.2 假设 B"IVF-Flat 侧 k-means 退化"——不成立

nprobe=1024（**扫全表**）仍只有 34.84 %。若 GT 是原始向量的精确 top-10，全表精确搜索必须命中 GT
（100 %）——**不是分区问题，是 GT 本身对不上**。

### 2.3 合成机制探针（`faiss_refine_mechanics_probe.py` → `results/t2/faiss_refine_mechanics_probe.json`）

在自洽 GT 的合成数据上：`refine_index` 度量 = IP（与 base 同）；默认 `k_factor = 1.0`；k_factor 越大召回
**单调上升**（19.25 → 44.45 → 46.05 %@nprobe=8），且 k=200 时 RaBitQ+Refine **恰好等于**同 nprobe 的
IVF-Flat 精确控制臂（46.05 % = 46.05 %）。⇒ **FAISS 行为符合理论，cohere 的"反转"不是库缺陷。**

### 2.4 GT 口径探针（smoking gun；`gt_metric_consistency_probe.py` → `results/t2/gt_metric_consistency_cohere.json`）

numpy 精确搜索逐查询核对（6 条均匀采样）：

| 口径 | 与 shipped GT 的 top-10 重合 |
|---|---|
| 原始向量 + IP | **4.2 / 10** |
| 原始向量 + L2 | 9.2 / 10 |
| **归一化向量 + IP（=cosine）** | **10.0 / 10** |

且 cohere train/test 的范数 ≈ **13.8**（未归一化）——`dim_axis_separability.py` 的注释早就记录了
"cohere 的文件在磁盘上是原始未归一化"，本步只是第一次把它与同族对照的失真联系起来。
⇒ **GT = cosine，文件 = raw。任何不做归一化的臂都在对着错误的目标打分**，而且失败方向取决于候选池大小：
小池（k=1）跟随 RaBitQ 码的方向性估计（碰巧更贴 cosine →"60 %"），大池让 f32 精排把结果拉回 raw-IP 排序
（→ 35 %，趋近"全表 34.8 %"）。伪矛盾的"60 % > 34.9 %"就此完全解剖。

### 2.5 修正后的同族对照（归一化；机器空闲、32 线程、同 GT）

产物：`results/t2/ivfflat_control_norm_cohere.json`、`results/t2/rabitq_refine_norm_cohere.json`

| 臂 | nprobe=64 | 256 | 512 | 1024 |
|---|---|---|---|---|
| IVF-Flat（精确粗排，上界） | 97.38 % @ 279 | 99.82 % @ 72 | 99.98 % @ 37 | **100.00 %** @ 21 |
| RaBitQ+Refine, k=200 | 97.38 % @ 2,885 | 99.82 % @ 1,087 | 99.98 % @ 611 | 100.00 % @ 360 |
| RaBitQ+Refine, k=20 | 97.37 % @ 4,364 | 99.79 % @ 1,268 | 99.95 % @ 673 | 99.97 % @ 380 |
| RaBitQ+Refine, k=1（默认） | 78.03 % @ 4,656 | 78.88 % @ 1,272 | 78.90 % @ 673 | 78.91 % @ 369 |

理论排序恢复：**逐 nprobe，候选池臂 ≤ 精确臂（k 足够时取等）**；k_factor 单调；全表 100 %。

### 2.6 撤换清单

* **撤下**（raw 口径、不得引用）：59.75 % / 60.2 % / 60.23 %（旧"RaBitQ 天花板"）、34.9 %（旧"IVF-Flat 对照"）。
* **替换为**：上表 `*_norm_*` 产物（200 % 修正对）。旧产物保留在 `results/t2/` 作为陷阱证据，**文件名与论文
  标注都已区分**（raw 对 vs `_norm` 对）。
* 附带口径事实：默认 `k_factor = 1` 在同等 QPS 附近比调优点低 ~19 pp ⇒ "同族基线"必须记录**生效参数**。

---

## 3. 其余要点

* **步骤 4（gist960c 上的同族 RaBitQ）**：k=200 → 95.4–95.8 %，而 QuIVer 的 2-bit 码在该数据上 39.87 %
  （@ef=64）——同族量化器不崩，**"崩塌是 2-bit SM 码特有"再添一个数据点**（论文 §5.6/§6.4）。
* **步骤 5–8（PQ 跨档位 + 同召回）**：sift128c 上 PQ 99.94 % 而 QuIVer 峰值 84.57 %；wolt_clipc 上全体
  被 tie 地板压平（exact 96.1 %，各家 ≈90 %，PQ +0.6 pp）。两格都补进 §5.6(a)/§8.7 表。
* **步骤 9（gauss960 第二证人）**：三种 HNSW 实现 + IVF-Flat 全部在 1.1–2.4 %（@ef=64）——§6.4(ii)
  "任务不可分辨"从 Random-Sphere 单例升级为**四个实现的共同结论**。
* **步骤 10（引擎侧 rc 复现）**：两个开关同时打开时，引擎侧（自产旋转矩阵）与数据侧 rc 臂在 0.4 pp 内一致
  ——§8.6 的"收益来自旋转这件事本身，而非某个特定矩阵"再次成立。

---

## 4. 与交接文档 / 既有材料的差异与处理方式

| # | 差异 | 处理 |
|---|---|---|
| **D1** | 交接文档 §4 的两个假设（RaBitQ 侧参数未生效 / IVF-Flat 侧退化）**都不成立**；真实根因是 GT 口径错配 | 论文 **§5.6(b) 改写**为"同族对照 + 归一化陷阱"，数字撤换（§2.6）；新增 **§10-L16** 把"GT/度量对齐必须逐数据集验证"列为限制项；本报告为审计轨迹 |
| **D2** | `p7-quantizer-baselines.md` §2h 的"召回被候选池锁死"读法**作废** | 在该节就地加"P8 修正"标注（保留原文，审计文化：结论撤换不删档） |
| **D3** | 交接文档预估 90–100 min vs 实际 **≈108 min**（另步骤 10 重试 ≈10 min） | 记录于本报告 §1；主因步骤 9 的 USearch 建图 2,143.7 s |
| **D4** | `p8_queue_summary.json` 的 `started` = 12:39:48（**末次写入时刻**），与 `.tmp/p8_queue.log` 的 10:51:32 不符 | `p8_queue.py` 已修（started 固定为真实开始时刻）；本产物已人工更正并在 JSON 内加 `started_note` 说明 |
| **D5** | 步骤 10 首跑 `FileNotFoundError`（0.0 min 即失败） | 根因：**Windows `CreateProcess` 用父进程 PATH 解析裸命令名**，`subprocess` 的 `env=` 里加 PATH **不参与可执行文件查找** ⇒ 裸 `"cargo"` 必找不到。`p8_queue.py` 已修（cargo 绝对路径 + 注释）；重试即成功 |
| **D6** | 论文 §5.6(a) 引用**不存在的 §10.5** | 已改为 §10.3/L14 |
| **D7** | §3.5 与 §4.2 的旧噪声地板（≤0.27 pp、Cohere 0.13…）与 §10.3/L7、§10.4 的新值（≤0.25 pp）**自相矛盾** | 两处均已同步为 **≤0.25 pp**（GIST 0.22 / SIFT 0.25 / GloVe 0.10 / Wolt 0.19 / Cohere 0.16；@1024 ≤0.27），来源 `p7_stagec_report.json` |
| **D8** | §11.6 引用的 `results/t2/pq_tier_jump_*.json` **实际不存在**（脚本不产该文件） | §11.6 改为实际产物：`.tmp/p7_pq_*.log` + `results/t2/pq_matched_recall_{sift128c,wolt_clipc}.json` |
| **D9** | 步骤 7/8 耗时 0.0 min，看似"跳步" | 非缺陷：`pq_matched_recall.py` 是读日志的分析脚本；记录说明即可 |

---

## 5. 产物与脚本清单（本次新增）

| 类别 | 文件 |
|---|---|
| 脚本 | `scripts/research/gt_metric_consistency_probe.py`、`faiss_refine_mechanics_probe.py`、`ivf_recall_diagnostic.py`、`bench_rabitq_refine.py`（+`RA_NORMALIZE`）、`baseline_competitors.py`（+`BL_SKIP`）、`p8_queue.py`（cargo 绝对路径 + started 修复）、`p8_collect_numbers.py`、`p7_stagec_report.py`、`p7_k5_vs_k3.py` |
| 产物（记录用） | `ivf_recall_diagnostic_cohere.json`、`ivfflat_control_norm_cohere.json`、`rabitq_refine_norm_cohere.json`、`rabitq_refine_gist960c.json`、`gt_metric_consistency_cohere.json`、`faiss_refine_mechanics_probe.json`、`pq_matched_recall_{sift128c,wolt_clipc}.json`、`results/baseline/competitors_gauss960.json`、`results/t2/gist960_collapse/gist960rc.json` |
| 产物（陷阱证据，保留不计入引用） | `ivfflat_control_cohere.json`、`rabitq_refine_cohere.json`（raw 口径） |
| 日志 | `.tmp/p8_*.log`、`.tmp/p7_pq_{sift128c,wolt_clipc}.log`、`.tmp/p8_10_engine_rc.{log,err}`、`.tmp/p8_numbers.log` |

**注**：`.tmp/**` 不入库（仓库惯例）；可引用的数字均在 `results/**`。

# 会话交接：新窗口从这里开始

> **交接时间**：2026-10-09 ｜ **上一会话**：Phase 3 收尾 → Phase 4/5/6/7 → Phase 8 队列启动
> **目的**：换窗口后**不需要重新读长历史**，读这一页即可接手。

---

## 0. 一句话状态

论文 **§0–§11 已成稿**，并且**已把 P4–P7 的新结论整合进正文**（三种失败、位预算天花板、量化类对照、
前瞻验证 6/6、VIBE 外延）。**唯一在跑的是 P8 队列**（最后 10 步实验，无人值守）。跑完后只剩三件
**零机时**的事：**§12 参考文献 → §0/§1/§3.5 同步 → 提交**。之后即可挂 arXiv 预印本。

---

## 1. 正在跑什么、怎么看进度

| 项 | 位置 |
|---|---|
| 队列脚本 | `scripts/research/p8_queue.py` |
| 总日志（含每步开始/结束/耗时） | `.tmp/p8_queue.log` |
| 分步日志 | `.tmp/p8_*.log`（另：PQ 两步写 `.tmp/p7_pq_<prefix>.log`） |
| 汇总产物（每步 ok + 分钟数） | `results/t2/p8_queue_summary.json` |

复制即用的进度自检（PowerShell）：

```powershell
Get-Content .tmp\p8_queue.log -Tail 25
Get-Content results\t2\p8_queue_summary.json
Get-Process python | Where-Object { $_.CPU -gt 60 } | Select-Object Id, CPU
```

预计总时长 **约 90–100 分钟**（10 步，顺序执行；任何一步失败会记录并继续）。

---

## 2. 队列十步各干什么（对应论文哪一节）

| 步 | 实验 | 对应章节 | 预期耗时 |
|---|---|---|---|
| 1 | IVF-Flat vs RaBitQ **召回诊断**（nprobe 是否生效、`ParameterSpace` 是否穿透 wrapper） | 决定 §5.6(b) 写法 | ~5 min |
| 2 | RaBitQ+Refine **修正版**（改为直接赋 `base.nprobe` / `refine.k_factor`，并记录生效值） | §5.6(b) | ~15 min |
| 3 | IVF-Flat 控制臂（同 nprobe 网格） | §5.6(b) | ~8 min |
| 4 | RaBitQ 在 `gist960c` 上跑一格 | §5.6(b) / §6.4 类型③ | ~6 min |
| 5–6 | PQ 跨档位补两格：`sift128c`、`wolt_clipc` | §5.6(a) / §8.7 | ~15 min ×2 |
| 7–8 | 同召回对照重算（含新两格） | §5.6(a) | ~1 min ×2 |
| 9 | `gauss960` 竞品曲线（给"索引无关崩塌"补第二个证人） | §6.4 类型② | ~25 min |
| 10 | 引擎侧旋转（`TRIVIUM_SIGN_ROTATE`）在 `gist960c` 上复现 `rc` 臂 | §8.6 | ~5 min |

---

## 3. 跑完后要做的三件事（全部 0 机时）

1. ~~**§12 参考文献**~~ ✅ **已完成**（`docs/paper/section-12-references.md`）：上游论文 **arXiv:2605.02171**
   "QuIVer: Rethinking ANN Graph Topology via Training-Free Binary Quantization"、HNSW/hnswlib/FAISS/USearch/
   IVF/PQ/OPQ/RaBitQ/DiskANN-Vamana/VIBE/all-but-the-top 全部列出（标 *[verify]* 的待核对版本），
   并含 **artifact 与许可声明**（仓库 **Apache-2.0**；逐目录标出"哪些是上游、哪些是我们的改动"）
   与 pandoc 组装命令。⚠️ 提交前仍需：把 §12 折成 BibTeX、补作者/致谢、图按栏宽重渲染。
2. **口径同步三处**：§0 摘要（补"三种失败/位预算/PQ 对照"）、§1 引言（发现清单）、§3.5 噪声下限
   （多种子极差 **≤0.25 pp**，5 集 × 3 次建图，产物 `results/t2/p7_stagec_report.json`）。
3. **提交**（见 §5 未提交清单），然后 Phase 8 报告。

---

## 4. ⚠️ 一个**未解决的自相矛盾**（新会话务必先看这条）

控制臂已测到：**精确粗排 IVF-Flat 在同 nprobe 下召回 ~34.9 %（nprobe=64/128/256 几乎不变）**，
而 `IndexIVFRaBitQ + IndexRefineFlat` 是 **59.75 %**。这在理论上**不可能**（RaBitQ+Refine 只在
"码排序的 top-(k_factor×k)" 里精排，IVF-Flat 对探测到的每个向量都精确比较 ⇒ IVF-Flat 必须是上界）。

⇒ 两侧必有一侧错。**队列第 1 步就是判定它**：

* 若 **RaBitQ 侧**参数从未生效（`set_index_parameter` 不穿透 wrapper）⇒ 之前那个 60.2 % 要**撤下**，
  §5.6(b) 改写成"受 IVF 分区限制、且同族参考"；
* 若 **IVF-Flat 侧**有错（如 k-means 在 cohere 上退化 ⇒ nprobe 扫到 25 % 数据也找不齐真邻）⇒ 用诊断
  给出的正确曲线替换。

**在诊断出结论之前，不要把这几个数字写进论文。** §5.6(a) 的 PQ 部分是**独立的、可信的**，可以写。

---

## 5. 未提交的改动（新会话请一起提交）

| 类别 | 文件 |
|---|---|
| 论文（本会话新整合） | `docs/paper/section-5-boundary.md`（+§5.6）、`section-6-diagnosis.md`（§6.4 三种失败 + §6.5 位预算）、`section-7-judge.md`（K=5 + 前瞻 6/6）、`section-8-repair.md`（§8.6 引擎开关 + §8.7 内存三角）、`section-9-discussion.md`（+§9.5 VIBE）、`section-10-limitations.md`（L7 更新 + L13–L15）、`section-11-artifacts.md`（+§11.6） |
| 产物 | `results/baseline/competitors_cohere.json`（32T 对齐版）、`results/t2/deployability_gate.json`（**K=5**） |
| 脚本 | `benches/bench_baselines.py`（PQ 网格/线程可用环境变量覆盖）、`scripts/research/make_figures_svg.py`、`scripts/research/bench_rabitq_refine.py`（修正 + 控制臂）、`scripts/research/ivf_recall_diagnostic.py`、`scripts/research/p8_queue.py`、`scripts/research/p7_stagec_report.py`、`scripts/research/p7_k5_vs_k3.py`、`scripts/research/p8_collect_numbers.py`、`scripts/research/b3_align_gate_doc.py` |
| 图 | `docs/paper/figures/fig6-bit-budget.svg` |
| 研究文档 | `docs/research/p7-quantizer-baselines.md`、`p5-engine-side-rotation.md`、`p6-external-resources.md`、`phase4-plan.md`、`phase4-report.md`、`handoff-next-session.md`（本文件） |
| **用户杂物（不要动）** | `.claude/`、`.codebuddy/`、`AGENTS.md`、`CLAUDE.md`、`audit-home.yaml`、`home2` 等 |

---

## 6. 本仓库的约定与坑（避免重犯）

1. **PowerShell 里不要写多行内联 Python**（含中文/`→`/`%` 会报"文件名、目录名或卷标语法不正确"）
   ⇒ 一律写成 `.py` 文件再执行（本会话因此浪费了好几轮）。
2. **机器满载（26–32×）时绝不测 QPS**；测出来的数全部作废。
3. **探针口径 = K=5**（产物字段 `probe_k`）；旧研究文档里的单次值已由
   `scripts/research/b3_align_gate_doc.py` 与 `p7_k5_vs_k3.py` 对齐，别再引用旧值。
4. `src/` 只接受**默认关闭、关闭时逐位不变**的开关，现有两个：
   `TRIVIUM_NAV_WEIGHTED`（导航度量，§8.3）、`TRIVIUM_SIGN_ROTATE`（旋转，§8.6）。
   引擎有**两条** vector→code 路径，加变换必须同时命中（否则 SIFT-128 从 15.77 % 掉到 0.01 %）。
5. **`.codebuddy/`、`.claude/` 是用户目录，不要删**；`.tmp/` 是日志与队列产物目录，别整体清掉。
6. 写数字前**先回查产物**（本会话 B3 审计抓到 6 类不一致，其中 2 个是我自己凭印象写的）。

---

## 7. 明确不跑（已定案，不用再问）

| 项 | 原因 |
|---|---|
| 第二台 AVX-512 机器（G-e） | 用户暂时提供不了 ⇒ **已列待做项** |
| DiskANN-Rust / VSAG 基线 | 工具链硬阻塞（无 C/C++/BLAS；`pyvsag` 是 Linux/cp310 wheel） |
| MSMARCO-5M（论文 Table 12） | 超出本研究预算 ⇒ 记为"未复现"而非"未达标" |
| Tier C 新方法（新量化器） | 本研究不做新方法，只做评估与修复 |

---

## 8. 【2026-10-09 收官补记】P8 队列已完成

* 十步：1–9 `exit=0`；第 10 步首跑因 **Windows 裸命令名解析缺陷**失败，已用绝对路径 cargo 重试成功
  （80.12 % / 97.13 %，`.tmp/p8_10_engine_rc.log`）。队列 10:51:32 → 12:39:50（≈108 min）。
* §4 的"未解决的自相矛盾"已诊断：**两侧都不是错**——是 **GT 口径错配**（cohere GT=cosine、文件=raw，
  ‖x‖≈13.8）；59.75/60.2/34.9 系列已撤下，归一化修正对为记录值（RaBitQ+Refine ≤ 精确 IVF-Flat，全表 100 %）。
* 论文收尾已做：§5.6(b) 新写、§0/§1/§3.5/§4.2 口径同步、§6.4(ii)/§8.6/§8.7/§10(L6/L14/L16)/§11.6 更新。
* 全部差异与处理方式（D1–D9）：**`docs/research/p8-queue-report.md`**。

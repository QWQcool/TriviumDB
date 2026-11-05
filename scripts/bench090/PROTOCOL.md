> **Evidence review notice:** This is the historical protocol. The accompanying [evidence README](../../results/bench-090/README.md) records corrections and unverified execution gates. The actual 1536d dataset has 990K training vectors; baseline build was performed once per configuration, while queries were repeated.
# TriviumDB 0.9.0 对外口径基准协议

这套脚手架只解决一件事：**文章和 X 帖子里出现的每一个数字，都能被"commit + 命令 + 原始 JSON"复现。**

不允许出现"我记得是 3 倍"这种数字。凡是 `summary.json` 里找不到出处的，一律不写。

---

## 一、固定不变的量（改任何一项，全部重跑并在文中复述）

| 项 | 取值 | 说明 |
|---|---|---|
| 版本 | `v0.9.0` = `7edf8ce` | 隔离工作树 `.bench090`，不动 research 分支 |
| 编译 | `cargo bench --locked --bench bench_cohere1m` | 用仓库自带 `Cargo.lock`，不手动升级依赖 |
| 线程 | 16 | `RAYON_NUM_THREADS` / `TRIVIUM_MT_THREADS` / `faiss.omp_set_num_threads` 三处一致 |
| HNSW 参数 | `M=32`, `ef_construction=128` | 与 QuIVer `m=32`（最大度 64）对齐；旧文同参 |
| K | 10 | 全部指标为 R@10 |
| ef 扫描 | 10, 20, 25, 30, 35, 40, 80, 120, 200, 400, 800 | 25–40 档用于精确卡住 90% 交叉点 |
| 查询集 | 平铺到 **2 万条**（`tile`） | 1000 条查询在 4 万 QPS 下只有 25 ms，计时窗口太短 |
| 重复 | 3 次，取中位数 | 同时保留 min/max |
| 目标召回 | R@10 = 90%，recall 轴线性插值 | **到不了就写 unreachable**，禁止外推、禁止改目标值凑数 |
| 度量 | cosine（L2 归一化后内积） | 与数据集 GT 口径一致 |
| GT | 数据集自带 `.i32` | `check` 会用精确重算对拍，要求 `gt_match = 1.0000` |

> **本机实测：i9-14900K（24C/32T）/ 64 GB / Win11。**
> 这与三篇旧文的测试机（i5-13490F / 32 GB）**不是同一台**。
> 因此：旧文里的绝对 QPS（73,197 等）与本机任何数字都不可直接相减或相除。
> 要谈"0.9.0 比 0.7.5 快/慢"，必须在本机用同一套参数把 0.7.5 也跑一遍（见 §8）。

---

## 二、四个数据集，各自在图里的位置

| key | 维度 | 规模 | 用途 |
|---|---:|---:|---|
| `cohere-1m` | 768 | 1M | 主图：LLM embedding 主流档，旧文的主战场 |
| `minilm-384` | 384 | 1M | 中维：旧文口径下与 HNSW 基本持平（0.82×），用来证明没有挑数据 |
| `dbpedia-1536` | 1536 | 1M | 最高维：内存压力最大，也是旧文优势最大档 |
| `sift128` | 128 | 1M | 边界：旧文明确落后的档，必须一起发 |

`sift128` 在 `bench_cohere1m.rs` 里没有预设名，驱动用 `cohere-1m` 作为占位 preset 再覆盖三个路径与维度；结果里的 `dataset` 以 `.meta.json` 为准。**源码没有改一行。**

---

## 三、跑法

```powershell
# 0) 生成平铺查询集（一次性；cohere/minilm 各 x20，dbpedia/sift 各 x2）
.venv\Scripts\python.exe scripts\bench090\bench090.py tile --datasets cohere-1m,minilm-384,dbpedia-1536,sift128

# 0.5) 自检（必须先过）：文件、维度、GT 对拍、依赖、工作树版本
.venv\Scripts\python.exe scripts\bench090\bench090.py check --datasets cohere-1m,minilm-384,dbpedia-1536,sift128

# 1) TriviumDB（3 次重复 = 3 次重建 + 3 次全量查询）
.venv\Scripts\python.exe scripts\bench090\bench090.py tdb `
  --datasets cohere-1m,minilm-384,dbpedia-1536,sift128 --repeats 3

# 2) 基线（建图一次，每个 ef 重复查 3 次取中位数）
.venv\Scripts\python.exe scripts\bench090\bench090.py base `
  --datasets cohere-1m,minilm-384,dbpedia-1536,sift128 `
  --engines hnswlib,faiss_hnsw --repeats 3

# 3) 汇总
.venv\Scripts\python.exe scripts\bench090\report090.py
```

冒烟（只验证管线，**结果不得引用**）：

```powershell
.venv\Scripts\python.exe scripts\bench090\bench090.py tdb  --datasets cohere-1m --train-limit 20000 --efs 10,80 --repeats 1 --tag smoke
.venv\Scripts\python.exe scripts\bench090\bench090.py base --datasets cohere-1m --train-limit 20000 --efs 10,80 --repeats 1 --tag smoke
.venv\Scripts\python.exe scripts\bench090\report090.py --tag smoke
```

`--tag` 决定结果目录：`results/bench-090/<tag>/`。正式数字只认 `official`。

---

## 四、每张图对应哪条命令

| 出图 | 数据来源 | 命令 |
|---|---|---|
| 主图：recall–QPS 曲线 | `summary.csv` 的 `recall_at_10, qps` 两列，按 engine 分组 | `report090.py` |
| 副图：构建时间 / 内存柱状 | `summary.json → datasets.<ds>.engines.<engine>.build_seconds / memory_bytes` | 同上 |
| 同召回条形图（90% 处） | `summary.json → ...at_target.qps` 与 `vs hnswlib` | 同上 |
| 边界图（128d 落后） | `summary.json → sift128 → max_recall` 与 `at_target` | 同上 |
| X 文案里每个数字 | 必须能指到 `summary.json` 的某个具体字段 | — |

`report090.py --datasets cohere-1m` 可只重建某个数据集的表。

---

## 五、结果结构

```
results/bench-090/official/
  raw/
    cohere-1m__triviumdb__r1.json      # 仓库自带 bench 输出（schema_version 1）
    cohere-1m__triviumdb__r1.meta.json # 我们的旁注：commit / 线程 / 参数 / tag
    cohere-1m__hnswlib.json            # schema_version 2
  logs/
    cohere-1m__triviumdb__r1.log       # 完整 stdout，出问题先看这里
  summary.json   # 合并后：engines / points / at_target / build / memory
  summary.md     # 可直接贴进文章的表
  summary.csv    # 画图用
```

---

## 六、已知坑（都是真踩过的，不是假设）

1. **cohere 的 f32 是未归一化原文，GT 是 cosine 口径。**
   HNSW 侧必须先把向量 L2 归一化再做内积（官方 `bench_baselines.py` 就是这么做的）。
   直接对原始向量用 `METRIC_INNER_PRODUCT`，会得到研究文档 P8 里那种"扫全表召回只有 34%"的假象。
   `check` 的 `gt_match` 就是用来钉死这一点的。

2. **tie floor。**
   `sift128` 的 GT 只有 Top-10；第 10/11 名同分时，任何库都拿不到 100% 召回。
   `check` 会打印 `tie_gap_median`，小于 1e-6 时文章里必须注明"召回上限受并列影响"。

3. **低 ef 段可能有台阶。**
   0.9.0 默认 SM-L2 在预算被拒时会回退 BQ，曲线低端不是平滑的。
   这正是要求扫 9 个 ef 点、不做两点插值的原因。

4. **内存口径不可混比。**
   TriviumDB 报 `hot_bytes`（不含 OS 页缓存与 mmap 常驻），HNSW 报公式估算。
   两个数只能看量级，不能写成"省了 4.7 倍"这种精确结论；表格里已用 `*` 标注。

5. **128 维大概率仍然落后。**
   旧文是 0.21×。如果 0.9.0 依旧落后，那是要发出去的诚实边界，**不允许**临时把目标召回改成 50% 来"赢一档"。

6. **Windows 控制台默认 GBK。**
   两个脚本已强制 stdout UTF-8；若重定向后仍乱码，先 `$env:PYTHONIOENCODING="utf-8"`。

7. **cargo 可能不在 PATH。**
   脚本会回落到 `%USERPROFILE%\.cargo\bin\cargo.exe`。

8. **dbpedia-1536 单集训练文件 5.7 GiB**，加载 + 归一化 + 建图峰值可能 12 GB 以上。
   跑之前关掉其它吃内存的进程，别在同一台机器上并行跑两个数据集。

9. **计时窗口太短会系统性低估吞吐。**
   原始 1000 条查询在 4 万 QPS 下每个 ef 只有 25 ms，实测三次重复 CV 高达 10%。
   平铺到 2 万条后同一个点从 34.9k 涨到 45.6k（+30%），召回完全不变（91.72–91.76%）。
   结论：**不平铺的数字一律作废**。`--factor 1` 只用于冒烟。

10. **重复间离散度就是污染探针。**
   同一数据集 3 次重复里，`build.seconds` 离散度 > 10% 或 QPS 的 CV > 8%，该轮一律作废重测。
   实测案例：dbpedia 三次 build 为 107.7 / 117.9 / **87.0**（离散 29.7%，CV 11.6%），
   重测后变成 101.2 / 105.6 / 103.4（离散 4.3%，CV 2.2%）——那个"最快的一次"才是没被干扰的。

11. **同机干扰必须当成一等公民。**
   实测：开着 UE（18 GB 常驻）+ 其它工具时，cohere 上 hnswlib 建图 202 s，
   比旧文 i5-13490F 的 166 s 还慢 22%——更快的 CPU 反而更慢，这只能是环境干扰。
   同一个 dbpedia 场景还直接撞出过 `std::bad_alloc`。
   开跑前确认：可用内存 ≥ 3× 训练集 + 8 GB，CPU 负载 < 15%，并跑在独立进程里。

---

## 七、发布前检查清单

- [ ] `check` 全绿，四个数据集 `gt_match = 1.0000`
- [ ] 每个数据集 `repeats >= 3`
- [ ] `summary.md` 里没有意外出现的 `unreachable`（若有，要么补 ef 重跑，要么在文中如实写"该档未达 90%"）
- [ ] 文章里每个数字都能在 `summary.json` 找到对应字段
- [ ] 复述了：机器、线程、HNSW 参数、重复次数、中位数、插值方法
- [ ] 边界档（128d）没有被隐藏
- [ ] 没有把 `tag=smoke` 的任何数字写进对外内容

---

## 八、还没做、但迟早要补的

- **0.7.5 → 0.9.0 的版本对比**：需要在旧 tag 上再开一个工作树，用同一套 `M/efc/ef` 在本机跑一遍。
  这是唯一能支撑"升级后更快/更慢"的路径——旧文的 73,197 QPS 出自 i5-13490F，跨机不可比。
  旧版 bench 入口可能不同（QuIVer 配置字段变过），要单独验证，不能假设可以直接跑。
- **混合查询（向量 + 图 + 属性过滤）的端到端延迟**：现在这套只测纯 ANN。
  要做第三张图，得另写一个 TQL 场景脚本，并且必须同时测"三库拼接"的对照，否则没有可比性。

---

## 九、2026-11-04 批次的实际处置（下次照做）

1. **`bench_pipeline_gate` 的官方断言会误判**：两个物理计划结果内容一致，但
   `provenance` 元数据不同（优化计划写 `property_origin`），`NodeSet` 全等比较必然失败。
   处置：只在 `.bench090` 工作树里把断言改成按内容签名（id + similarity + property_score）比较，
   并在报告里写明。**不改主仓库**。
2. **`fault_allocator` 在 release+LTO 下会把 rustc 编译崩掉**（`STATUS_ACCESS_VIOLATION`）。
   处置：故障注入套件改用 debug 构建跑，只引用通过数，不引用耗时。
3. **仓库自带报告名带规模后缀**：`deep-traversal-1000000.json`、
   `query-parallel-200000-768.json`，归档时别写死成 `deep-traversal.json`。
4. **批跑脚本 `run_all.py`** 会串行跑完 P0–P6 并在最后调用 `make_report.py`；
   单步失败不阻断，状态写入 `results/bench-090/official/runlog.json`。

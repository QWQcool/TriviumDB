# 换机恢复指南：从 fork 重建这套实验与论文环境

> 面向两个场景：**(A)** 第三方想查证论文数据，只想看产物；**(B)** 你自己换电脑，想继续跑实验 / 重建投稿 PDF。
> 结论先行：**代码、全部产物（`results/**`，含 290 个原始日志）、论文与脚本都在 fork 上**；
> 只有三类东西不在：原始数据集向量（≈112 GB）、可重建的中间件（`.tmp/l0_csr_*.bin`，≈2.8 GB）、本地环境（Rust / Python / 排版工具链）——三者都有脚本可复现。

---

## 0. 一张表：什么在 fork 上，什么不在

| 内容 | 在 fork？ | 位置 / 怎么恢复 |
|---|---|---|
| 实验与论文代码 | ✅ | 分支 `research/quiver2-pipnn-rabitq-tsng`（另有 26 个 `feature/webui-*` 分支在 origin） |
| 全部产物 JSON / 报告 | ✅ | `results/**`（`results/t2/`、`results/baseline/`、`results/t2/gist960_collapse/`） |
| **原始 stdout 日志** | ✅ | `results/logs/`（290 个；从本机 `.tmp/` 复制入库，见该目录 README） |
| 论文（13 节 Markdown + 6 图 + 投稿包） | ✅ | `docs/paper/**`、`docs/paper/submission/**` |
| 上游 patch | ✅ | `patches/f1-nav-weighted.patch` |
| 数据集向量 `*.f32` / `*.i32` | ❌ | `.gitignore` 掉的；用 `scripts/prepare_all.py` + VIBE/RedCaps 下载脚本重建（见 §2） |
| `.tmp/l0_csr_*.bin`（图邻接 CSR 导出） | ❌ | 由 `benches/bench_t2_build_recon.rs` 重建（每个 ≈250 MB，共 9 个） |
| `.venv/`、`target/`、Pandoc/Tectonic | ❌ | 重装（见 §4、§5） |
| 审稿产物 `.codebuddy/`、`.claude/`、`AGENTS.md` 等 | ❌（未跟踪） | 与论文无关的工具垃圾，不必恢复 |

---

## 1. 克隆与分支

```bash
git clone https://github.com/QWQcool/TriviumDB && cd TriviumDB
git switch research/quiver2-pipnn-rabitq-tsng     # 论文 + 实验主线（results/** 与 docs/paper/** 都在这）
git branch -r | grep webui                        # 26 个 WebUI 分支（都在 origin）
```

**第三方查证最短路径（不需要跑任何东西）**：

1. `results/logs/README.md` → 日志命名与对应章节；
2. `docs/paper/section-11-artifacts.md` §11.3 / §11.6 → 论文表 → 产物文件 的映射；
3. `docs/research/p8-queue-report.md` → 最后一轮 10 步队列的结果、诊断与撤换记录。

## 2. 数据集（≈112 GB，不在仓库里）

`.gitignore:48` 忽略 `*.f32`；行数校验一律用 `字节数 ÷ 4 ÷ dim`（别用 MB 估算）。

```bash
# 12 个 Table 11 行（HF / ann-benchmarks 源），归一化 + 重算 cosine GT
python scripts/prepare_all.py <name>            # 例：cohere / gist960 / sift128 / glove100 / wolt_clip …
python scripts/research/gist960_collapse_prepare.py --center gist960:960      # 去均值变体（含 ‖μ‖≤1 守卫）
python scripts/research/gist960_collapse_prepare.py --rotate gist960:960      # 旋转变体（含 GT 不变性校验）

# VIBE 七个基准（§9.5）
python scripts/research/download_vibe_parallel.py
python scripts/research/convert_hdf5_to_f32.py

# RedCaps-1M（§4.4）：Zenodo 13137120，22.12 GiB，MD5 a6221cc0a4103af7e0f06f87bd989a0a
```

**注意**：`cohere_*.f32` 在磁盘上是**原始未归一化**向量（‖x‖≈13.8）而 GT 是 cosine —— §5.6(b) 的全部故事源于此；
任何直接对这些文件做原始向量 IP 搜索的脚本都必须先 `faiss.normalize_L2`（`RA_NORMALIZE=1`）。

## 3. Rust 侧（图索引实验）

```bash
RUSTFLAGS="-C target-cpu=native" cargo build --release --features ablation
# 单臂（论文所引数字都来自这条路径；T2_* 环境变量见 §11.4/§11.6）
T2_PREFIX=gist960 T2_DIM=960 T2_FROZEN_RECALL=2.79 \
  cargo bench --features ablation --bench bench_t2_b2_partitioned
# 引擎侧开关
TRIVIUM_SIGN_ROTATE=20260923 TRIVIUM_NAV_WEIGHTED=1 T2_PREFIX=gist960c T2_DIM=960 \
  cargo bench --features ablation --bench bench_t2_b2_partitioned     # 80.12 / 97.13（§8.6）
```

坑：Windows 上 `cargo build/bench` 前**必须停掉正在运行的 server**（exe 被锁）；`.cargo\bin` 不在 PATH 时用绝对路径调 cargo（见 `docs/research/p8-queue-report.md` §4-D5）。

## 4. Python 侧

关键依赖：`numpy`、`faiss-cpu`（1.15，含 `IndexIVFRaBitQ`/`IndexRefineFlat`）、`hnswlib`、`usearch`、
`pandas`（部分分析脚本）、`pymupdf`（图 SVG→PDF）。

```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install numpy faiss-cpu hnswlib usearch pymupdf
.venv/Scripts/python.exe scripts/research/p8_collect_numbers.py    # 一览式取数清单
```

## 5. 论文构建（Pandoc + Tectonic）

本机装法（不需要管理员）：

```powershell
# pandoc：windows-x86_64.zip；tectonic：x86_64-pc-windows-msvc.zip
# 解压到 %LOCALAPPDATA%\TriviumPaperTools\（build 脚本按此默认路径查找，也可用 PANDOC / TECTONIC 环境变量覆盖）
```

```bash
.venv/Scripts/python.exe scripts/paper/build_submission.py
# -> docs/paper/submission/{quiver-independent-eval.tex, .pdf, figures/*.pdf, abstract-short.txt}
```

脚本自带：六图 SVG→PDF、按序拼装、Unicode 数学→LaTeX 映射、代码块/标题行 ASCII 降级、**缺字形自检**。

## 6. 不要往仓库里塞的东西

`*.f32` / `*.i32`（数据集）、`.tmp/l0_csr_*.bin`（可重建）、`.venv/`、`target/`、`.gitnexus/`、
以及 `.codebuddy/`、`.claude/`、`AGENTS.md`、`CLAUDE.md` 等工具文件（均已在 `.gitignore` 或保持未跟踪）。

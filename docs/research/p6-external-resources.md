# P6 —— 外部资源项（G11 DiskANN-Rust / G12 VIBE）：下载与构建结果

> **日期**：2026-09-23 ｜ 日志 `.tmp/vibe_dl2.log` ｜ 代码 `scripts/research/download_vibe_parallel.py`
> **用户指令**：离线不可得的两项"去下载并尝试构建"。

---

## 1. G11 —— DiskANN Rust：**已下载、构建被工具链阻塞**

**下载 ✓**：`microsoft/DiskANN` 克隆到 `C:\Users\v_chchsli\Desktop\trivium-vendor\DiskANN`。
它**本身就是 Rust workspace**（`diskann/` + `cmd_drivers/build_memory_index`、`search_memory_index`、
`build_and_insert_memory_index` … + `vector/platform/logger`）⇒ **这正是论文 §5.3 里说的
"DiskANN Rust (float32 Vamana graph, Microsoft's official Rust rewrite)"** ⇒ 基线目标确认无误。

**构建 ✗（硬阻塞）**：`cargo build --release` 在 `openblas-src` 处失败：

```
openblas-src-0.10.8/build.rs:53  panicked: VcpkgNotFound("No vcpkg installation found.
Set the VCPKG_ROOT environment variable or run 'vcpkg integrate install'")
```

`diskann/Cargo.toml` 的依赖是 `openblas-src = { version = "0.10.8", features = ["system"] }`
⇒ 需要**系统 OpenBLAS**。本机工具链现状：

| 工具 | 状态 |
|---|---|
| rustc/cargo | ✓（`host: x86_64-pc-windows-msvc`，我们自己的项目能正常构建） |
| `cl` / `link` / `gcc` / `cc` / `clang` | **全部不在 PATH** |
| `cmake` / `vcpkg` / `make` | **缺失** |

⇒ 既不能 vcpkg 装 OpenBLAS，也不能从源码构建 OpenBLAS（要 make + Fortran）。

**另试的两个纯 Rust 实现也都不通**：

| 实现 | 结果 |
|---|---|
| `jianshu93/rust-diskann` | `anndists` 编译失败 **E0554**（`#![feature]` 不能在 stable 上用）⇒ 需 nightly |
| `infinilabs/diskann` | 同样卡在 `openblas-src` / vcpkg |

**解锁需要**（需管理员 + 数 GB）：安装 VS Build Tools（C++ 工具链）+ vcpkg（`vcpkg install openblas`），
或 MSYS2（gcc + openblas）。**在拿到它之前，G11 记为"阻塞：工具链"**，论文里继续只用
hnswlib / FAISS-HNSW / USearch / IVF-Flat / `faiss_exact` 这 5 个（我们都已实测）。

**替代增量也失败**：`README_QUIVER.md` 的 `bench_baselines.py` 覆盖
`hnswlib / FAISS HNSW / FAISS IVF-PQ / USearch / **VSAG / VSAG-HGraph**`，而 `pyvsag 0.0.11` 本机**已装**，
看起来是"第 6 个实现"的现成机会。但实际跑仓库脚本时报 `[跳过] pyvsag 未安装`，查明原因：

```
import pyvsag  ->  ModuleNotFoundError: No module named '_pyvsag'
site-packages/pyvsag/ 里是：
  _pyvsag.cpython-310-x86_64-**linux-gnu**.so
  libvsag.so（141 MB）、libgfortran.so.5
```

⇒ **装的是 Linux wheel**（且是 cp310，本环境 cp312）⇒ Windows 上不可用。**VSAG 亦为阻塞**。

⇒ **G11 的结论**：本机**无法产出 DiskANN-Rust / VSAG 这两个基线**，两条路都是硬阻塞、
且原因不同（前者缺 C/C++/BLAS 工具链，后者是平台不匹配的 wheel）。论文里继续只用已实测的
5 个竞品（hnswlib / FAISS-HNSW / USearch / IVF-Flat / `faiss_exact`）。

---

## 2. G12 —— VIBE：**下载已解决，转换与基准待跑**

**取得路径 ✓**：HF `vector-index-bench/vibe`（37 个文件），仓库 `convert_hdf5_to_f32.py` 需要的 7 个全在：

| 文件 | 大小 | 对应 bench 名 |
|---|---|---|
| `coco-nomic-768-normalized.hdf5` | 1.2 GiB | `coco-nomic` |
| `ccnews-nomic-768-normalized.hdf5` | 1.4 GiB | `ccnews-nomic` |
| `landmark-nomic-768-normalized.hdf5` | 2.2 GiB | `landmark-nomic` |
| `landmark-dino-768-cosine.hdf5` | 2.2 GiB | `landmark-dino` |
| `arxiv-nomic-768-normalized.hdf5` | 3.9 GiB | `arxiv-nomic` |
| `codesearchnet-jina-768-cosine.hdf5` | 3.9 GiB | `codesearch-jina` |
| `gooaq-distilroberta-768-normalized.hdf5` | 4.2 GiB | `gooaq-roberta` |

**坑（K29）**：`huggingface_hub.hf_hub_download` 在本机**完全不动** ——
8 分钟后 `.incomplete` 仍是 **0 B**、HF 缓存 **0 GB**（API 调用正常，`list_repo_tree` 秒回）。
直连 CDN 的 range 请求却正常：`huggingface.co` **1.5 MB/s**、`hf-mirror.com` **2.0 MB/s**（单连接）。
⇒ 改用**并行 HTTP range 下载**（7 文件并发、可续传）：**聚合 ~23 MB/s**，19 GiB 约 15 分钟。
脚本 `scripts/research/download_vibe_parallel.py`，产物 `vibe_hdf5/*.hdf5`。

**下一步**：`convert_hdf5_to_f32.py --input-dir vibe_hdf5`（产出 `<name>_train.f32/_test.f32/_groundtruth.i32`）
⇒ 用 `bench_t2_b2_partitioned`（`T2_PREFIX`/`T2_DIM=768`）跑行 ⇒ 补进 §4/§5 的表。
注意 VIBE 的 7 行**不在论文 Table 11 的 12 行里**，所以它们的价值是**拓展**（论文 Discussion 的"跨分布"主张），
而不是"复现"。

---

## 3. ★ VIBE 的首批实测结果（2 行已跑完，**发现一个新的失败案例**）

| VIBE 行 | n × d | `sign_info` | `‖μ‖` | 随机对 cos（均值±std） | `GT10−GT11` | `probe_ef`（双度量最弱） | **QuIVer R@10@64** | @1024 | **hnswlib `ef=64`** |
|---|---|---|---|---|---|---|---|---|---|
| `coco_nomic` | 282K × 768 | 0.382 | 0.882 | 0.106±0.045 | **0.0003** | **0.6%**（w 26.4 / c 0.6） | **0.21%** | 3.59% | **86.23%** @17,053 |
| `ccnews_nomic` | 495K × 768 | 0.690 | 0.737 | 0.869±0.054 | 0.0034 | 99.0%（w 99.2 / c 99.0） | 25.65% | **99.64%** | （未测） |

**三条读法，都对论文有用**：

1. ★ **`coco_nomic` 是 Table 11 之外的一个"灾难级"案例，而且 HNSW 在同任务上很好**：
   QuIVer `0.21%` vs hnswlib `86.23%`（`faiss_exact` = 100% ⇒ GT 与任务都没问题）。
   这是 **C2（适用性 ≠ 竞争力）在"论文从未评估过的现代嵌入基准"上的直接外延**。
2. ★ **判据链在一个它从未见过的数据集上正确预警**：`probe_ef = 0.6% ⇒ 规则③"改用 float32"` ✓
   （`ccnews_nomic` 则是 99.0% ⇒ 判"可用"，且其 **@ef_s=1024 实测 99.64%** 与探针吻合）。
   ⚠️ 但这暴露一个必须写清的**口径细节**：`probe_ef` 预测的是**码的"天花板"**（在足够大的 `ef_s` 下实现），
   **不是**低 `ef` 工作点 —— `ccnews_nomic` 的 99% 探针对应的是 `ef_s=1024` 的 99.64%，而它 `ef=64` 只有 25.65%
   （⇒ 该数据集"吃 ef"）。判据是**可用性门**，不是延迟/工作点预测器。
3. ⚠️ **我们自己的修复救不了 `coco_nomic`**：引擎侧旋转只把它从 `0.21%` 抬到 `0.70%`
   ⇒ 它**既不是符号面崩塌（旋转可修）也不是索引无关崩塌（图都不行）**，而是**码容量不足**：
   符号面半活（`sign_info = 0.382`、Hamming 探针 0.6%）而幅度面只到 26% ⇒ 2-bit 码根本装不下这个任务的角间隙
   （`GT10−GT11 = 0.0003`：第 10 名与第 11 名几乎并列）。**这是 C1 的诚实边界**，
   与 `sphere/gauss960` 那条一起构成"**三种失败**"的完整分类（可修 / 任务不可分辨 / 码容量不足）。

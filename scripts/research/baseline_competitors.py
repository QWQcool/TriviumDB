"""竞品基线 —— hnswlib / FAISS HNSW / USearch，对 QuIVer 的宣称做独立核验。

## 为什么必须做
`docs/research/bootstrap-report.md` / `l1-baseline.md` 引用了仓库宣称的
"相对 hnswlib 4–5×"，但**那个数字在本机从未被复现过**。
任何方向的论文都绕不过"有无可比基线"这一条。

## 口径（与 QuIVer 主基准严格对齐）
| 项 | 值 |
|---|---|
| 数据 | `{PREFIX}_train.f32`，L2 归一化后 cosine = 内积 |
| 查询 / GT | `{PREFIX}_test.f32` / `{PREFIX}_groundtruth.i32`（前 10 列） |
| 参数 | M=32（对齐 QuIVer 的 m=32）、ef_construction=128 |
| 扫描 | ef_search ∈ {64,128,256,512,1024} |
| 线程 | 与 QuIVer 主基准一致的 32 线程（`num_threads` / `omp_set_num_threads`） |
| 召回定义 | 返回 top-10 命中 GT top-10 的比例（与 QuIVer 一致） |

> ⚠️ **公平性声明**：M=32 是对齐 QuIVer 的 `m`，但**图出度语义不同**——
> QuIVer 的 `m0 = 2m = 64`（每节点最多 64 条出边），而 HNSW 的 M=32 意味着
> 层 0 出度上限约 `2M = 64`。⇒ **两者在出度上是可比的**（都是 64）。

## 输出
`results/baseline/competitors_{PREFIX}.json` + stdout 的 markdown 表。
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PREFIX = os.environ.get("T2_PREFIX", "cohere")
DIM = int(os.environ.get("T2_DIM", "768"))
M = int(os.environ.get("BL_M", "32"))
EFC = int(os.environ.get("BL_EFC", "128"))
THREADS = int(os.environ.get("BL_THREADS", "32"))
EF_LIST = [64, 128, 256, 512, 1024]
TOP_K = 10
N_CAP = int(os.environ.get("T2_N", "0"))  # 0 = 全部

TRAIN = f"{PREFIX}_train.f32"
TEST = f"{PREFIX}_test.f32"
GT = f"{PREFIX}_groundtruth.i32"


def l2n(x):
    n = np.linalg.norm(x, axis=1, keepdims=True)
    n[n < 1e-12] = 1.0
    return x / n


def recall_at_10(labels, gt):
    """labels/gt: (nq, 10)。逐查询算命中数。"""
    hit = 0
    for i in range(labels.shape[0]):
        hit += len(set(labels[i].tolist()) & set(gt[i].tolist()))
    return hit / (labels.shape[0] * TOP_K) * 100.0


def run_hnswlib(train, test, gt):
    import hnswlib

    print("\n  [hnswlib]")
    t = time.time()
    idx = hnswlib.Index(space="cosine", dim=DIM)
    idx.init_index(max_elements=train.shape[0], ef_construction=EFC, M=M)
    idx.add_items(train, np.arange(train.shape[0], dtype=np.int64), num_threads=THREADS)
    build_s = time.time() - t
    print(f"    建图 {build_s:.2f}s  {train.shape[0]/build_s:.0f} vec/s")

    rows = []
    for ef in EF_LIST:
        idx.set_ef(ef)
        t = time.time()
        labels, _ = idx.knn_query(test, k=TOP_K, num_threads=THREADS)
        el = time.time() - t
        r = recall_at_10(labels, gt)
        qps = test.shape[0] / el
        rows.append({"ef": ef, "recall": r, "qps": qps, "latency_ms": el / test.shape[0] * 1000})
        print(f"    ef={ef:<5} R@10 {r:6.2f}%  {qps:9.0f} QPS")
    return {"name": "hnswlib", "build_s": build_s, "rows": rows}


def run_faiss_hnsw(train, test, gt):
    import faiss

    print("\n  [FAISS HNSW]")
    faiss.omp_set_num_threads(THREADS)
    t = time.time()
    idx = faiss.IndexHNSWFlat(DIM, M, faiss.METRIC_INNER_PRODUCT)
    idx.hnsw.efConstruction = EFC
    idx.add(train)
    build_s = time.time() - t
    print(f"    建图 {build_s:.2f}s  {train.shape[0]/build_s:.0f} vec/s")

    rows = []
    for ef in EF_LIST:
        idx.hnsw.efSearch = ef
        t = time.time()
        _, labels = idx.search(test, TOP_K)
        el = time.time() - t
        r = recall_at_10(labels.astype(np.int64), gt)
        qps = test.shape[0] / el
        rows.append({"ef": ef, "recall": r, "qps": qps, "latency_ms": el / test.shape[0] * 1000})
        print(f"    ef={ef:<5} R@10 {r:6.2f}%  {qps:9.0f} QPS")
    return {"name": "faiss_hnsw", "build_s": build_s, "rows": rows}


def run_faiss_ivf(train, test, gt, nlist=4096, nprobe_list=(16, 64, 128, 256)):
    """非图基线：IVF-Flat。用于说明"图 vs 非图"的量级差。"""
    import faiss

    print("\n  [FAISS IVF-Flat]")
    faiss.omp_set_num_threads(THREADS)
    quant = faiss.IndexFlatIP(DIM)
    t = time.time()
    idx = faiss.IndexIVFFlat(quant, DIM, nlist, faiss.METRIC_INNER_PRODUCT)
    idx.train(train)
    idx.add(train)
    build_s = time.time() - t
    print(f"    建图 {build_s:.2f}s  nlist={nlist}")

    rows = []
    for np_ in nprobe_list:
        idx.nprobe = np_
        t = time.time()
        _, labels = idx.search(test, TOP_K)
        el = time.time() - t
        r = recall_at_10(labels.astype(np.int64), gt)
        qps = test.shape[0] / el
        rows.append({"nprobe": np_, "recall": r, "qps": qps, "latency_ms": el / test.shape[0] * 1000})
        print(f"    nprobe={np_:<4} R@10 {r:6.2f}%  {qps:9.0f} QPS")
    return {"name": "faiss_ivf_flat", "build_s": build_s, "rows": rows}


def run_faiss_exact(train, test, gt):
    """精确基线：给"相对精确的加速比"做分母。"""
    import faiss

    print("\n  [FAISS FlatIP 精确]")
    faiss.omp_set_num_threads(THREADS)
    idx = faiss.IndexFlatIP(DIM)
    idx.add(train)
    t = time.time()
    _, labels = idx.search(test, TOP_K)
    el = time.time() - t
    r = recall_at_10(labels.astype(np.int64), gt)
    qps = test.shape[0] / el
    print(f"    R@10 {r:6.2f}%  {qps:9.1f} QPS（应与 GT 一致）")
    return {"name": "faiss_exact", "build_s": 0.0, "rows": [
        {"ef": None, "recall": r, "qps": qps, "latency_ms": el / test.shape[0] * 1000}
    ]}


def run_usearch(train, test, gt):
    """USearch：现代 HNSW 实现，作为第三个图基线。"""
    try:
        from usearch.index import Index
    except Exception as e:
        print(f"\n  [USearch] 跳过: {type(e).__name__}: {e}")
        return None

    print("\n  [USearch]")
    t = time.time()
    idx = Index(
        ndim=DIM,
        metric="cos",
        connectivity=M,
        expansion_add=EFC,
        expansion_search=128,
    )
    idx.add(np.arange(train.shape[0], dtype=np.int64), train)
    build_s = time.time() - t
    print(f"    建图 {build_s:.2f}s  {train.shape[0]/build_s:.0f} vec/s")

    rows = []
    for ef in EF_LIST:
        idx.expansion_search = ef
        t = time.time()
        res = idx.search(test, TOP_K)
        el = time.time() - t
        labels = np.asarray(res.keys, dtype=np.int64)
        r = recall_at_10(labels, gt)
        qps = test.shape[0] / el
        rows.append({"ef": ef, "recall": r, "qps": qps, "latency_ms": el / test.shape[0] * 1000})
        print(f"    ef={ef:<5} R@10 {r:6.2f}%  {qps:9.0f} QPS")
    return {"name": "usearch", "build_s": build_s, "rows": rows}


def main():
    t0 = time.time()
    for p in (TRAIN, TEST, GT):
        if not os.path.exists(p):
            print(f"缺少 {p}")
            return 1

    print("=" * 78)
    print(f"  竞品基线  {PREFIX}  dim={DIM}  M={M}  ef_construction={EFC}  线程={THREADS}")
    print("=" * 78)

    train = np.fromfile(TRAIN, dtype=np.float32).reshape(-1, DIM)
    test = np.fromfile(TEST, dtype=np.float32).reshape(-1, DIM)
    if N_CAP and N_CAP < train.shape[0]:
        train = train[:N_CAP]
    gt_all = np.fromfile(GT, dtype=np.int32)
    k_gt = gt_all.size // test.shape[0]
    gt = gt_all.reshape(test.shape[0], k_gt)[:, :TOP_K].astype(np.int64)

    train = l2n(train)
    test = l2n(test)
    print(f"  train {train.shape}  test {test.shape}  GT {gt.shape}  加载 {time.time()-t0:.1f}s")

    lv = np.ascontiguousarray(train)
    qv = np.ascontiguousarray(test)

    results = []
    for fn in (run_faiss_exact, run_hnswlib, run_faiss_hnsw, run_usearch, run_faiss_ivf):
        try:
            r = fn(lv, qv, gt)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  [{fn.__name__}] 失败: {type(e).__name__}: {str(e)[:200]}")

    # ── markdown ──
    print("\n### 竞品基线（" + f"{PREFIX} {train.shape[0]} × {DIM}，M={M}，ef_c={EFC}，"
          f"{THREADS} 线程）\n")
    print("| 方法 | 参数 | R@10 | MT-QPS | 延迟 ms | 建图 s |")
    print("|---|---|---|---|---|---|")
    for r in results:
        for row in r["rows"]:
            key = row.get("ef") if row.get("ef") is not None else row.get("nprobe")
            kname = "ef" if row.get("ef") is not None else "nprobe"
            print(
                f"| {r['name']} | {kname}={key} | {row['recall']:.2f}% | {row['qps']:.0f} | "
                f"{row['latency_ms']:.4f} | {r['build_s']:.1f} |"
            )

    os.makedirs(os.path.join("results", "baseline"), exist_ok=True)
    out = os.path.join("results", "baseline", f"competitors_{PREFIX}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "prefix": PREFIX,
                "dim": DIM,
                "n_train": int(train.shape[0]),
                "n_test": int(test.shape[0]),
                "m": M,
                "ef_construction": EFC,
                "threads": THREADS,
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n  已写出 {out}")
    print(f"  总耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

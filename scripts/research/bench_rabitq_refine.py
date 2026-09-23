"""P7-④：复现论文 §5.3 的 **FAISS IVF+RaBitQ+Refine** 基线（他们 9 个基线里的一个）。

论文原文：「FAISS IVF+RaBitQ+Refine (12) (IVF1024 with RaBitQ FastScan coarse search and
SQ8 reranking, the Pareto-best nprobe and k_factor at each recall level)」
⇒ 我们用 faiss 1.15 的 `IndexIVFRaBitQ` + `IndexRefineFlat`（f32 精排）做同族对照，
扫描 nprobe × k_factor，按 **MT/ST-QPS** 报，输出与 `competitors_*.json` 同形以便并入 §5 的地图。

线程数用 `TRIVIUM_MT_THREADS`（默认 32，与我们的竞品地图一致）。

用法：`.venv/Scripts/python.exe scripts/research/bench_rabitq_refine.py cohere 768 [nlist]`
"""
import json
import os
import sys
import time
from pathlib import Path

import faiss
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
TOP_K = 10
NPROBES = tuple(int(x) for x in os.environ.get("RA_BITQ_NPROBES", "64,128,256,512").split(","))
# ⚠️ `IndexRefineFlat` 只对 `k_factor × k` 个**码排序**候选做精排 ⇒ 召回受**候选池**限制：
# 第一次用 (1,4,10,20) 跑 cohere 时，召回在 60.2% 处**与 nprobe 无关地卡住**
# （即 faiss 的 RaBitQ 码在该数据上的 top-200 里漏掉真邻）⇒ 必须放开 k_factor 才能看出天花板。
K_FACTORS = tuple(int(x) for x in os.environ.get("RA_BITQ_KFACTORS", "20,50,100,200").split(","))
THREADS = int(os.environ.get("TRIVIUM_MT_THREADS", "32"))


def load(prefix, dim):
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    gt = np.fromfile(ROOT / f"{prefix}_groundtruth.i32", dtype=np.int32).reshape(te.shape[0], -1)[:, :TOP_K]
    return tr, te, gt


def qps_of(fn, queries, reps=1):
    best = 0.0
    for _ in range(reps):
        t0 = time.perf_counter()
        fn(queries)
        dt = time.perf_counter() - t0
        if dt > 0:
            best = max(best, len(queries) / dt)
    return best


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "cohere"
    dim = int(sys.argv[2]) if len(sys.argv) > 2 else 768
    nlist = int(sys.argv[3]) if len(sys.argv) > 3 else 1024

    tr, te, gt = load(prefix, dim)
    print(f"\n  {prefix}: train={tr.shape} test={te.shape} nlist={nlist} threads={THREADS}")

    quantizer = faiss.IndexFlatIP(dim)
    ivf = faiss.IndexIVFRaBitQ(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    faiss.omp_set_num_threads(THREADS)
    t0 = time.perf_counter()
    ivf.train(tr)
    # ⚠️ `IndexRefineFlat` 必须在 **add 之前** 包住 base：其构造函数断言
    # `base_index->ntotal == refine_index->ntotal`，先 add 会直接抛 RuntimeError。
    refine = faiss.IndexRefineFlat(ivf)
    refine.add(tr)                       # 同时写 base（RaBitQ 码）与 refine（f32 副本）
    build_s = time.perf_counter() - t0
    print(f"  构建 {build_s:.1f}s（含 RaBitQ 训练）；索引 ntotal={refine.ntotal}")

    rows = []
    header = f"{'nprobe':>8} {'k_fac':>6} {'R@10':>9} {'1T-QPS':>10} {'MT-QPS':>10}"
    print(header)
    for nprobe in NPROBES:
        if nprobe > nlist:
            continue
        faiss.ParameterSpace().set_index_parameter(refine, "nprobe", nprobe)
        for k in K_FACTORS:
            try:
                faiss.ParameterSpace().set_index_parameter(refine, "k_factor", k)
            except Exception:                                            # noqa: BLE001
                pass
            _ = refine.search(te[:8], TOP_K)                             # warmup
            faiss.omp_set_num_threads(1)
            st = qps_of(lambda q: refine.search(q, TOP_K), te)
            faiss.omp_set_num_threads(THREADS)
            mt = qps_of(lambda q: refine.search(q, TOP_K), te)
            _, I = refine.search(te, TOP_K)
            rec = float(np.mean([len(set(I[i].tolist()) & set(gt[i].tolist())) for i in range(len(te))])) / TOP_K * 100
            rows.append({"ef": nprobe, "k_factor": k, "recall": rec, "st_qps": st, "qps": mt})
            print(f"{nprobe:>8} {k:>6} {rec:>8.2f}% {st:>10,.0f} {mt:>10,.0f}")

    out = {"prefix": prefix, "dim": dim, "n_train": int(tr.shape[0]), "n_test": int(te.shape[0]),
           "threads": THREADS, "build_s": build_s,
           "results": [{"name": "faiss_rabitq_refine", "build_s": build_s, "rows": rows}]}
    (ROOT / "results" / "t2").mkdir(parents=True, exist_ok=True)
    p = ROOT / "results" / "t2" / f"rabitq_refine_{prefix}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

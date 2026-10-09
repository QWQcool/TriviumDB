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
# 控制臂：`RA_CONTROL=ivfflat` ⇒ 同一 nprobe 网格上跑 **精确 f32 粗排** 的 IVF-Flat。
# 目的：把「召回卡在 ~60%」拆成两种可能 —— (i) RaBitQ 1-bit 码的天花板，(ii) 我们的包装/参数错。
# 判据：若 IVFFlat 在同 nprobe 下逼近 100%，则 (i) 成立，且这条对照本身就是论文可引的证据。
CONTROL = os.environ.get("RA_CONTROL", "").strip().lower()
# 口径修正（P8 诊断的根因）：cohere 的磁盘文件是**原始未归一化**向量（‖x‖≈13.8；其余数据集已被
# prepare_all 归一化），而 shipped GT 是 **cosine** 口径（`gt_metric_consistency_probe.py` 实测：
# 归一化 IP 复现 GT 10/10，原始 IP 只有 3.5/10）。不归一化时任何搜索都对不上 GT，且会出现
# 「RaBitQ 小候选池 = 59.75% 反而高于 IVF-Flat 全表 34.8%」的伪矛盾（k_factor 变大后 f32 精排
# 把结果拉回 raw-IP 排序，见 `faiss_refine_mechanics_probe.py`）。
# `RA_NORMALIZE=1` ⇒ 对 train/test 做 L2 归一化（与 bench_baselines.py 等脚本同口径）。
NORMALIZE = os.environ.get("RA_NORMALIZE", "").strip().lower() in ("1", "true", "yes")


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
    if NORMALIZE:
        faiss.normalize_L2(tr)
        faiss.normalize_L2(te)
    print(f"\n  {prefix}: train={tr.shape} test={te.shape} nlist={nlist} threads={THREADS}"
          f"  normalized={NORMALIZE}")

    quantizer = faiss.IndexFlatIP(dim)
    faiss.omp_set_num_threads(THREADS)
    t0 = time.perf_counter()
    if CONTROL == "ivfflat":
        refine = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
        refine.train(tr)
        refine.add(tr)
        k_factors = (1,)                 # 精确粗排没有"候选池"概念
        arm_name = "faiss_ivfflat_control"
        build_note = "（控制臂：精确 f32 粗排）"
    else:
        ivf = faiss.IndexIVFRaBitQ(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
        ivf.train(tr)
        # ⚠️ `IndexRefineFlat` 必须在 **add 之前** 包住 base：其构造函数断言
        # `base_index->ntotal == refine_index->ntotal`，先 add 会直接抛 RuntimeError。
        refine = faiss.IndexRefineFlat(ivf)
        refine.add(tr)                   # 同时写 base（RaBitQ 码）与 refine（f32 副本）
        k_factors = K_FACTORS
        arm_name = "faiss_rabitq_refine"
        build_note = "（含 RaBitQ 训练）"
    build_s = time.perf_counter() - t0
    print(f"  构建 {build_s:.1f}s{build_note}；索引 ntotal={refine.ntotal}")

    # ⚠️ 直接赋值，而不是 `ParameterSpace().set_index_parameter(wrapper, ...)`：
    #    后者对"被包住的"索引（`IndexRefineFlat` → `base_index`）是否**穿透**
    #    未经验证，而参数没生效会安静地给出错误曲线（P8 队列第 1 步就是查这个）。
    #    这里显式赋在真正参与搜索的对象上，并把生效值写进产物，便于复核。
    base = faiss.downcast_index(refine.base_index) if hasattr(refine, "base_index") else refine
    rows = []
    header = f"{'nprobe':>8} {'k_fac':>6} {'R@10':>9} {'1T-QPS':>10} {'MT-QPS':>10}"
    print(f"  search object = {type(base).__name__}   k_factor 可用 = {hasattr(refine, 'k_factor')}")
    print(header)
    for nprobe in NPROBES:
        if nprobe > nlist:
            continue
        base.nprobe = nprobe
        for k in k_factors:
            if hasattr(refine, "k_factor"):
                refine.k_factor = k
            _ = refine.search(te[:8], TOP_K)                             # warmup
            faiss.omp_set_num_threads(1)
            st = qps_of(lambda q: refine.search(q, TOP_K), te)
            faiss.omp_set_num_threads(THREADS)
            mt = qps_of(lambda q: refine.search(q, TOP_K), te)
            _, I = refine.search(te, TOP_K)
            rec = float(np.mean([len(set(I[i].tolist()) & set(gt[i].tolist())) for i in range(len(te))])) / TOP_K * 100
            rows.append({"ef": nprobe, "k_factor": k,
                         "eff_nprobe": int(base.nprobe),
                         "eff_k_factor": int(getattr(refine, "k_factor", 0)) or None,
                         "recall": rec, "st_qps": st, "qps": mt})
            print(f"{nprobe:>8} {k:>6} {rec:>8.2f}% {st:>10,.0f} {mt:>10,.0f}")

    out = {"prefix": prefix, "dim": dim, "n_train": int(tr.shape[0]), "n_test": int(te.shape[0]),
           "threads": THREADS, "build_s": build_s, "control": CONTROL or None,
           "normalized": NORMALIZE,
           "results": [{"name": arm_name, "build_s": build_s, "rows": rows}]}
    (ROOT / "results" / "t2").mkdir(parents=True, exist_ok=True)
    stem = "ivfflat_control" if CONTROL == "ivfflat" else "rabitq_refine"
    if NORMALIZE:
        stem += "_norm"
    p = ROOT / "results" / "t2" / f"{stem}_{prefix}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

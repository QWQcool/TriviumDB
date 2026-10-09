"""机制探针（合成数据，确定性）：`IndexRefineFlat` 的度量、默认 `k_factor` 与单调性。

背景（P8 队列第 2 步的意外发现）
--------------------------------
cohere 上（**未归一化**）修正版脚本测到：k_factor=1（默认）→ 59.75 %，k_factor=20 → 36.6 %，
k_factor=200 → 35.1 % —— k_factor 越大召回**越低**，与理论（候选池更大不应变差）相反。
本脚本在合成数据（无 GT 口径问题）上隔离 FAISS 侧机制本身，回答三个问题：

  1. `IndexRefineFlat.refine_index` 的度量是什么？（应为与 base 相同的 IP）
  2. 默认 `k_factor` 是多少？（faiss 1.15 = 1.0）
  3. 候选池更大时召回是否单调不降？（在合成数据上应单调上升）

⇒ 合成数据上机制完全正常 ⇒ cohere 的"反转"不是 FAISS 缺陷，而是 **GT 口径错配**下
（GT=cosine、文件=raw）raw-IP 精排与大候选池把结果拉回 raw-IP 排序的必然结果。
配套：`gt_metric_consistency_probe.py`（GT 口径）、`ivf_recall_diagnostic.py`（wrapper 穿透）。

用法：`.venv/Scripts/python.exe scripts/research/faiss_refine_mechanics_probe.py`
产物：`results/t2/faiss_refine_mechanics_probe.json`
"""
import json
import sys
from pathlib import Path

import faiss
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
K = 10


def main():
    np.random.seed(0)                     # 确定性
    faiss.omp_set_num_threads(4)
    d, nb, nq, nlist = 64, 20000, 200, 64
    base = np.random.randn(nb, d).astype(np.float32)
    q = np.random.randn(nq, d).astype(np.float32)

    s = q @ base.T
    gt_ip = np.argsort(-s, axis=1)[:, :K]
    sq = np.einsum("ij,ij->i", base, base)
    d2 = sq[None, :] - 2.0 * (q @ base.T) + np.einsum("ij,ij->i", q, q)[:, None]
    gt_l2 = np.argsort(d2, axis=1)[:, :K]

    def rec(I, gt):
        return float(np.mean([len(set(I[i].tolist()) & set(gt[i].tolist()))
                              for i in range(nq)])) / K * 100

    out = {"synthetic": {"d": d, "n_base": nb, "n_query": nq, "nlist": nlist, "seed": 0}}

    # ── A. 包装器度量 + 默认 k_factor（精确 base 作参照）────────────────
    b1 = faiss.IndexFlatIP(d)
    rf1 = faiss.IndexRefineFlat(b1)       # 构造必须在 add 之前（断言 ntotal 相等）
    rf1.add(base)
    section_a = {"base_metric": int(b1.metric_type),
                 "refine_metric": int(rf1.refine_index.metric_type),
                 "default_k_factor": float(rf1.k_factor), "rows": []}
    print(f"A. base metric={b1.metric_type} refine metric={rf1.refine_index.metric_type} "
          f"(IP={faiss.METRIC_INNER_PRODUCT}, L2={faiss.METRIC_L2})  default k_factor={rf1.k_factor}")
    for kf in (1.0, 20.0, 200.0):
        rf1.k_factor = kf
        _, I = rf1.search(q, K)
        r_ip, r_l2 = rec(I, gt_ip), rec(I, gt_l2)
        section_a["rows"].append({"k_factor": kf, "recall_vs_ip_gt": r_ip, "recall_vs_l2_gt": r_l2})
        print(f"   [exact base] k_factor={kf:g}  R@10(IP-GT)={r_ip:6.2f}%  R@10(L2-GT)={r_l2:6.2f}%")
    out["exact_base"] = section_a

    # ── B. RaBitQ base + RefineFlat（与队列脚本同结构）───────────────
    ivf = faiss.IndexIVFRaBitQ(faiss.IndexFlatIP(d), d, nlist, faiss.METRIC_INNER_PRODUCT)
    ivf.train(base)
    rf2 = faiss.IndexRefineFlat(ivf)
    rf2.add(base)
    b2 = faiss.downcast_index(rf2.base_index)
    b2.nprobe = 8
    section_b = {"base_type": type(b2).__name__, "refine_metric": int(rf2.refine_index.metric_type),
                 "default_k_factor": float(rf2.k_factor), "rows": []}
    print(f"\nB. RaBitQ base nprobe=8  refine metric={rf2.refine_index.metric_type}  "
          f"default k_factor={rf2.k_factor}")
    _, I = rf2.search(q, K)
    section_b["rows"].append({"k_factor": None, "note": "default", "recall_vs_ip_gt": rec(I, gt_ip)})
    print(f"   [rabitq base] default     R@10(IP-GT)={rec(I, gt_ip):6.2f}%")
    for kf in (1.0, 20.0, 200.0):
        rf2.k_factor = kf
        _, I = rf2.search(q, K)
        r = rec(I, gt_ip)
        section_b["rows"].append({"k_factor": kf, "recall_vs_ip_gt": r})
        print(f"   [rabitq base] k_factor={kf:g}  R@10(IP-GT)={r:6.2f}%")
    out["rabitq_base"] = section_b

    # ── C. IVF-Flat 参照（同 nprobe / 全表）─────────────────────────
    b3 = faiss.IndexIVFFlat(faiss.IndexFlatIP(d), d, nlist, faiss.METRIC_INNER_PRODUCT)
    b3.train(base)
    b3.add(base)
    ref = {}
    for np_ in (8, nlist):
        b3.nprobe = np_
        _, I = b3.search(q, K)
        ref[f"nprobe_{np_}"] = rec(I, gt_ip)
        print(f"C. [ivfflat] nprobe={np_:<4} R@10(IP-GT)={ref[f'nprobe_{np_}']:6.2f}%")
    out["ivfflat_reference"] = ref

    p = ROOT / "results" / "t2" / "faiss_refine_mechanics_probe.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  [OK] {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

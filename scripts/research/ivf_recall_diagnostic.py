"""诊断：为什么 `IndexIVFFlat`（精确 f32 粗排）在同 nprobe 下召回**低于** `IndexIVFRaBitQ+Refine`？

理论上不可能：`IndexRefineFlat` 只在"码排序的 top-(k_factor×k)"里做精排，而 IVF-Flat 对探测到的
**每个**列表向量都做精确比较 ⇒ IVF-Flat 的召回必须是上界。若测到相反，必有一侧错。

本脚本只测**召回**（不测 QPS，避免线程影响），把三件事一次问清：

1. IVF-Flat 的召回随 nprobe 的曲线（nprobe 是否真的生效？）；
2. `ParameterSpace().set_index_parameter(wrapper, "nprobe", x)` 是否**穿透到** `IndexRefineFlat` 的
   base index（不穿透 ⇒ 之前那跑的"nprobe"其实一直是默认值 1）；
3. RaBitQ+Refine 在 nprobe=1024（全表）时的召回上限。

用法：`.venv/Scripts/python.exe scripts/research/ivf_recall_diagnostic.py cohere 768 1024`
"""
import json
import sys
from pathlib import Path

import faiss
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
TOP_K = 10


def recall(I, gt):
    return float(np.mean([len(set(I[i].tolist()) & set(gt[i].tolist()))
                          for i in range(len(gt))])) / TOP_K * 100


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "cohere"
    dim = int(sys.argv[2]) if len(sys.argv) > 2 else 768
    nlist = int(sys.argv[3]) if len(sys.argv) > 3 else 1024
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    gt = np.fromfile(ROOT / f"{prefix}_groundtruth.i32", dtype=np.int32).reshape(te.shape[0], -1)[:, :TOP_K]
    faiss.omp_set_num_threads(32)
    print(f"  faiss {faiss.__version__}  {prefix} {tr.shape} nlist={nlist}")

    out = {"prefix": prefix, "dim": dim, "faiss": faiss.__version__, "nlist": nlist}

    # ── 1. 精确粗排 IVF-Flat ────────────────────────────────────────
    print("\n  [1] IndexIVFFlat（精确 f32）：nprobe 扫描")
    q = faiss.IndexFlatIP(dim)
    flat = faiss.IndexIVFFlat(q, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    flat.train(tr)
    flat.add(tr)
    print(f"      train 后的默认 nprobe = {flat.nprobe}")
    rows_flat = []
    for nprobe in (1, 4, 16, 64, 128, 256, 512, 1024):
        flat.nprobe = nprobe                       # 直接赋值，不经 ParameterSpace
        _, I = flat.search(te, TOP_K)
        r = recall(I, gt)
        rows_flat.append({"nprobe": nprobe, "recall": r})
        print(f"      nprobe={nprobe:<5} R@10 {r:6.2f}%   (index.nprobe={flat.nprobe})")
    out["ivfflat_direct"] = rows_flat

    # ── 2. ParameterSpace 是否穿透 wrapper ──────────────────────────
    print("\n  [2] ParameterSpace().set_index_parameter(IndexRefineFlat, 'nprobe', x) 是否穿透到 base？")
    q2 = faiss.IndexFlatIP(dim)
    ivf = faiss.IndexIVFRaBitQ(q2, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    ivf.train(tr)
    ref = faiss.IndexRefineFlat(ivf)
    ref.add(tr)
    base = faiss.downcast_index(ref.base_index)
    print(f"      包装前 base.nprobe={base.nprobe}")
    faiss.ParameterSpace().set_index_parameter(ref, "nprobe", 256)
    print(f"      set_index_parameter(wrapper, nprobe=256) 之后：wrapper.nprobe={getattr(ref, 'nprobe', 'N/A')} "
          f"base.nprobe={base.nprobe}  ⇒ {'穿透 ✓' if base.nprobe == 256 else '✗ 没穿透（一直是默认值）'}")
    out["paramspace_reaches_base"] = bool(base.nprobe == 256)

    # ── 3. 直接给 base 赋 nprobe，看 RaBitQ+Refine 的真实上限 ────────
    print("\n  [3] RaBitQ+Refine，直接给 base 赋 nprobe（k_factor=200）")
    try:
        faiss.ParameterSpace().set_index_parameter(ref, "k_factor", 200)
    except Exception as e:                                                # noqa: BLE001
        print(f"      k_factor 设置失败：{e}")
    rows_ra = []
    for nprobe in (1, 64, 256, 1024):
        base.nprobe = nprobe
        _, I = ref.search(te, TOP_K)
        r = recall(I, gt)
        rows_ra.append({"nprobe": nprobe, "k_factor": 200, "recall": r})
        print(f"      nprobe={nprobe:<5} k_factor=200  R@10 {r:6.2f}%")
    out["rabitq_refine_direct"] = rows_ra

    # ── 4. 同样条件下 IVF-Flat 用 ParameterSpace（复核 [1]） ─────────
    print("\n  [4] 对照：把 IVF-Flat 也用 ParameterSpace 设一遍（应与 [1] 一致）")
    q3 = faiss.IndexFlatIP(dim)
    flat2 = faiss.IndexIVFFlat(q3, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    flat2.train(tr)
    flat2.add(tr)
    rows_flat2 = []
    for nprobe in (64, 256):
        faiss.ParameterSpace().set_index_parameter(flat2, "nprobe", nprobe)
        _, I = flat2.search(te, TOP_K)
        r = recall(I, gt)
        rows_flat2.append({"nprobe": nprobe, "recall": r, "index_nprobe": flat2.nprobe})
        print(f"      nprobe={nprobe:<5} R@10 {r:6.2f}%  (index.nprobe={flat2.nprobe})")
    out["ivfflat_paramspace"] = rows_flat2

    p = ROOT / "results" / "t2" / f"ivf_recall_diagnostic_{prefix}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  [OK] {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

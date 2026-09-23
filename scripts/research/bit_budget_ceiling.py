"""P7-⑧：**位预算天花板** —— 判定一个数据集"不可用"是**码容量不足**还是**信息本身不存在**。

思路：把"每维 b 比特"当作唯一变量（逐维均匀量化 + min/max 归一化），
对每个 b 报告"码排序 → f32 精排"的召回（与 §7 的 `probe_ef` 同仪器）。
- 若召回随 b 迅速回升（2→4→6 bit）⇒ 该数据的瓶颈是**码容量**（如 `coco_nomic`）。
- 若在所有 b 上都上不去 ⇒ 瓶颈是**任务本身**（如 Random-Sphere/Gaussian：邻域不可分辨）。

同时打印 `GT10−GT11`（角间隙）与随机对 cos 分布，作为"信息是否存在"的旁证。

用法：`.venv/Scripts/python.exe scripts/research/bit_budget_ceiling.py coco_nomic 768 [--nbase 200000]`
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
BITS = (1, 2, 3, 4, 6, 8, 16)
TOP_K, EF, NQ = 10, 128, 200


def load(prefix, dim, nbase):
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    rng = np.random.default_rng(20260923)
    idx = rng.choice(tr.shape[0], min(nbase, tr.shape[0]), replace=False)
    return np.ascontiguousarray(tr[idx]), te


def normalize(a):
    return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)


def uniform_code(x, lo, hi, bits):
    """逐维均匀量化 → 反量化（b 比特/维）"""
    levels = (1 << bits) - 1
    step = (hi - lo) / max(levels, 1)
    q = np.clip(np.round((x - lo) / np.maximum(step, 1e-12)), 0, levels)
    return q.astype(np.float32) * step + lo


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "coco_nomic"
    dim = int(sys.argv[2]) if len(sys.argv) > 2 else 768
    nbase = int(sys.argv[sys.argv.index("--nbase") + 1]) if "--nbase" in sys.argv else 200_000

    tr, te = load(prefix, dim, nbase)
    tr, te = normalize(tr), normalize(te)
    print(f"\n  {prefix}: base(sample)={tr.shape} test={te.shape}  dim={dim}")

    rng = np.random.default_rng(7)
    qs = rng.choice(te.shape[0], min(NQ, te.shape[0]), replace=False)
    # 精确 top-10（样本内 GT）
    exact = []
    for q in qs:
        s = tr @ te[q]
        exact.append(set(np.argpartition(-s, TOP_K)[:TOP_K].tolist()))

    gap = []
    for q in qs[: min(64, len(qs))]:
        s = tr @ te[q]
        o = np.argsort(-s, kind="stable")
        gap.append(float(s[o[TOP_K - 1]] - s[o[TOP_K]]))
    idx = rng.integers(0, tr.shape[0], (20_000, 2))     # ⚠️ 别对 tr 再索引一次（会把 (N,2) 变成 (N,2,dim)）
    cos = np.einsum("ij,ij->i", tr[idx[:, 0]], tr[idx[:, 1]])
    print(f"  随机对 cos = {cos.mean():.4f}±{cos.std():.4f}   "
          f"GT10−GT11 = {np.mean(gap):.5f}（越大越好找）")

    lo, hi = tr.min(axis=0), tr.max(axis=0)
    rows = []
    print(f"\n  {'bits/维':>8} {'码内存/向量':>12} {'码 top-10 ∩ GT':>16} {'码 top-ef→精排 ∩ GT':>20}")
    for bits in BITS:
        if bits >= 16:
            base_c, qry_c = tr, te[qs]
        else:
            base_c, qry_c = uniform_code(tr, lo, hi, bits), uniform_code(te[qs], lo, hi, bits)
        h10 = pef = 0
        for i, q in enumerate(qs):
            s = base_c @ qry_c[i]
            t10 = np.argpartition(-s, TOP_K)[:TOP_K]
            h10 += len(set(t10.tolist()) & exact[i])
            cand = np.argpartition(-s, EF)[:EF]
            sims = tr[cand] @ te[q]                      # 用**原始**向量精排
            top = cand[np.argsort(-sims, kind="stable")[:TOP_K]]
            pef += len(set(top.tolist()) & exact[i])
        den = len(qs) * TOP_K
        mb = dim * bits / 8 / 2**20
        rows.append({"bits": bits, "code_mib_per_vec": mb,
                     "top10": h10 / den * 100, "topef": pef / den * 100})
        tag = "（= 原始 f32 上界）" if bits >= 16 else ""
        print(f"  {bits:>8} {mb:>11.4f} MiB {h10 / den * 100:>15.2f}% {pef / den * 100:>19.2f}% {tag}")

    out = {"prefix": prefix, "dim": dim, "nbase": int(tr.shape[0]), "nq": len(qs),
           "cos_mean": float(cos.mean()), "cos_std": float(cos.std()),
           "gap_10_11": float(np.mean(gap)), "ef": EF, "rows": rows}
    (ROOT / "results" / "t2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "t2" / f"bit_budget_{prefix}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] results/t2/bit_budget_{prefix}.json")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2（修订版）—— 复现论文的 *Practical Compatibility Test*，并测它对**样本量**与**度量选择**的依赖。

# 为什么
已发表版本（PVLDB Vol. 20, 2027；arXiv `2605.02171`）给出的部署判据是：
> 对约 **10K 个样本向量**计算「**BQ 排序 vs float32 排序的 brute-force top-K 重叠率**」；
> **>~50% ⇒ 很可能兼容 BQ-native 图构建；<50% ⇒ 更安全的是 float32 索引**。

P1（`p1-snr-predictor-result.md`）已发现该判据**未指明用哪一个 BQ 度量**，而本引擎有两个
（`weighted` 建图 / `cheap` 查询 L0，`quiver.rs:1272-1281`），在无结构数据上二者相差 20×。
本脚本把这两件事都变成可测的：

1. **样本量依赖**：`S ∈ {10_000, 100_000, 全量}`。注意 10K 子样本上的 top-10 检索**比 1M 上容易得多**
   ⇒ 探针值会随 S 单调上升 ⇒ 若论文的 50% 阈值在 S=10K 上不再能分开"崩塌档"与"竞争档"，
   则该判据的**协议依赖性**是一个具体可报的缺陷。
2. **度量歧义**：`weighted` 与 `cheap` 各算一遍，报告二者是否给出**相反**的 verdict。

# 口径（严格照论文）
对每个数据集、每个 S：
- 取确定性随机子样本 `idx`（|idx| = S）；
- 对每个查询：**在同一样本内**分别取 `float32` 的 top-10 与**码**的 top-10，算重叠率；
- 跨查询求均值得探针值（%）。
⇒ **两侧都在同一子样本内排序**，这正是论文 "BQ 排序 vs float32 排序" 的字面含义。
另附**全局口径**一列（码 top-10 在全量内 vs 数据集自带 GT），用于与 P1 的 `code_only_top10_*` 对拍。

# 预注册判据（先写死，再跑）
- **P2-1**：`cheap` 度量、`S=10K` 的探针值与 `R@10@ef=64` 的 Spearman ρ **≥ 0.9**；
- **P2-2**：`S=10K` 上必须能用 **50% 阈值**把"崩塌档"（论文 <15%）与"竞争档"（论文 >88%）**完全分开**；
- **P2-3**（事后探索）：`weighted` 与 `cheap` 是否对任一数据集给出**相反的 50% verdict**；
- **P2-4**（事后探索）：探针值随 S 的上升幅度（`S=10K → 全量`），用于量化协议依赖。

# 守卫
- 全局口径那列必须复现 P1 的 `code_only_top10_{w,c}_pct`（差 ≤2pp）——否则本脚本的样本/索引处理有误；
- `S = 全量` 时"样本内 GT" 与"数据集 GT" 应当近似一致（报告二者的交集率作为交叉检查）。

用法:
    & .venv\\Scripts\\python.exe scripts\\research\\compat_probe_scaling.py
    & .venv\\Scripts\\python.exe scripts\\research\\compat_probe_scaling.py --report
    & .venv\\Scripts\\python\\python.exe scripts\\research\\compat_probe_scaling.py cohere gist960
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bq2_code_ceiling import bq2_planes, l2_normalize_inplace  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "t2" / "gist960_collapse"
OUT_JSON = OUT_DIR / "compat_probe_scaling.json"

# (前缀, 维数, 论文 Table 11 的 R@10@ef=64 或本仓实测, 论文分组, 备注)
DATASETS = [
    ("dbpedia3072", 3072, None, "竞争档", "论文 95.65（未下载）"),
    ("cohere",       768, 94.63, "竞争档", "论文 95.13（Δ−0.50）"),
    ("dummy",          0, None, "—", "占位（见 filter）"),
    ("glove100",     100, 32.82, "可用档", "论文 32.08（Δ+0.74）"),
    ("sift128",      128, 15.77, "崩塌档", "论文 14.85（Δ+0.92）"),
    ("gist960",      960,  2.10, "崩塌档", "论文 2.01（Δ+0.09）"),
    ("gauss960",     960,  0.41, "崩塌档", "T-ctrl 各向同性（≈论文 Random-Sphere 0.40）"),
    ("sphere",       768,  0.48, "崩塌档", "论文 Random-Sphere 0.40（Δ+0.08，仓库生成器）"),
    ("random",       768, 43.60, "可用档", "论文 Synthetic-LR 41.76（Δ+1.84，仓库生成器）"),
    ("gist960c",     960, 39.74, "—", "去均值（本会话）"),
    ("sift128c",     128, 30.64, "—", "去均值（本会话）"),
]
DATASETS = [d for d in DATASETS if d[0] != "dummy" and (ROOT / f"{d[0]}_train.f32").exists()]

S_LIST = (10_000, 100_000, 1_000_000)
NQ = 200
TOP_K = 10
QBATCH = 16
RNG_SEED = 20260917


def spearman(x, y):
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    def rank(v):
        order = np.argsort(v, kind="stable")
        r = np.empty_like(v)
        r[order] = np.arange(len(v), dtype=np.float64)
        _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
        if (cnt > 1).any():
            sums = np.zeros_like(cnt, dtype=np.float64)
            np.add.at(sums, inv, r)
            r = (sums / cnt)[inv]
        return r

    rx, ry = rank(x) - rank(x).mean(), rank(y) - rank(y).mean()
    den = np.sqrt((rx * rx).sum() * (ry * ry).sum())
    return float((rx * ry).sum() / den) if den > 0 else float("nan")


def probe(prefix, dim, recall, group, note, rng):
    print(f"\n{'=' * 92}\n  {prefix}  dim={dim}  R@10@ef=64="
          f"{'—' if recall is None else f'{recall:.2f}%'}  [{group}]  {note}\n{'=' * 92}")
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    gt_all = np.fromfile(ROOT / f"{prefix}_groundtruth.i32", dtype=np.int32)
    n, nq_all = tr.shape[0], te.shape[0]
    gt = gt_all.reshape(nq_all, -1)[:, :TOP_K]
    l2_normalize_inplace(tr, dim)
    l2_normalize_inplace(te, dim)

    pos, strong = bq2_planes(tr)
    P = pos.astype(np.float32)
    S = strong.astype(np.float32)
    W = (2.0 * P - 1.0) * (1.0 + S)
    rs = P.sum(1) + S.sum(1)
    qpos, qstrong = bq2_planes(te)
    Pt, St = qpos.astype(np.float32), qstrong.astype(np.float32)
    Wt = (2.0 * Pt - 1.0) * (1.0 + St)
    rq = Pt.sum(1) + St.sum(1)

    qs = rng.choice(nq_all, min(NQ, nq_all), replace=False)
    out = {"prefix": prefix, "dim": dim, "recall_ef64": recall, "paper_group": group,
           "note": note, "n_train": int(n), "probe": {}, "global_full": {},
           "insample_vs_datasetGT_pct": None}

    for S_ in S_LIST:
        if S_ > n:
            continue
        idx = np.sort(rng.choice(n, S_, replace=False))
        trs, Ps, Ss, Ws, rss = tr[idx], P[idx], S[idx], W[idx], rs[idx]
        hit = {"w": 0, "c": 0}
        hit_global = {"w": 0, "c": 0}
        inter_dataset = 0
        for b0 in range(0, len(qs), QBATCH):
            qb = qs[b0 : b0 + QBATCH]
            TC = trs @ te[qb].T
            SW = Ws @ Wt[qb].T
            SC = -(rss[:, None] + rq[qb][None, :]
                   - 2.0 * ((Ps @ Pt[qb].T) + (Ss @ St[qb].T)))
            for bi, q in enumerate(qb):
                gsample = idx[np.argpartition(-TC[:, bi], TOP_K)[:TOP_K]]
                inter_dataset += len(set(gsample.tolist()) & set(gt[q].tolist()))
                for key, sc in (("w", SW[:, bi]), ("c", SC[:, bi])):
                    t = idx[np.argpartition(-sc, TOP_K)[:TOP_K]]
                    hit[key] += len(set(t.tolist()) & set(gsample.tolist()))
                    hit_global[key] += len(set(t.tolist()) & set(gt[q].tolist()))
            del TC, SW, SC
        den = len(qs) * TOP_K
        out["probe"][f"S={S_}"] = {k: hit[k] / den * 100 for k in ("w", "c")}
        if S_ == 1_000_000 or S_ == n:
            out["global_full"] = {k: hit_global[k] / den * 100 for k in ("w", "c")}
            out["insample_vs_datasetGT_pct"] = inter_dataset / den * 100
        print(f"  S={S_:>9,}  探针（样本内 top-10 重叠）: weighted {hit['w'] / den * 100:6.2f}%"
              f" | cheap {hit['c'] / den * 100:6.2f}%   "
              f"（全局口径 w {hit_global['w'] / den * 100:6.2f}% / c {hit_global['c'] / den * 100:6.2f}%）")
        del trs, Ps, Ss, Ws, rss
    if out["global_full"]:
        print(f"  交叉检查：全量时'样本内 f32 top-10' ∩ '数据集 GT top-10' = "
              f"{out['insample_vs_datasetGT_pct']:.2f}%（接近 100% ⇒ 样本内 GT 与数据集 GT 一致）")
    return out


def evaluate(rows):
    rows = sorted(rows, key=lambda r: -(r["recall_ef64"] or 0))
    keys = [f"S={s}" for s in S_LIST]
    print(f"\n{'=' * 108}\n  论文探针（样本内 top-10 重叠率，%）随样本量 S 的变化\n{'=' * 108}")
    print("| 数据集 | dim | R@10@ef=64 | 论文分组 | " +
          " | ".join(f"{k} (w/c)" for k in keys) + " | 全局口径 w/c |")
    print("|---|---|---|---|" + "---|" * (len(keys) + 1))
    for r in rows:
        cells = []
        for k in keys:
            p = r["probe"].get(k)
            cells.append("—" if not p else f"{p['w']:.2f} / {p['c']:.2f}")
        g = r["global_full"]
        rec = "—" if r["recall_ef64"] is None else f"{r['recall_ef64']:.2f}%"
        gl = "—" if not g else f"{g['w']:.2f} / {g['c']:.2f}"
        print(f"| {r['prefix']} | {r['dim']} | {rec} | {r['paper_group']} | "
              + " | ".join(cells) + f" | {gl} |")

    print(f"\n  ── 秩相关 ρ(探针, R@10@ef=64) ──")
    have = [r for r in rows if r["recall_ef64"] is not None]
    for k in keys:
        for m in ("w", "c"):
            sel = [r for r in have if k in r["probe"]]
            if len(sel) >= 3:
                rho = spearman([r["probe"][k][m] for r in sel],
                               [r["recall_ef64"] for r in sel])
                print(f"    {k:<10} {m}  n={len(sel)}  ρ = {rho:+.4f}")
    # 50% 阈值能否分开崩塌档/竞争档
    print(f"\n  ── P2-2：50% 阈值在 S=10K 上能否分开『崩塌档』与『竞争档』 ──")
    for m in ("w", "c"):
        col = [r for r in rows if r["probe"].get("S=10000") and r["paper_group"] in ("崩塌档", "竞争档")]
        col = [r for r in col if r["recall_ef64"] is not None]
        if len(col) >= 2:
            collapse = [r["probe"]["S=10000"][m] for r in col if r["paper_group"] == "崩塌档"]
            compete = [r["probe"]["S=10000"][m] for r in col if r["paper_group"] == "竞争档"]
            ok = (max(collapse) < 50 < min(compete)) if collapse and compete else None
            mx = f"{max(collapse):.2f}%" if collapse else "（无）"
            mn = f"{min(compete):.2f}%" if compete else "（无）"
            print(f"    {m}: 崩塌档 max={mx}  竞争档 min={mn}  ⇒ "
                  f"{'可分' if ok else '不可分（阈值失效）' if ok is not None else '样本不足，无法判定'}")
    # 度量歧义：给低召回行的 verdict
    print(f"\n  ── P2-3：度量歧义（S=10K，低召回行是否被两个度量给出相反 verdict） ──")
    print(f"    {'数据集':<12}{'R@10@ef=64':>12}{'weighted':>10}{'cheap':>10}  verdict 一致？")
    for r in have:
        p = r["probe"].get("S=10000")
        if not p:
            continue
        vw, vc = p["w"] >= 50, p["c"] >= 50
        print(f"    {r['prefix']:<12}{r['recall_ef64']:>11.2f}%{p['w']:>9.2f}%{p['c']:>9.2f}%"
              f"  {'是' if vw == vc else '★ 否（相反）'}")


def _load():
    if not OUT_JSON.exists():
        return {}
    raw = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("rows", {})
    return raw if isinstance(raw, dict) else {r["prefix"]: r for r in raw}


def main():
    if "--report" in sys.argv:
        rows = list(_load().values())
        evaluate(rows)
        print(f"\n  （读自 {OUT_JSON.relative_to(ROOT)}，{len(rows)} 行）")
        return
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")]
    old = _load()
    for prefix, dim, recall, group, note in DATASETS:
        if wanted and prefix not in wanted:
            continue
        rng = np.random.default_rng([RNG_SEED, dim, sum(map(ord, prefix))])
        old[prefix] = probe(prefix, dim, recall, group, note, rng)
    rows = list(old.values())
    rng = np.random.default_rng(RNG_SEED)
    guard(rng, 128)
    guard(rng, 960)
    # ⚠️ 先落盘再评估：`evaluate()` 曾经在"竞争档为空"时抛异常，导致整批结果丢失（K20）
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "protocol": "in-sample top-10 overlap: code-top10 within an S-candidate subsample vs "
                    "float32-top10 within the SAME subsample (paper's Practical Compatibility Test)",
        "S_list": list(S_LIST), "nq": NQ,
        "rows": old,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  结果已写入 {OUT_JSON.relative_to(ROOT)}（{len(rows)} 行）")
    evaluate(rows)


def guard(rng, dim):
    """与 `bq2_code_ceiling.py` 同源的守卫：确认本脚本用的两个分数的恒等式与 `src/index/bq.rs` 一致"""
    from bq2_code_ceiling import ref_cheap, ref_weighted
    n = 512
    a = rng.standard_normal((n, dim), dtype=np.float32)
    b = rng.standard_normal((n, dim), dtype=np.float32)
    a[: n // 2] = np.abs(a[: n // 2])
    b[: n // 2] = np.abs(b[: n // 2])
    l2_normalize_inplace(a, dim)
    l2_normalize_inplace(b, dim)
    pa, sa = bq2_planes(a)
    pb, sb = bq2_planes(b)
    d_cheap = int(np.abs(ref_cheap(pa, sa, pb, sb)
                         - (pa.sum(1) + pb.sum(1) + sa.sum(1) + sb.sum(1)
                            - 2 * ((pa & pb).sum(1) + (sa & sb).sum(1)))).max())
    wa = (2.0 * pa.astype(np.float32) - 1.0) * (1.0 + sa.astype(np.float32))
    wb = (2.0 * pb.astype(np.float32) - 1.0) * (1.0 + sb.astype(np.float32))
    d_w = float(np.abs(ref_weighted(pa, sa, pb, sb, dim)
                       - (4 * dim - np.einsum("ij,ij->i", wa, wb))).max())
    print(f"  守卫 dim={dim}: |ΔHamming|={d_cheap}  |Δ<w,w>|={d_w}  "
          f"{'PASS' if d_cheap == 0 and d_w == 0 else 'FAIL'}")
    if d_cheap != 0 or d_w != 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

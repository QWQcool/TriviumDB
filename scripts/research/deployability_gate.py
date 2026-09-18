"""D1 —— 可部署性判据链（deployability gate）：**全部量都在建索引之前几秒钟可算**

# 为什么需要
论文把"适用性"交给一个**未指定度量**、**样本量敏感 6.8×** 的探针（P2/U13），
对失败数据只给"改用 float32"这一条出路；而我们先前的两次"单一预测器"尝试都已证伪（P1/P2）。
本脚本把已有零件合成一条**分工明确**的判据链（每一步都不需要建索引）：

    ① 符号平面是否死了？   sign_info / sign_info_min（逐坐标负值比的熵，bit）
                           ≈0 ⇒ 编码退化 ⇒ **强制去均值**（论文未提出此修复，见 N3）
    ② 移位量够不够？       ‖μ‖（归一化 train 的均值范数）+ 实际余量（100 − r@ef_s）
                           ⇒ **建议去均值**（预期小-中收益；cohere 型已到天花板则中性）
    ③ 任务+码能不能分辨？  `min(probe_weighted, probe_cheap)`（码 top-10 ∩ 数据集 GT）
                           < 50% ⇒ **改用 float32**（论文判据的修好版：双度量取最弱）
    ④ 会不会真赢？         ★ **本链不预测**。competitiveness 需要竞品曲线（D2）——
                           我们的实测是"有竞品数据的 3/4 档被 HNSW 支配"。

# 公式来源（**不是本脚本即兴写的**）
`bq2_planes` / cheap / weighted 三式**逐字沿用** `bq2_code_ceiling.py` 里已被守卫验证过的版本
（该脚本的 `verify_identities()` 断言"分析式 vs 位运算最大差 = 0"且守卫比对的是 `src/index/bq.rs`）：

    pos    = v > 0.0                        （严格大于 ⇒ 0 落在**负**半平面）
    strong = |v| > mean(|v|)                （逐向量阈值）
    cheap  : D = (|p_i|+|s_i|) − 2(<p_i,p_q> + <s_i,s_q>)          越小越近
    weighted: S = <w_i, w_q>,  w = (2p−1)·(1+s) ∈ {−2,−1,1,2}      越大越近

# 诚实声明
- ①③ 的阈值落在实测的**宽间隙**上（见输出），不是拟合出来的；② 的规则是**描述性**的，有明确反例
  （cohere：`‖μ‖=0.834` 却中性 ⇒ 规则里显式要求"余量 > 5pp"）。
- 本脚本**只做必要条件的筛查**，不做充分性承诺。
"""
import gc
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "t2" / "deployability_gate.json"
TOP_K, NQ, QPAD_BATCH, EF_REFINE = 10, 200, 64, 128
RNG = np.random.default_rng(20260918)

ARMS = [
    ("gist960", 960), ("gist960k768", 768), ("gist960k512", 512),
    ("gist960k256", 256), ("gist960k128", 128), ("gist960c", 960),
    ("sift128", 128), ("sift128c", 128),
    ("glove100", 100), ("glove100c", 100),
    ("cohere", 768), ("coherec", 768), ("coherek128", 128),
    ("cohere960pad", 960),
    ("wolt_clip", 512), ("wolt_clipc", 512),
    ("random", 768), ("randomc", 768),
    ("sphere", 768), ("spherec", 768),
    ("gauss960", 960), ("gauss960plant", 960),
    # ── N1 ③：论文 Table 11 剩余行（缺文件会自动跳过）──
    ("minilm", 384), ("bge_m3", 1024),
    ("dbpedia_openai", 1536), ("dbpedia_openai_3072", 3072),
]

# `bench_t2_b2_partitioned` 实测 R@10（@ef_s=128 主列, @ef_s=1024 天花板；None=未测）
MEASURED = {
    "gist960": (2.81, 4.38), "gist960k768": (2.84, None), "gist960k512": (2.49, None),
    "gist960k256": (2.08, None), "gist960k128": (1.61, None), "gist960c": (51.96, 79.44),
    "sift128": (21.88, 47.23), "sift128c": (44.16, 85.21),
    "glove100": (45.60, 71.69), "glove100c": (49.01, 73.28),
    "cohere": (97.51, 99.78), "coherec": (97.25, 99.86), "coherek128": (72.30, None),
    "cohere960pad": (97.11, None), "wolt_clip": (77.73, 86.81), "wolt_clipc": (82.19, 89.14),
    "random": (59.08, 92.52), "randomc": (60.28, 94.69),
    "sphere": (0.91, 6.46), "spherec": (1.11, 6.58),
    "gauss960": (0.83, None), "gauss960plant": (100.00, None),
    # N1 ③ 新增（@ef_s=128, @ef_s=1024）
    "minilm": (94.28, 99.47), "bge_m3": (97.76, 99.97),
    "dbpedia_openai": (98.29, 99.79), "dbpedia_openai_3072": (98.16, 99.80),
}


def norm_inplace(a):
    a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    return a


def sign_entropy(tr):
    """逐坐标符号熵 H(p_j)（bit）。pos 位面对第 j 维是**一个全局位** ⇒ 信息量 = mean_j H(p_j)。

    全非负数据 ⇒ 所有 p_j=0 ⇒ H=0 ⇒ pos 平面零信息（论文 Finding 1 的机制）。
    返回 (mean_j H, min_j H, p_j)。
    """
    p = (tr < 0).mean(axis=0).astype(np.float64)
    h = np.zeros_like(p)
    for v in (p, 1.0 - p):                     # H(p) = −p log2 p − (1−p) log2(1−p)
        m = v > 0
        h[m] -= v[m] * np.log2(v[m])
    return float(h.mean()), float(h.min()), p


def cos_std_proxy(tr, n=20_000):
    """随机向量对 cosine 的标准差（与 `dim_axis_separability.py` 同口径）"""
    i = RNG.choice(tr.shape[0], n, replace=False)
    j = RNG.choice(tr.shape[0], n, replace=False)
    return float(np.sum(tr[i] * tr[j], axis=1).std())


def bq2_planes(v):
    """`Bq2Signature::from_vector`：pos = v > 0.0；strong = |v| > mean(|v|)（逐向量）"""
    alpha = np.abs(v).mean(axis=1)
    return v > 0.0, np.abs(v) > alpha[:, None]


def probe(tr, te, gt, qs):
    """两个仪器 × 两个度量，全部 ∩ **数据集 GT**：

    - `top10`  = 论文的**字面定义**（"BQ-ranked Top-10 vs float32 GT"）
    - `topef`  = "码 top-**ef** 候选 → f32 精排 → top-10"，即 P2 里与图召回可比的那个仪器
                 （P2 实测：glove100 `code_oracle@128`=67.79% ↔ bench 71.69%；ρ=+0.95）

    **公式逐字沿用 `bq2_code_ceiling.py` 的已验证版本**（该脚本断言过"分析式 vs 位运算最大差 = 0"）：
        pos = v > 0.0;  strong = |v| > mean(|v|);  w = (2p−1)(1+s) ∈ {−2,−1,1,2}
        cheap    : D = (|p_i|+|s_i|) − 2(<p_i,p_q> + <s_i,s_q>)        升序 = 近
        weighted : S = <w_i, w_q>                                      降序 = 近
    ⚠️ 我曾试图把 `<w_a,w_b>` 拆成 popcount 的组合来省内存，**代数推导错了**
    （`(2p−1)(1+s)` 的两个因子无法那样拆），自检当场抓到（glove100 45.1→29.5）。
    正确做法是**按行分块**物化 P/S/W：内存 O(blk×dim)，数学与已验证版本完全一致。
    """
    n, dim = tr.shape
    ppos, pstrong = bq2_planes(te)
    Pq = ppos[qs].astype(np.float32)
    Sq = pstrong[qs].astype(np.float32)
    Wq = (2.0 * Pq - 1.0) * (1.0 + Sq)
    B = len(qs)
    D = np.empty((n, B), dtype=np.float32)      # 990K×200×4 ≈ 0.8 GB
    Sw = np.empty((n, B), dtype=np.float32)
    blk = max(1, 1_500_000_000 // (dim * 4 * 3))   # 每块的 P/S/W 合计约 1.5 GB
    for b0 in range(0, n, blk):
        b1 = min(b0 + blk, n)
        sub = tr[b0:b1]
        alpha = np.abs(sub).mean(axis=1)
        P = (sub > 0.0).astype(np.float32)
        S = (np.abs(sub) > alpha[:, None]).astype(np.float32)
        W = (2.0 * P - 1.0) * (1.0 + S)
        bias = (P.sum(1) + S.sum(1))[:, None]
        D[b0:b1] = bias - 2.0 * (P @ Pq.T + S @ Sq.T)
        Sw[b0:b1] = W @ Wq.T
        del sub, P, S, W, bias
        gc.collect()

    hit = {k: 0 for k in ("top10_w", "top10_c", "topef_w", "topef_c")}
    for i, q in enumerate(qs):
        for key, arr in (("w", -Sw[:, i]), ("c", D[:, i])):   # 统一升序 = 近
            t10 = np.argpartition(arr, TOP_K)[:TOP_K]
            hit[f"top10_{key}"] += len(set(t10.tolist()) & set(gt[q].tolist()))
            cand = np.argpartition(arr, EF_REFINE)[:EF_REFINE]
            sims = tr[cand] @ te[q]
            top = cand[np.argsort(-sims, kind="stable")[:TOP_K]]
            hit[f"topef_{key}"] += len(set(top.tolist()) & set(gt[q].tolist()))
    del D, Sw
    gc.collect()
    den = len(qs) * TOP_K
    return {k: v / den * 100 for k, v in hit.items()}


def run(prefix, dim):
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    gt = np.fromfile(ROOT / f"{prefix}_groundtruth.i32", dtype=np.int32).reshape(te.shape[0], -1)[:, :TOP_K]
    raw_mu = float(np.linalg.norm(tr.mean(axis=0)))      # 磁盘原始数据的均值范数（诊断归一化与否）
    neg_raw = float((tr < 0).mean())
    norm_inplace(tr)
    norm_inplace(te)
    cos_max = float((te[: min(64, te.shape[0])] @ tr[:200_000].T).max())
    assert cos_max <= 1.0 + 1e-5, f"{prefix}: cosine={cos_max} > 1 ⇒ 归一化漏了"

    sign_info, sign_info_min, p = sign_entropy(tr)
    mu_norm = float(np.linalg.norm(tr.mean(axis=0)))

    qs = RNG.choice(te.shape[0], min(NQ, te.shape[0]), replace=False)
    cos_std = cos_std_proxy(tr)
    sub = tr[:300_000]
    gt1 = gt10 = gap = 0.0
    crowd = []
    for q in qs[: min(100, len(qs))]:
        s = sub @ te[q]
        o = np.argsort(-s, kind="stable")
        gt1 += float(s[o[0]])
        gt10 += float(s[o[TOP_K - 1]])
        g = float(s[o[TOP_K - 1]] - s[o[TOP_K]])
        gap += g
        crowd.append(int(((s > s[o[TOP_K - 1]] - g) & (s <= s[o[TOP_K - 1]])).sum()))
    nq_probe = min(100, len(qs))
    gt1, gt10, gap = gt1 / nq_probe, gt10 / nq_probe, gap / nq_probe
    del sub
    gc.collect()

    pr = probe(tr, te, gt, qs)
    r128, r1024 = MEASURED.get(prefix, (None, None))
    rec = {
        "prefix": prefix, "dim": dim, "n": int(tr.shape[0]), "nq": int(te.shape[0]),
        "raw_mu_norm": raw_mu, "mu_norm": mu_norm, "disk_normalized": raw_mu < 2.0,
        "neg_frac_raw": neg_raw, "sign_info": sign_info, "sign_info_min": sign_info_min,
        "neg_frac": float(p.mean()),
        "gt1": gt1, "gt10": gt10, "gap_10_11": gap, "cos_std": cos_std,
        "separability": (gt1 - gt10) / cos_std if cos_std else float("nan"),
        "crowd_med": float(np.median(crowd)), "crowd_mean": float(np.mean(crowd)),
        "probe_top10_w": pr["top10_w"], "probe_top10_c": pr["top10_c"],
        "probe_topef_w": pr["topef_w"], "probe_topef_c": pr["topef_c"],
        "probe_top10_min": min(pr["top10_w"], pr["top10_c"]),
        "probe_topef_min": min(pr["topef_w"], pr["topef_c"]),
        "measured_r128": r128, "measured_r1024": r1024,
    }
    headroom = 100.0 - r128 if r128 is not None else None
    if sign_info < 0.2:                       # ★ 用**均值**：min 会对 cohere 这类健康集误报
        verdict = "① 强制去均值（符号平面整体退化）"
    elif mu_norm >= 0.3 and (headroom is None or headroom > 5.0):
        verdict = "② 建议去均值（移位量可观且有余量）"
    elif rec["probe_topef_min"] < 50.0:       # ★ 用与图召回可比的仪器（P2 的 code_oracle）
        verdict = "③ 改用 float32（码判别力不足）"
    else:
        verdict = "④ BQ-native 可用（竞争力另需竞品曲线）"
    rec["verdict"] = verdict
    rec["headroom_pp"] = headroom
    del tr, te
    gc.collect()
    return rec


def main():
    rows = []
    # `python deployability_gate.py glove100 gist960` ⇒ 只跑指定臂（产物仍增量合并进 JSON）
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    for prefix, dim in ARMS:
        if want and prefix not in want:
            continue
        if not (ROOT / f"{prefix}_train.f32").exists():
            print(f"  [跳过] {prefix} 缺文件")
            continue
        r = run(prefix, dim)
        rows.append(r)
        m = "—" if r["measured_r128"] is None else f"{r['measured_r128']:5.2f}%"
        print(f"  {prefix:<16} dim={dim:<5} sign_info={r['sign_info']:.3f}"
              f"/{r['sign_info_min']:.3f} ‖μ‖={r['mu_norm']:.3f}"
              f" 可分={r['separability']:+.3f} probe10={r['probe_top10_min']:5.1f}%"
              f" probe_ef={r['probe_topef_min']:5.1f}% 实测@128={m}  {r['verdict']}")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 112}\n  markdown\n{'=' * 112}")
    print("| 臂 | dim | sign_info mean/min | ‖μ‖ | 可分性 | probe10 | probe_ef | 实测 R@10@128 | 判据 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        m = "—" if r["measured_r128"] is None else f"{r['measured_r128']:.2f}%"
        print(f"| {r['prefix']} | {r['dim']} | {r['sign_info']:.3f}/{r['sign_info_min']:.3f} "
              f"| {r['mu_norm']:.3f} | {r['separability']:+.3f} "
              f"| {r['probe_top10_min']:.1f}% | {r['probe_topef_min']:.1f}% | {m} "
              f"| {r['verdict']} |")
    print(f"\n[OK] 写出 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

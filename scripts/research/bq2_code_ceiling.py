#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BQ2 码的**分辨力探针** —— 把"召回崩塌"分解为「码」与「图导航」。

# 为什么需要这个探针
`bench_t2_b2_partitioned` 的 R@10 是**图导航 + f32 精排**的联合结果，
无法回答"到底是码不行，还是图不行"。本探针用**全扫描**替代图：

    code_oracle@ef = |top-10 (全局按码取 top-ef 候选 → f32 精排) ∩ 真 GT top-10| / 10

⚠️ **诚实声明**：`code_oracle@ef` **不是**真算法的严格上界——真算法只在"已发现集合"
内按码取 top-ef，而已发现集合 ⊆ 全集，故它**可能超过**本值（glove100 实测即如此：
oracle@1024 = 67.79% 而 bench = 71.69%）。它的正确定位是**码的 oracle 分辨力**：
"若候选池就是码判定的全局最优 ef 个，还剩多少召回"。bench 贴近或超过它，
说明**瓶颈是码而非图**；bench 远低于它，说明图导航（或 α 剪枝）也有责任。

# 两条距离口径（`src/index/bq.rs`）
1. **weighted**（`bq2_distance_raw`，6 类权重）：建图束搜索 `beam_search_l0_locked`
   与 `vamana_select` 用它。
2. **cheap**（`distance_to_sig_cheap`，pos/strong 两个平面的纯 Hamming）：
   **查询期** `beam_search_l0_impl` 用它。

两者都必须被本脚本精确复现——这是全部结论的地基，故脚本自带**可证伪守卫**：
在随机 512 对上，用 bool 展开的位运算逐位实现 6 类权重公式，断言
   (a) cheap = popcount(pos_a^pos_b) + popcount(strong_a^strong_b)
   (b) weighted = 4*dim − <w_a, w_b>,  w = (2*pos−1)*(1+strong)
      且 weighted == 6 类权重的逐位展开
守卫失败则本脚本的所有数字作废（exit 1）。

# 关键分析式（由 (b) 推出）
    distance_weighted = 4*dim − <w_a, w_b>,   w ∈ {−2,−1,+1,+2}^dim
⇒ 全扫描排序可用一次 f32 GEMM 精确算出（1000 查询 × 1M × dim 约 1e12 FLOP）。
   cheap 同理，用 Hamming 的展开式 Ham(p,q|s,t) = |p|+|q|+|s|+|t| − 2(<p,q>+<s,t>)。

# ⚠️ 全非负数据（GIST / SIFT）的退化
若 x ≥ 0 逐维成立，则 `Bq2Signature::from_vector` 的 pos 位**恒为 1**
⇒ pos 平面零信息 ⇒
  - cheap 口径只剩 strong 一个平面（**等效 1 bit/维**）
  - weighted 口径的 w = 1+strong ∈ {1,2}^dim（全正）⇒
    <w_a,w_b> = dim + |h_a| + |h_b| + <h_a,h_b>
    其中 |h| = strong 位计数，是**与查询无关的候选偏置**（纯噪声项）。
脚本会量化这一项（strong 密度的跨向量离散度）。

用法:
    & .venv\\Scripts\\python.exe scripts\\research\\bq2_code_ceiling.py
    & .venv\\Scripts\\python.exe scripts\\research\\bq2_code_ceiling.py sift128 gist960
"""

import gc
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

OUT_JSON = Path(__file__).resolve().parents[2] / "results" / "t2" / "gist960_collapse" / "code_oracle.json"

# (前缀, 维数, 说明)
ALL_DATASETS = [
    ("sift128", 128, "euclidean→cosine(重算)"),
    ("cohere", 768, "官方 GT"),
    ("gist960", 960, "euclidean→cosine(重算)"),
    ("glove100", 100, "angular(原生 GT)"),
    # ── gist960 崩塌根因实验的派生集（见 gist960_collapse_prepare.py） ──
    ("gauss960", 960, "T-ctrl 随机各向同性高斯"),
    ("gauss960plant", 960, "T-plant 植入真近邻"),
    ("gist960c", 960, "T-center 去均值"),
    ("sift128c", 128, "T-center SIFT"),
    ("cohere960pad", 960, "T-pad 零填充"),
    ("gist960k768", 768, "T-sweep 768"),
    ("gist960k512", 512, "T-sweep 512"),
    ("gist960k256", 256, "T-sweep 256"),
    ("gist960k128", 128, "T-sweep 128"),
    ("coherek128", 128, "cohere sweep 128"),
]

NQ_PROBE = 1000       # 用于全扫描的查询数（gist960 原生就是 1000）
QPAD_BATCH = 32       # 查询批大小（GEMM 输出 N×B）
EF_LIST = (128, 1024)  # 与 bench 的 ef_s 关键档一致
GUARD_PAIRS = 512     # 守卫抽样对数
RNG_SEED = 20260917
TOP_K = 10

# 冻结值（口径守卫）：`bench_t2_b2_partitioned` 实测 R@10 @ef_s=128
FROZEN_RECALL = {
    "cohere": 97.52,
    "sift128": 21.83,
    "gist960": 2.79,
    "glove100": 45.60,
    # 本会话实测
    "gaussian960": 0.83,
    "gauss960plant": 100.00,
    "gist960c": 51.96,
    "sift128c": 44.16,
    "cohere960pad": 97.11,
    "gist960k768": 2.84,
    "gist960k512": 2.49,
    "gist960k256": 2.08,
    "gist960k128": 1.61,
    "coherek128": 72.30,
}


# ══════════════════════════════════════════════════════════════════
#  精确参考实现（bool 逐位，只有 GUARD_PAIRS 对，成本可忽略）
# ══════════════════════════════════════════════════════════════════

def bq2_planes(v):
    """复现 `Bq2Signature::from_vector`：返回 (pos, strong) 两个 bool 平面。

    pos    = v > 0.0
    strong = |v| > alpha,  alpha = mean(|v|)   （逐向量）
    """
    alpha = np.abs(v).mean(axis=1)
    pos = v > 0.0
    strong = np.abs(v) > alpha[:, None]
    return pos, strong


def ref_cheap(pos_a, strong_a, pos_b, strong_b):
    """精确 cheap 口径（`distance_to_sig_cheap`）"""
    return (
        np.bitwise_count(np.packbits(pos_a, axis=1) ^ np.packbits(pos_b, axis=1)).sum(-1)
        + np.bitwise_count(
            np.packbits(strong_a, axis=1) ^ np.packbits(strong_b, axis=1)
        ).sum(-1)
    ).astype(np.int64)


def ref_weighted(pos_a, strong_a, pos_b, strong_b, dim):
    """精确 weighted 口径（`bq2_distance_raw` 的 6 类权重，逐位展开）"""
    same = ~(pos_a ^ pos_b)
    both_strong = strong_a & strong_b
    one_strong = strong_a ^ strong_b
    both_weak = ~(strong_a | strong_b)
    dot = (
        4 * (same & both_strong).sum(-1)
        - 4 * (~same & both_strong).sum(-1)
        + 2 * (same & one_strong).sum(-1)
        - 2 * (~same & one_strong).sum(-1)
        + 1 * (same & both_weak).sum(-1)
        - 1 * (~same & both_weak).sum(-1)
    )
    assert dot.min() >= -4 * dim and dot.max() <= 4 * dim, "6 类权重 dot 越界"
    return (4 * dim - dot).astype(np.int64)


def w_vector(pos, strong):
    """分析式 w = (2*pos−1)*(1+strong) ∈ {−2,−1,+1,+2}"""
    return (2.0 * pos.astype(np.float32) - 1.0) * (1.0 + strong.astype(np.float32))


# ══════════════════════════════════════════════════════════════════

def l2_normalize_inplace(a, dim):
    n = a.shape[0]
    b = a.reshape(n, dim)
    norms = np.linalg.norm(b, axis=1)
    b *= (1.0 / np.maximum(norms, 1e-12))[:, None]
    return norms


def guard(rng, dim):
    """可证伪守卫：在随机对上验证两条分析式与 6 类权重公式逐位一致"""
    print(f"\n{'=' * 70}\n  守卫：分析式 vs 6 类权重公式（{GUARD_PAIRS} 对，dim={dim}）\n{'=' * 70}")
    a = rng.standard_normal((GUARD_PAIRS, dim), dtype=np.float32)
    b = rng.standard_normal((GUARD_PAIRS, dim), dtype=np.float32)
    # 混入非负向量（复现 GIST/SIFT 的退化情形）
    a[: GUARD_PAIRS // 2] = np.abs(a[: GUARD_PAIRS // 2])
    b[: GUARD_PAIRS // 2] = np.abs(b[: GUARD_PAIRS // 2])
    l2_normalize_inplace(a, dim)
    l2_normalize_inplace(b, dim)

    pa, sa = bq2_planes(a)
    pb, sb = bq2_planes(b)

    cheap_ref = ref_cheap(pa, sa, pb, sb)
    # 展开式：Ham = |p_a|+|p_b|+|s_a|+|s_b| − 2(<p_a,p_b>+<s_a,s_b>)
    cheap_ana = (
        pa.sum(1)
        + pb.sum(1)
        + sa.sum(1)
        + sb.sum(1)
        - 2 * ((pa & pb).sum(1) + (sa & sb).sum(1))
    )
    d_cheap = np.abs(cheap_ref - cheap_ana).max()

    weighted_ref = ref_weighted(pa, sa, pb, sb, dim)
    wa, wb = w_vector(pa, sa), w_vector(pb, sb)
    weighted_ana = 4 * dim - np.einsum("ij,ij->i", wa, wb)
    d_weighted = np.abs(weighted_ref - weighted_ana).max()

    # 退化情形的恒等式：全非负 ⇒ w ∈ {1,2}，<w_a,w_b> = dim + |h_a| + |h_b| + <h_a,h_b>
    ha, hb = sa.sum(1), sb.sum(1)
    ident = dim + ha + hb + (sa & sb).sum(1)
    nonneg = pa.all(1)
    d_ident = (
        np.abs(weighted_ana[nonneg] - (4 * dim - ident[nonneg])).max()
        if nonneg.any()
        else 0.0
    )

    print(f"  (a) cheap  分析式 vs 位运算  最大差 = {d_cheap}")
    print(f"  (b) weighted 分析式 vs 6 类权重 最大差 = {d_weighted}")
    print(f"  (c) 全非负退化恒等式（{int(nonneg.sum())} 对）最大差 = {d_ident}")
    ok = d_cheap == 0 and d_weighted == 0 and d_ident == 0
    print(f"  守卫总判定: {'PASS ⇒ 分析式与 src/index/bq.rs 逐位一致' if ok else 'FAIL ⇒ 结论作废'}")
    if not ok:
        sys.exit(1)


def plane_info(bits, rng, n_sample=1500):
    """位平面携带多少信息：返回 (位密度, 随机对 Hamming 率, 恒定向量占比)

    随机对 Hamming 率 = 平均 popcount(a^b)/dim。0 表示该平面在所有向量上恒定（零信息），
    0.5 表示最大不确定性。
    """
    n = bits.shape[0]
    idx = rng.choice(n, min(n_sample, n), replace=False)
    sub = bits[idx]
    packed = np.packbits(sub, axis=1)
    d = np.bitwise_count(packed[:, None, :] ^ packed[None, :, :]).sum(-1)
    iu = np.triu_indices(len(idx), k=1)
    ham = float(d[iu].mean() / bits.shape[1])
    return float(bits.mean()), ham, float(bits.all(1).mean())


def probe(prefix, dim, rng):
    print(f"\n{'=' * 70}\n  {prefix}  dim={dim}  BQ2 码分辨力\n{'=' * 70}")
    tr = np.fromfile(f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    gt_flat = np.fromfile(f"{prefix}_groundtruth.i32", dtype=np.int32)
    n, nq_all = tr.shape[0], te.shape[0]
    cols = gt_flat.size // nq_all
    gt = gt_flat.reshape(nq_all, cols)[:, :TOP_K]
    # 归一化前先记录符号统计（归一化不改变符号）
    neg_frac = float((tr < 0).mean())
    zero_frac = float((tr == 0).mean())

    l2_normalize_inplace(tr, dim)
    l2_normalize_inplace(te, dim)

    # 口径守卫：归一化后 cosine 必须 ≤ 1（上轮踩过的坑）
    q0 = te[: min(nq_all, 64)]
    cos_max = float((q0 @ tr[:200_000].T).max())
    assert cos_max <= 1.0 + 1e-5, f"cosine={cos_max} > 1 ⇒ 归一化漏了"
    print(f"  口径守卫 cosine≤1: max={cos_max:.6f} PASS")

    pos, strong = bq2_planes(tr)
    ppos, pstrong = bq2_planes(te)
    h_tr = strong.sum(1).astype(np.float32)

    pos_dens, pos_ham, pos_const = plane_info(pos, rng)
    str_dens, str_ham, _ = plane_info(strong, rng)
    dens = h_tr / dim
    print(f"  负值占比 = {neg_frac:.6f}   零值占比 = {zero_frac:.6f}")
    print(
        f"  pos  平面: 位密度={pos_dens:.4f}  随机对 Hamming 率={pos_ham:.4f}"
        f"  （0=零信息，0.5=满信息）"
    )
    print(f"  strong 平面: 位密度={str_dens:.4f}  随机对 Hamming 率={str_ham:.4f}")
    print(f"  全严格正（无零无负）向量占比 = {pos_const:.4f}")
    print(f"  strong 位计数 |h| = {float(h_tr.mean()):.1f} ± {float(h_tr.std()):.1f}"
          f"  (min {float(h_tr.min()):.0f} / max {float(h_tr.max()):.0f})")
    # gist960 有 10 行全零 ⇒ 必须 epsilon 兜底，否则 nan（K14）
    aniso = float((np.abs(tr).sum(1) / np.maximum(np.linalg.norm(tr, axis=1), 1e-12)).mean())
    print(f"  各向异性 ‖x‖₁/‖x‖₂ = {aniso:.3f}  (√dim={np.sqrt(dim):.3f})")
    # 有效 bit/维 ≈ 1 + pos 平面是否携带信息（pos 零信息 ⇒ 2-bit 退化为 1-bit）
    eff_bits = 1.0 + (1.0 if pos_ham > 0.02 else 0.0)
    print(f"  ★ 有效 bit/维 ≈ {eff_bits:.1f}")

    nq = min(NQ_PROBE, nq_all)
    qt = te[:nq]
    gtq = gt[:nq]

    # ── 两个口径的全扫描矩阵（f32 GEMM，分析式精确等价） ──
    Ptr = pos.astype(np.float32)
    Str = strong.astype(np.float32)
    Pq = ppos[:nq].astype(np.float32)
    Sq = pstrong[:nq].astype(np.float32)

    cheap_rank_recall = {ef: 0 for ef in EF_LIST}
    weighted_rank_recall = {ef: 0 for ef in EF_LIST}
    cheap_top10 = 0
    weighted_top10 = 0

    Wtr = None
    Wq = None

    for b0 in range(0, nq, QPAD_BATCH):
        b1 = min(b0 + QPAD_BATCH, nq)
        B = b1 - b0
        Pq_b, Sq_b = Pq[b0:b1], Sq[b0:b1]

        # cheap Hamming 展开式
        bitp = Ptr @ Pq_b.T          # (n, B)  <p_i, p_q>
        bits = Str @ Sq_b.T          # (n, B)  <s_i, s_q>
        # D_i = |p_i|+|s_i| + const_q − 2*(bitp+bits)
        bias = (Ptr.sum(1) + Str.sum(1))[:, None]      # |p_i|+|s_i|，与查询无关的偏置
        D_cheap = bias - 2.0 * (bitp + bits)           # 排序等价（升序 = 距离升序）
        del bitp, bits

        # weighted: distance = 4*dim − <w_i, w_q>，排序降序 = 相似升序
        if Wtr is None:
            Wtr = (2.0 * Ptr - 1.0) * (1.0 + Str)
            Wq = (2.0 * Pq - 1.0) * (1.0 + Sq)
        S_mat = Wtr @ Wq[b0:b1].T

        for qi in range(B):
            g = gtq[b0 + qi]
            d = D_cheap[:, qi]                 # 越小越近
            s = S_mat[:, qi]                   # 越大越近
            for ef in EF_LIST:
                # 排序键统一为「越小越近」：cheap 用 d，weighted 用 −s
                for key, acc in ((d, cheap_rank_recall), (-s, weighted_rank_recall)):
                    cand = np.argpartition(key, ef)[:ef]
                    cand = cand[np.argsort(key[cand], kind="stable")]
                    # f32 精排（与 `search_flat` 的第二段一致）
                    sims = tr[cand] @ qt[b0 + qi]
                    top = cand[np.argsort(-sims, kind="stable")[:TOP_K]]
                    acc[ef] += int(np.isin(top, g).sum())
            # 无精排：直接取码 top-10
            c1 = np.argpartition(d, TOP_K)[:TOP_K]
            w1 = np.argpartition(-s, TOP_K)[:TOP_K]
            cheap_top10 += int(np.isin(c1, g).sum())
            weighted_top10 += int(np.isin(w1, g).sum())
        del D_cheap, S_mat
        gc.collect()

    denom = nq * TOP_K
    fr = FROZEN_RECALL.get(prefix)
    frozen_txt = f"（bench 实测 {fr:.2f}% @ef_s=128）" if fr else ""
    if fr:
        delta = cheap_rank_recall[128] / denom * 100 - fr
        print(
            f"  ★ cheap 口径 code_oracle@128 = {cheap_rank_recall[128] / denom * 100:6.2f}%"
            f"   vs bench R@10 = {fr:6.2f}%   差 = {delta:+.2f}pp"
        )
    for ef in EF_LIST:
        print(
            f"  code_oracle@{ef:<4} cheap = {cheap_rank_recall[ef] / denom * 100:6.2f}%"
            f"   weighted = {weighted_rank_recall[ef] / denom * 100:6.2f}%"
        )
    print(
        f"  （仅码、无 f32 精排）top-10 cheap = {cheap_top10 / denom * 100:.2f}%"
        f"   weighted = {weighted_top10 / denom * 100:.2f}%"
    )

    result = {
        "prefix": prefix,
        "dim": dim,
        "n": int(n),
        "nq_used": int(nq),
        "neg_frac": neg_frac,
        "zero_frac": zero_frac,
        "pos_dens": pos_dens,
        "pos_ham": pos_ham,
        "strong_dens": str_dens,
        "strong_dens_std": float(dens.std()),
        "h_mean": float(h_tr.mean()),
        "h_std": float(h_tr.std()),
        "eff_bits_per_dim": eff_bits,
        "ceiling_cheap": {ef: cheap_rank_recall[ef] / denom * 100 for ef in EF_LIST},
        "ceiling_weighted": {ef: weighted_rank_recall[ef] / denom * 100 for ef in EF_LIST},
        "code_only_cheap": cheap_top10 / denom * 100,
        "code_only_weighted": weighted_top10 / denom * 100,
        "bench_recall_ef128": fr,
    }
    del tr, te, gt_flat, pos, strong, ppos, pstrong, Ptr, Str, Pq, Sq, Wtr, Wq
    gc.collect()
    return result


def main():
    wanted = sys.argv[1:] or [d[0] for d in ALL_DATASETS]
    rng = np.random.default_rng(RNG_SEED)

    guard(rng, 128)
    guard(rng, 960)

    rows = []
    for prefix, dim, note in ALL_DATASETS:
        if prefix in wanted:
            r = probe(prefix, dim, rng)
            r["note"] = note
            rows.append(r)
            # 增量落盘（跑一个存一个，便于分批执行）
            OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
            merged = {}
            if OUT_JSON.exists():
                merged = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            merged.update({x["prefix"]: x for x in rows})
            OUT_JSON.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    print(f"\n{'=' * 70}\n  汇总（markdown）\n{'=' * 70}")
    print(
        "| 数据集 | dim | 负值占比 | pos 平面 Hamming 率 | 有效bit/维 "
        "| code_oracle@128 (cheap) | code_oracle@1024 (cheap) | bench R@10@128 |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        bench = f"{r['bench_recall_ef128']:.2f}%" if r["bench_recall_ef128"] else "—"
        print(
            f"| {r['prefix']} | {r['dim']} | {r['neg_frac']:.5f} | {r['pos_ham']:.4f} "
            f"| {r['eff_bits_per_dim']:.1f} "
            f"| {r['ceiling_cheap'][128]:.2f}% | {r['ceiling_cheap'][1024]:.2f}% | {bench} |"
        )


if __name__ == "__main__":
    main()

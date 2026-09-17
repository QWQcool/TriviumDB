#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""维度轴可分性诊断（P2 核心图的前置数据）

口径严格取自 `docs/research/t2-sift-crosscheck.md` §4：
    可分性 = (GT1 - GT10) / cos_std
      GT1/GT10 = 各查询的最近/第 10 近邻 cosine，再对查询取均值
      cos_std  = **随机向量对**的 cosine 标准差

**口径守卫**：脚本必须复现文档里的已知值
    SIFT-128  可分性 0.1291   cos_std 0.2109
    cohere-768 可分性 0.7958  cos_std 0.0471

另加一个**新指标（拥挤度）**：top-10 的"可分间隙"内挤了多少向量。
可分性只说明间隙有多窄，拥挤度说明**要通过这个间隙需要多高的排序精度**——
若间隙内挤了上千个点，即使量化噪声小于间隙，名次仍近似抽签。

用法:
    & .venv\\Scripts\\python.exe scripts\\research\\dim_axis_separability.py
    & .venv\\Scripts\\python.exe scripts\\research\\dim_axis_separability.py sift128 gist960
"""
import gc
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

# (前缀, 维数, 数据类型说明)
ALL_DATASETS = [
    ("sift128", 128, "euclidean→cosine(重算)"),
    ("cohere", 768, "官方GT"),
    ("gist960", 960, "euclidean→cosine(重算)"),
    ("glove100", 100, "angular(原生GT)"),
]

# 口径守卫：来自 t2-sift-crosscheck.md §4
GUARD = {
    "sift128": {"cos_std": 0.2109, "separability": 0.1291},
    "cohere": {"cos_std": 0.0471, "separability": 0.7958},
}

N_PAIRS = 400_000  # 随机对样本数
N_QUERY_PROBE = 200  # 拥挤度探测的查询数（要全量扫描 1M，故只抽样）
CHUNK = 20_000  # 随机对分块


def l2_normalize_inplace(a, dim):
    """按行 L2 归一化（epsilon 兜底，与 prepare_all.py / bench 一致）。原零向量保持为零。"""
    n = a.shape[0]
    b = a.reshape(n, dim)
    norms = np.linalg.norm(b, axis=1)
    inv = 1.0 / np.maximum(norms, 1e-12)
    b *= inv[:, None]
    return norms


def random_pair_cos_std(tr, dim, rng):
    """随机向量对的 cosine 标准差（口径：'随机对 cos 标准差'）"""
    n = tr.shape[0]
    vals = np.empty(N_PAIRS, dtype=np.float64)
    done = 0
    while done < N_PAIRS:
        m = min(CHUNK, N_PAIRS - done)
        i = rng.integers(0, n, m)
        j = rng.integers(0, n, m)
        bad = i == j
        j[bad] = (j[bad] + 1) % n
        a = tr[i]  # (m, dim)
        b = tr[j]
        vals[done : done + m] = np.einsum("ij,ij->i", a, b)
        del a, b
        done += m
    return vals.mean(), vals.std()


def main():
    wanted = sys.argv[1:] or [d[0] for d in ALL_DATASETS]
    rng = np.random.default_rng(20260917)

    rows = []
    for prefix, dim, note in ALL_DATASETS:
        if prefix not in wanted:
            continue

        print(f"\n{'=' * 70}\n  {prefix}  dim={dim}  ({note})\n{'=' * 70}")

        tr = np.fromfile(f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
        te = np.fromfile(f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
        gt_flat = np.fromfile(f"{prefix}_groundtruth.i32", dtype=np.int32)

        nq = te.shape[0]
        cols = gt_flat.size // nq
        gt = gt_flat.reshape(nq, cols)[:, :10]  # cohere 是 K=1000 → 取前 10

        # 原始范数的变异系数（归一化前先算）
        norms_raw = np.linalg.norm(tr, axis=1)
        cv = norms_raw.std() / norms_raw.mean()
        aniso = (np.abs(tr).sum(axis=1) / np.maximum(norms_raw, 1e-12)).mean()
        zero_rows = int((norms_raw < 1e-8).sum())

        # 统一归一化。⚠️ train 与 test 都必须归一化：
        # `cohere_test.f32` 在磁盘上是**原始未归一化**的（其余数据集已被 prepare_all 归一化），
        # 漏掉 test 会让 cosine 变成 ‖q‖·cos（实测放大 ~13.8×，cosine > 1）。
        # 对已在球面上的数据是幂等操作。
        l2_normalize_inplace(tr, dim)
        l2_normalize_inplace(te, dim)

        cos_mean, cos_std = random_pair_cos_std(tr, dim, rng)

        # GT1 / GT10：用归一化后的向量算 cosine，再对查询取均值
        qi = np.arange(nq)
        g1 = np.einsum("ij,ij->i", te, tr[gt[:, 0]])
        g10 = np.einsum("ij,ij->i", te, tr[gt[:, 9]])
        gt1, gt10 = g1.mean(), g10.mean()
        separability = (gt1 - gt10) / cos_std

        # ── 新指标：拥挤度 ──
        # `[GT10, GT1]` 区间按定义只含那 10 个点，用它度量会退化成常数 10。
        # 改为度量**间隙下方有多拥挤**：落在 `[GT10 − gap, GT10)` 内的点数。
        # 该值越大，说明"第 10 名附近"越密，量化噪声稍大就会把真 top-10 挤出候选集。
        probe = rng.choice(nq, min(N_QUERY_PROBE, nq), replace=False)
        crowd_below = []
        rank10 = []
        for q in probe:
            s = tr @ te[q]
            lo = s[gt[q, 9]]
            hi = s[gt[q, 0]]
            gap = hi - lo
            crowd_below.append(int(((s >= lo - gap) & (s < lo)).sum()))
            # 第 10 名的"名次"= 相似度不低于它的点数（含并列）
            rank10.append(int((s >= lo).sum()))
        crowd_below = np.array(crowd_below, dtype=np.float64)
        rank10 = np.array(rank10, dtype=np.float64)

        sig_bits = 2 * ((dim + 63) // 64) * 64

        rows.append(
            {
                "prefix": prefix,
                "dim": dim,
                "n": tr.shape[0],
                "nq": nq,
                "cv": cv,
                "aniso": aniso,
                "cos_mean": cos_mean,
                "cos_std": cos_std,
                "gt1": gt1,
                "gt10": gt10,
                "separability": separability,
                "crowd_med": float(np.median(crowd_below)),
                "crowd_mean": crowd_below.mean(),
                "rank10_med": float(np.median(rank10)),
                "rank10_max": float(rank10.max()),
                "sig_bits": sig_bits,
                "note": note,
                "zero_rows": zero_rows,
            }
        )

        print(f"  原始 ‖x‖₂ CV            = {cv:.4f}   （零范数行 {zero_rows}）")
        print(f"  各向异性 ‖x‖₁/‖x‖₂      = {aniso:.3f}")
        print(f"  随机对 cos: mean={cos_mean:+.4f}  std={cos_std:.4f}")
        print(f"  GT1={gt1:+.4f}  GT10={gt10:+.4f}  落差={gt1 - gt10:+.4f}")
        print(f"  可分性 (GT1−GT10)/cos_std = {separability:.4f}")
        print(
            f"  ★ 拥挤度: [GT10−gap, GT10) 内点数 中位={np.median(crowd_below):.0f} "
            f"均值={crowd_below.mean():.0f}"
        )
        print(
            f"  ★ 第10名名次(≥GT10 的点数): 中位={np.median(rank10):.0f} 最大={rank10.max():.0f}"
        )
        print(f"  签名长度 2×ceil(dim/64)×64 = {sig_bits} bit")

        del tr, te, gt_flat
        gc.collect()

    # ── 口径守卫 ──
    print(f"\n{'=' * 70}\n  口径守卫：必须复现 t2-sift-crosscheck.md §4 的已知值\n{'=' * 70}")
    ok = True
    for r in rows:
        g = GUARD.get(r["prefix"])
        if not g:
            print(f"  {r['prefix']:10s} 无冻结值可校（新数据集）")
            continue
        d_std = abs(r["cos_std"] - g["cos_std"])
        d_sep = abs(r["separability"] - g["separability"])
        tol_std = 0.01 * g["cos_std"] + 0.002
        tol_sep = 0.02 * g["separability"] + 0.005
        good = (d_std <= tol_std) and (d_sep <= tol_sep)
        ok &= good
        print(
            f"  {r['prefix']:10s} cos_std {r['cos_std']:.4f} vs {g['cos_std']:.4f} (Δ{d_std:.4f})"
            f" | 可分性 {r['separability']:.4f} vs {g['separability']:.4f} (Δ{d_sep:.4f})"
            f"  → {'PASS' if good else 'FAIL'}"
        )
    print(f"\n  口径守卫总判定: {'PASS ⇒ 新数据集的指标与文档同尺度可比' if ok else 'FAIL ⇒ 口径不一致，外推无效'}")

    # ── markdown ──
    print(f"\n{'=' * 70}\n  维度轴汇总表（markdown）\n{'=' * 70}")
    print(
        "| 数据集 | 维度 | 随机对 cos std | GT1 | GT10 | 可分性 | 间隙下拥挤(中位) | 签名 bit | R@10 天花板 |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    recall_known = {
        "cohere": "97.52% @ef_s=128",
        "sift128": "47.21% @ef_s=1024",
        "gist960": "4.25% @ef_s=1024",
        "glove100": "待测",
    }
    for r in rows:
        print(
            f"| {r['prefix']} | {r['dim']} | {r['cos_std']:.4f} | {r['gt1']:+.4f} | {r['gt10']:+.4f} "
            f"| {r['separability']:.4f} | {r['crowd_med']:.0f} | {r['sig_bits']} | {recall_known.get(r['prefix'], '?')} |"
        )


if __name__ == "__main__":
    main()

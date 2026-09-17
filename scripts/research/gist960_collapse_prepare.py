#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成「gist960 召回崩塌根因」实验所需的派生数据集（含 GT 重算与口径守卫）。

一切派生集都写成标准三文件 `{prefix}_train.f32 / _test.f32 / _groundtruth.i32`，
从而可直接被 `bench_t2_b2_partitioned`（`T2_PREFIX` / `T2_DIM`）消费。

# 预注册臂（用户给定判据）
| 臂 | 前缀 | 构造 | 判据 |
|---|---|---|---|
| **T-ctrl** | `gauss960` | 随机各向同性高斯 1M×960 | ≥90% ⇒ "960 维"无罪；~3% ⇒ 维度/旋转结构有问题 |
| **T-center** | `gist960c` | `normalize(x − mean(train))`，保持 960 维 | ≥50% ⇒ H3（共同均值方向吃掉 2-bit 表示能力） |
| **T-sweep** | `gist960k{768,512,256,128}` | 取前 k 维后重新归一化 | 单调上升 ⇒ H1（维度相关）；平坦 ≈2.8% ⇒ H2（分布相关） |

# 追加的**判别臂**（本会话新增，用于消除 T-ctrl 的混淆并定位机制）
| 臂 | 前缀 | 构造 | 作用 |
|---|---|---|---|
| **T-pad** | `cohere960pad` | cohere 零填充到 960 维 | **维度机制对照**：零填充不改变任何余弦与排名 ⇒ 若 R@10 复现 97.5%，则 dim=960 的码/内核路径**可证无罪** |
| **T-plant** | `gauss960plant` | 高斯 + 每查询植入 10 个"真近邻"（cos 0.86–0.99，与 #11 有巨大间隔） | **T-ctrl 的补正**：随机高斯云的 top-10 是**近并列**（GT10≈GT11），任务本身不可解；T-plant 把"960 维 + 无结构"与"top-10 可解"分开 |
| **T-center-sift** | `sift128c` | SIFT 去均值后归一化 | H3 的**外部效度**：若 SIFT 也从中受益，则"均值方向"是跨数据集机制 |
| **T-sweep-cohere** | `coherek{512,256,128}` | cohere 截断 | 区分"gist960 特有" vs "高维普遍" |

# 口径守卫（每个派生集都跑）
1. 归一化后 cosine ≤ 1（上轮踩过：漏归一化 `test` 会得到 cosine 12.4）
2. GT 自校验：GT 第 1 名必须不弱于 2 万个随机点（≥98% 查询通过）
3. T-pad 专项：零填充前后逐对 cosine **完全一致**（断言 < 1e-6）
4. T-plant 专项：GT 必须恰好是植入的 10 行（100% 命中）

用法:
    & .venv\\Scripts\\python.exe scripts\\research\\gist960_collapse_prepare.py --list
    & .venv\\Scripts\\python.exe scripts\\research\\gist960_collapse_prepare.py gist960c gist960k512
"""

import gc
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "t2" / "gist960_collapse"
TOP_K = 10
RNG_SEED = 20260917
CROWD_PROBE = 100      # 拥挤度探测的查询数
N_PAIRS = 200_000      # 随机对 cosine 统计
SELFCHECK_POINTS = 20_000

RECIPES = {}


def recipe(fn):
    RECIPES[fn.__name__] = fn
    return fn


# ══════════════════════════════════════════════════════════════════
#  工具
# ══════════════════════════════════════════════════════════════════

def normalize_inplace(a):
    norms = np.linalg.norm(a, axis=1)
    a *= (1.0 / np.maximum(norms, 1e-12))[:, None]
    return norms


def load(prefix, dim):
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    return tr, te


def n_rows(prefix, dim):
    return (ROOT / f"{prefix}_train.f32").stat().st_size // (4 * dim)


def streaming_mean(prefix, dim, block=100_000):
    """流式求列均值（避免为 float64 拷贝再分配一份 2× 内存）"""
    n = n_rows(prefix, dim)
    acc = np.zeros(dim, dtype=np.float64)
    with open(ROOT / f"{prefix}_train.f32", "rb") as f:
        left = n
        while left > 0:
            m = min(block, left)
            a = np.fromfile(f, dtype=np.float32, count=m * dim).reshape(m, dim)
            acc += a.sum(axis=0, dtype=np.float64)
            left -= m
    return (acc / n).astype(np.float32)


def compute_gt(tr, te, top_k=TOP_K, batch=100):
    """**原地**归一化后按 cosine 重算 top-k GT（口径与 prepare_all.compute_groundtruth 一致）"""
    normalize_inplace(tr)
    normalize_inplace(te)
    nq = te.shape[0]
    gt = np.zeros((nq, top_k), dtype=np.int32)
    for s in range(0, nq, batch):
        e = min(s + batch, nq)
        sims = te[s:e] @ tr.T
        cand = np.argpartition(-sims, top_k, axis=1)[:, :top_k]
        for i in range(e - s):
            order = np.argsort(-sims[i, cand[i]], kind="stable")
            gt[s + i] = cand[i][order]
    return gt


def save(prefix, tr, te, gt):
    tr.astype(np.float32).tofile(str(ROOT / f"{prefix}_train.f32"))
    te.astype(np.float32).tofile(str(ROOT / f"{prefix}_test.f32"))
    gt.astype(np.int32).tofile(str(ROOT / f"{prefix}_groundtruth.i32"))
    print(f"  [OK] 写出 {prefix}_*.f32/i32  train={tr.shape} test={te.shape}")


def stats(prefix, dim, tr, te, gt, rng):
    """与 `dim_axis_separability.py` 同口径的统计（供论文 P2 表使用）"""
    nq = te.shape[0]
    q0 = te[: min(nq, 64)]
    cos_max = float((q0 @ tr[:200_000].T).max())
    assert cos_max <= 1.0 + 1e-5, f"口径守卫失败: cosine={cos_max} > 1（归一化漏了）"

    # GT 自校验：GT 第 1 名必须不弱于 SELFCHECK_POINTS 个**随机**点
    probe = rng.choice(nq, min(CROWD_PROBE, nq), replace=False)
    check_rows = rng.choice(tr.shape[0], SELFCHECK_POINTS, replace=False)
    n_ok = 0
    for q in probe:
        s = tr[check_rows] @ te[q]
        s_gt = float(tr[gt[q, 0]] @ te[q])
        if s_gt >= s.max() - 1e-4:
            n_ok += 1
    gt_self = n_ok / len(probe)

    idx = rng.integers(0, tr.shape[0], (N_PAIRS, 2))
    pair = np.einsum("ij,ij->i", tr[idx[:, 0]], tr[idx[:, 1]])
    g1 = float(np.einsum("ij,ij->i", te, tr[gt[:, 0]]).mean())
    g10 = float(np.einsum("ij,ij->i", te, tr[gt[:, 9]]).mean())
    cos_mean, cos_std = float(pair.mean()), float(pair.std())
    separability = (g1 - g10) / cos_std if cos_std > 0 else float("nan")

    crowd, gap10_11 = [], []
    for q in probe:
        s = tr @ te[q]
        lo, hi = s[gt[q, 9]], s[gt[q, 0]]
        gap = hi - lo
        crowd.append(int(((s >= lo - gap) & (s < lo)).sum()))
        # 第 10 名与"第 11 名"的间隔 —— 真正的可解性指标（top-10 与外部的最小间隔）
        s_sorted = np.sort(s)[::-1]
        gap10_11.append(float(s_sorted[9] - s_sorted[10]))
    crowd = np.array(crowd, dtype=np.float64)
    gap10_11 = np.array(gap10_11, dtype=np.float64)

    r = {
        "prefix": prefix,
        "dim": dim,
        "n_train": int(tr.shape[0]),
        "n_test": int(nq),
        "neg_frac": float((tr < 0).mean()),
        "zero_frac": float((tr == 0).mean()),
        "cos_mean": cos_mean,
        "cos_std": cos_std,
        "gt1": g1,
        "gt10": g10,
        "separability": separability,
        "crowd_med": float(np.median(crowd)),
        "crowd_mean": float(crowd.mean()),
        "gap10_11_med": float(np.median(gap10_11)),
        "gt_selfcheck": gt_self,
        "cos_max_guard": cos_max,
    }
    print(
        f"  负值占比={r['neg_frac']:.5f}  零值占比={r['zero_frac']:.5f}"
        f"  随机对 cos={cos_mean:+.4f}±{cos_std:.4f}\n"
        f"  GT1={g1:+.4f}  GT10={g10:+.4f}  可分性={separability:+.4f}\n"
        f"  GT10−GT11 中位间隔={r['gap10_11_med']:+.6f}  拥挤度 中位={r['crowd_med']:.0f} "
        f"均值={r['crowd_mean']:.0f}\n"
        f"  守卫: cosine≤1 max={cos_max:.6f} PASS | GT 自校验 {gt_self * 100:.1f}% "
        f"({'PASS' if gt_self >= 0.98 else 'FAIL'})"
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{prefix}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return r


# ══════════════════════════════════════════════════════════════════
#  通用派生：先在源维度归一化（对已在球面上的数据幂等），再做变换，再重算 GT
# ══════════════════════════════════════════════════════════════════

def derive(src_prefix, src_dim, dst_prefix, transform, dst_dim=None, doc=""):
    print(f"\n{'=' * 70}\n  {src_prefix}({src_dim}) → {dst_prefix}   {doc}\n{'=' * 70}")
    tr, te = load(src_prefix, src_dim)
    normalize_inplace(tr)
    normalize_inplace(te)
    tr, te = transform(tr, te)
    gc.collect()
    dim = tr.shape[1]
    assert te.shape[1] == dim
    if dst_dim is not None:
        assert dim == dst_dim
    gt = compute_gt(tr, te)
    save(dst_prefix, tr, te, gt)
    return tr, te, gt, dim


# ══════════════════════════════════════════════════════════════════
#  T-ctrl
# ══════════════════════════════════════════════════════════════════

@recipe
def gauss960(rng):
    dim, n, nq = 960, 1_000_000, 1000
    print(f"\n{'=' * 70}\n  T-ctrl: 随机各向同性高斯 {n} × {dim}\n{'=' * 70}")
    tr = rng.standard_normal((n, dim), dtype=np.float32)
    te = rng.standard_normal((nq, dim), dtype=np.float32)
    gt = compute_gt(tr, te)
    save("gauss960", tr, te, gt)
    stats("gauss960", dim, tr, te, gt, rng)


# ══════════════════════════════════════════════════════════════════
#  T-plant
# ══════════════════════════════════════════════════════════════════

@recipe
def gauss960plant(rng):
    dim, n, nq = 960, 1_000_000, 1000
    delta = np.linspace(0.15, 0.60, TOP_K).astype(np.float32)
    print(
        f"\n{'=' * 70}\n  T-plant: 高斯 {n} × {dim} + 每查询植入 10 个真近邻\n"
        f"  δ={delta[0]:.2f}..{delta[-1]:.2f} ⇒ 植入 cos ≈ "
        f"{1 / np.sqrt(1 + delta[0] ** 2):.3f}..{1 / np.sqrt(1 + delta[-1] ** 2):.3f}"
        f"（随机点最大 cos 约 0.15）\n{'=' * 70}"
    )
    tr = rng.standard_normal((n, dim), dtype=np.float32)
    te = np.zeros((nq, dim), dtype=np.float32)
    # 植入点直接覆盖 train 的前 nq*TOP_K 行（它们本身就是 train 的成员）。
    # ⚠️ 扰动向量 g 必须**单位化**，否则 ‖δg‖ ≈ δ√dim ≫ ‖c‖，
    #    植入点会退化成随机方向（cos ≈ 1/(δ√dim) 而非 1/√(1+δ²)）。
    for q in range(nq):
        c = rng.standard_normal(dim, dtype=np.float32)
        c /= np.linalg.norm(c)
        te[q] = c
        g = rng.standard_normal((TOP_K, dim), dtype=np.float32)
        g /= np.linalg.norm(g, axis=1, keepdims=True)
        planted = c[None, :] + delta[:, None] * g
        planted /= np.linalg.norm(planted, axis=1, keepdims=True)
        tr[q * TOP_K : (q + 1) * TOP_K] = planted
    gt = compute_gt(tr, te)
    hit = sum(
        len(set(map(int, gt[q])) & set(range(q * TOP_K, (q + 1) * TOP_K)))
        for q in range(nq)
    )
    print(
        f"  守卫 植入命中率 = {hit / (nq * TOP_K) * 100:.2f}%"
        f"（须 100% ⇒ 植入的近邻确实是真 top-10）"
    )
    assert hit == nq * TOP_K, "T-plant 植入失败：GT 未落在植入行上"
    save("gauss960plant", tr, te, gt)
    stats("gauss960plant", dim, tr, te, gt, rng)


# ══════════════════════════════════════════════════════════════════
#  T-center
# ══════════════════════════════════════════════════════════════════

@recipe
def gist960c(rng):
    """T-center: x' = normalize(x − mean(train))，保持 960 维"""
    mu = streaming_mean("gist960", 960)
    print(f"  ‖mean(train)‖ = {np.linalg.norm(mu):.6f}")
    tr, te, gt, dim = derive(
        "gist960", 960, "gist960c", lambda a, b: (a - mu, b - mu), 960,
        doc="去均值（共同均值方向）",
    )
    stats("gist960c", dim, tr, te, gt, rng)


@recipe
def sift128c(rng):
    """T-center-sift: SIFT 去均值后归一化（H3 的外部效度）"""
    mu = streaming_mean("sift128", 128)
    print(f"  ‖mean(train)‖ = {np.linalg.norm(mu):.6f}")
    tr, te, gt, dim = derive(
        "sift128", 128, "sift128c", lambda a, b: (a - mu, b - mu), 128,
        doc="去均值（外部效度）",
    )
    stats("sift128c", dim, tr, te, gt, rng)


# ══════════════════════════════════════════════════════════════════
#  T-sweep
# ══════════════════════════════════════════════════════════════════

def _sweep(src_prefix, src_dim, keep, rng, doc):
    tr, te, gt, dim = derive(
        src_prefix, src_dim, f"{src_prefix}k{keep}",
        lambda a, b: (a[:, :keep].copy(), b[:, :keep].copy()), keep, doc=doc,
    )
    stats(f"{src_prefix}k{keep}", dim, tr, te, gt, rng)


@recipe
def gist960k768(rng):
    """T-sweep: gist960 截断到 768 维（取前 768 维后重新归一化 + 重算 GT）"""
    _sweep("gist960", 960, 768, rng, "截断到 768 维")


@recipe
def gist960k512(rng):
    """T-sweep: gist960 截断到 512 维"""
    _sweep("gist960", 960, 512, rng, "截断到 512 维")


@recipe
def gist960k256(rng):
    """T-sweep: gist960 截断到 256 维"""
    _sweep("gist960", 960, 256, rng, "截断到 256 维")


@recipe
def gist960k128(rng):
    """T-sweep: gist960 截断到 128 维"""
    _sweep("gist960", 960, 128, rng, "截断到 128 维")


@recipe
def coherek512(rng):
    """可选对照: cohere 截断到 512 维（区分"gist960 特有" vs "高维普遍"）"""
    _sweep("cohere", 768, 512, rng, "截断到 512 维（对照）")


@recipe
def coherek256(rng):
    """可选对照: cohere 截断到 256 维"""
    _sweep("cohere", 768, 256, rng, "截断到 256 维（对照）")


@recipe
def coherek128(rng):
    """可选对照: cohere 截断到 128 维"""
    _sweep("cohere", 768, 128, rng, "截断到 128 维（对照）")


# ══════════════════════════════════════════════════════════════════
#  T-pad
# ══════════════════════════════════════════════════════════════════

@recipe
def cohere960pad(rng):
    """T-pad: cohere 零填充到 960 维（余弦与全部排名不变，但 chunks 12→15）"""
    print(f"\n{'=' * 70}\n  T-pad: cohere(768) → 960 零填充\n{'=' * 70}")
    tr768, te768 = load("cohere", 768)
    normalize_inplace(tr768)
    normalize_inplace(te768)
    n, nq = tr768.shape[0], te768.shape[0]
    tr = np.zeros((n, 960), dtype=np.float32)
    te = np.zeros((nq, 960), dtype=np.float32)
    tr[:, :768] = tr768
    te[:, :768] = te768
    i, j = rng.integers(0, n, 64), rng.integers(0, n, 64)
    dev = float(np.abs(np.einsum("ij,ij->i", tr768[i], tr768[j])
                       - np.einsum("ij,ij->i", tr[i], tr[j])).max())
    print(
        f"  守卫 零填充前后逐对 cosine 最大偏差 = {dev:.3e}  "
        f"{'PASS ⇒ 排名与图同构，R@10 必须复现 cohere' if dev < 1e-6 else 'FAIL'}"
    )
    assert dev < 1e-6
    del tr768, te768
    gc.collect()
    # GT 直接复制（零填充保序）——bench 只取每行前 10 列
    gt = (np.fromfile(ROOT / "cohere_groundtruth.i32", dtype=np.int32)
          .reshape(nq, -1)[:, :TOP_K].copy())
    save("cohere960pad", tr, te, gt)
    stats("cohere960pad", 960, tr, te, gt, rng)


# ══════════════════════════════════════════════════════════════════

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--list" in sys.argv:
        for name in RECIPES:
            print(f"  {name}")
        return
    if "--stats" in sys.argv:
        # 只对已生成的派生集重跑统计（不重新生成/重算 GT）
        for name in args:
            dim = {"gauss960": 960, "gauss960plant": 960, "gist960c": 960,
                   "sift128c": 128, "cohere960pad": 960}.get(name)
            if dim is None:
                dim = int(name.split("k")[-1])
            tr, te = load(name, dim)
            gt = (np.fromfile(ROOT / f"{name}_groundtruth.i32", dtype=np.int32)
                  .reshape(te.shape[0], -1)[:, :TOP_K])
            print(f"\n{'=' * 70}\n  {name}  dim={dim}\n{'=' * 70}")
            stats(name, dim, tr, te, gt, np.random.default_rng(RNG_SEED))
        return
    names = args or list(RECIPES.keys())
    for name in names:
        if name not in RECIPES:
            print(f"[错误] 未知配方 {name}；可用: {', '.join(RECIPES)}")
            sys.exit(1)
    rng = np.random.default_rng(RNG_SEED)
    for name in names:
        RECIPES[name](rng)
    print(f"\n{'=' * 70}\n  全部完成；统计写入 {OUT_DIR}\n{'=' * 70}")


if __name__ == "__main__":
    main()

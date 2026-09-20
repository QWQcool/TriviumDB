"""N1 ③ 补完：RedCaps-1M（512-d, CLIP ViT-B/32, angular）→ f32 三件套 + 重算 GT

**源**：`README_QUIVER.md` §1c 指定的 Zenodo 记录 13137120
      `redcaps-512-angular.hdf5`（22.12 GiB，MD5 `a6221cc0a4103af7e0f06f87bd989a0a`，CC BY 4.0）

**实测文件结构**（`train` 全部已 L2 单位化）：
    train       (11,588,824, 512)
    random_test (10,000, 512)
    test        (800, 512)
    ← **没有 `neighbors`/`distances`** ⇒ GT 必须自己重算

⚠️ README 只说"转成 f32 并保存 1M×512 / 10K×512 / 10K×10"，**四点协议未规定**，本脚本采用：
  (a) **base = `train[:1_000_000]`**（文件序前 1M）
  (b) **queries = `random_test`（10,000）** —— 它与 README 的 "10K" 匹配；
      另一套 `test` 只有 800 行，且与基底的最大 cosine 仅 0.273–0.376（中位 0.324），
      而 `random_test` 的中位是 **0.863**（11.59M 里约 8.6% 概率落在 1M 前缀内，实测 21/200 命中 1.000000）
      ⇒ 两套查询**语义不同**，不能互换
  (c) **排除自匹配**：`random_test` 与 `train` 同池，命中 cosine ≥ 1−1e-6 的基底行（自身与精确重复）全部剔除
  (d) **GT 在 1M 基底内**重算 exact cosine top-10

⇒ 这四点已作为 issue 草稿（B4）向作者求证；本脚本的产出是"**按我们的假设**"的复现口径，
   论文中必须如此声明（见 `docs/research/audit-and-direction.md`、`paper-outline.md` L5）。
"""
import json
import sys
from pathlib import Path

import h5py
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
H5 = ROOT / "redcaps-512-angular.hdf5"
BASE_N, DIM, TOP_K, QBATCH = 1_000_000, 512, 10, 50
SELF_TOL = 1e-6


def save(prefix, tr, te, gt):
    tr.astype(np.float32).tofile(str(ROOT / f"{prefix}_train.f32"))
    te.astype(np.float32).tofile(str(ROOT / f"{prefix}_test.f32"))
    gt.astype(np.int32).tofile(str(ROOT / f"{prefix}_groundtruth.i32"))
    print(f"  [OK] {prefix}_*.f32/i32  train={tr.shape} test={te.shape} gt={gt.shape}")


def main():
    if not H5.exists():
        print(f"[错误] 缺 {H5.name}（从 Zenodo 13137120 下载）")
        return
    # argv: [mode] [seed] —— mode ∈ {prefix, random}；后者用于检验"取哪 1M"的影响
    mode = sys.argv[1] if len(sys.argv) > 1 else "prefix"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    keep_self = "keepself" in sys.argv          # 不排除自匹配（检验论文是否这么做的）
    with h5py.File(H5, "r") as f:
        total = f["train"].shape[0]
        if mode == "random":
            idx = np.sort(np.random.default_rng(seed).choice(total, BASE_N, replace=False))
            tr = f["train"][idx].astype(np.float32)
            prefix = f"redcapsr{seed}"
            base_rule = f"random {BASE_N} rows of {total} (seed={seed})"
        else:
            tr = f["train"][:BASE_N].astype(np.float32)
            prefix = "redcaps"
            base_rule = f"train[:{BASE_N}] (file order)"
        if keep_self:
            prefix += "k"
            base_rule += " + 不排除自匹配"
        te = f["random_test"][:].astype(np.float32)
    nq = te.shape[0]
    print(f"读取 {H5.name}：base={base_rule}，queries=random_test（{nq}）")
    print(f"  train={tr.shape} test={te.shape}")

    n_tr = np.linalg.norm(tr, axis=1)
    n_te = np.linalg.norm(te, axis=1)
    print(f"  行范数 train mean={n_tr.mean():.6f} std={n_tr.std():.6f} | "
          f"test mean={n_te.mean():.6f} std={n_te.std():.6f}")
    tr /= np.maximum(n_tr, 1e-12)[:, None]
    te /= np.maximum(n_te, 1e-12)[:, None]

    gt = np.zeros((nq, TOP_K), dtype=np.int32)
    n_excl = 0
    gt1 = gt10 = 0.0
    for s in range(0, nq, QBATCH):
        e = min(s + QBATCH, nq)
        sims = tr @ te[s:e].T                       # (1M, B)
        if keep_self:
            dup = np.zeros_like(sims, dtype=bool)
        else:
            dup = sims >= 1.0 - SELF_TOL
            n_excl += int(dup.any(axis=0).sum())
            sims[dup] = -np.inf                     # 排除自匹配/精确重复
        cand = np.argpartition(-sims, TOP_K, axis=0)[:TOP_K]
        for j in range(e - s):
            col = cand[:, j]
            gt[s + j] = col[np.argsort(-sims[col, j], kind="stable")]
        gt1 += float(sims[gt[s:e, 0], np.arange(e - s)].sum())
        gt10 += float(sims[gt[s:e, TOP_K - 1], np.arange(e - s)].sum())
        del sims, dup, cand
    gt1 /= nq
    gt10 /= nq

    cos_max = float((te[: min(64, nq)] @ tr[:200_000].T).max())
    assert cos_max <= 1.0 + 1e-5, f"口径守卫失败: cosine={cos_max} > 1"
    print(f"  口径守卫 cosine≤1: max={cos_max:.6f} PASS")
    print(f"  ★ 排除自匹配的查询数 = {n_excl}/{nq}（{n_excl / nq * 100:.1f}%）"
          f"  —— 与'随机取自同一池'相符（1M/11.59M ≈ 8.6%）")
    print(f"  GT1={gt1:.4f}  GT10={gt10:.4f}  落差={gt1 - gt10:.4f}")

    save(prefix, tr, te, gt)
    out = ROOT / "results" / "t2" / "gist960_collapse" / f"{prefix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "prefix": prefix, "dim": DIM, "n_train": int(tr.shape[0]), "n_test": int(te.shape[0]),
        "base_rule": base_rule, "queries": "random_test (10000)",
        "self_match_excluded": True, "n_self_excluded": n_excl,
        "gt_scope": "exact cosine top-10 within the 1M base",
        "gt1": gt1, "gt10": gt10, "hdf5_md5": "a6221cc0a4103af7e0f06f87bd989a0a",
        "zenodo": "10.5281/zenodo.13137120",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 写出 {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""L1-A6 数据集自校验：维度/形状一致性 + 独立重算 ground truth 对拍。

只读操作，不修改任何数据集文件。
"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIM = 768
K_EXPECT = 10  # prepare_all.py: TOP_K = 10


def load_raw(path: Path, dtype: str) -> np.ndarray:
    return np.fromfile(path, dtype=dtype)


def shp(arr: np.ndarray, width: int) -> tuple[int, int]:
    assert arr.size % width == 0, f"size {arr.size} 不能被 {width} 整除"
    return arr.size // width, width


print("=" * 74)
print("L1-A6 数据集自校验")
print("=" * 74)

train_p = ROOT / "cohere_train.f32"
test_p = ROOT / "cohere_test.f32"
gt_p = ROOT / "cohere_groundtruth.i32"

for p in (train_p, test_p, gt_p):
    print(f"  {p.name:28s} {p.stat().st_size:>13,} bytes  ({p.stat().st_size / 1048576:>8.2f} MiB)")

train = load_raw(train_p, np.float32)
test = load_raw(test_p, np.float32)
gt = load_raw(gt_p, np.int32)

n_train, d_train = shp(train, DIM)
n_test, d_test = shp(test, DIM)

print("-" * 74)
print(f"  train : {n_train:,} × {d_train}")
print(f"  test  : {n_test:,} × {d_test}")

# gt 列数：用 Q=len(test) 反推每个 query 的 top-K 数
gt_cols_if_q_test = gt.size / n_test
print(f"  gt    : {gt.size:,} 个 int32")
print(f"         若按 Q={n_test:,} 解釋 → K = {gt_cols_if_q_test:.2f}")

# 优先假设 GT 列数为整数且接近 K_EXPECT
k_gt = None
for cand in (10, 100, 1000):
    if gt.size % (n_test * cand) == 0:
        k_gt = cand
        print(f"         → 可被 Q×{cand} 整除，K={cand} 候选成立")
if k_gt is None:
    # 反推最大可能 K
    for cand in range(1, 4097):
        if gt.size == n_test * cand:
            k_gt = cand
            break

print("-" * 74)

# ── 有限性检查（抽样，避免全量 3GB 扫描过慢）──
rng = np.random.default_rng(0)
sample_idx = rng.choice(n_train, size=min(20000, n_train), replace=False)
print(f"  train 有限性抽检 {len(sample_idx):,} 条: {np.isfinite(train.reshape(-1, DIM)[sample_idx]).all()}")
print(f"  test  有限性全检           : {np.isfinite(test).all()}")

# ── GT 索引合法性 ──
gt_int = gt[: n_test * k_gt].reshape(n_test, k_gt) if k_gt and gt.size >= n_test * k_gt else None
if gt_int is not None:
    bad_lo, bad_hi = (gt_int < 0).sum(), (gt_int >= n_train).sum()
    print(f"  GT 索引范围            : <0 {bad_lo} 个, >=n_train {bad_hi} 个")
    dup = sum(1 for r in gt_int[:500] if len(set(r.tolist())) != len(r))
    print(f"  GT 前 500 行重复索引行数: {dup}")

# ── 独立重算 GT 对拍（前 20 条查询，余弦）──
print("-" * 74)
print("  独立重算 GT 对拍（前 20 条 query，全量 1M 扫描，cosine）...")
train_2d = train.reshape(n_train, DIM)
test_2d = test.reshape(n_test, DIM)

tn = train_2d / np.maximum(np.linalg.norm(train_2d, axis=1, keepdims=True), 1e-12)
qn = test_2d[:20] / np.maximum(np.linalg.norm(test_2d[:20], axis=1, keepdims=True), 1e-12)

sims = qn @ tn.T  # 20 × 1M
recomputed = np.argsort(-sims, axis=1)[:, :K_EXPECT].astype(np.int32)

if gt_int is not None:
    provided = gt_int[:20, :K_EXPECT]
    hit_sets = [len(set(recomputed[i].tolist()) & set(provided[i].tolist())) for i in range(20)]
    print(f"  逐条 top-{K_EXPECT} 重合数: {hit_sets}")
    print(f"  平均重合: {np.mean(hit_sets):.2f} / {K_EXPECT}")

    # 用重算结果反查：provided 里的 ID 在重算排序中的名次
    for i in range(min(3, 20)):
        rank = np.argsort(-sims[i])
        pos = [int(np.where(rank == pid)[0][0]) for pid in provided[i]]
        print(f"    q{i}: provided 的 {K_EXPECT} 个 ID 在重算中的名次 = {pos}")
else:
    print("  [跳过] GT 形状无法解析")

print("=" * 74)

"""验证 bench_rbq2_precision.rs 的 FhtKacRotator 是否为正交变换。

严格复刻 `benches/bench_rbq2_precision.rs:36-110` 的 rotate()：
  padded_dim = (dim+63) & ~63
  trunc_dim  = 1 << floor(log2(dim))
  fac        = 1/sqrt(trunc_dim)
  4 轮 (flip_sign + FHT/trunc_dim + rescale + kacs_walk)，trunc_dim != padded_dim 分支
  最后整段 ×0.25

判据：
  1) 范数保持  ||R(x)||  ==  ||x||
  2) 内积保持  <R(q),R(x)> == <q,x>      <- 正交性的定义
"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIM = 768
MASK64 = (1 << 64) - 1


class Rotator:
    """逐位复刻 Rust 实现。"""

    def __init__(self, dim: int, seed: int) -> None:
        self.padded_dim = (dim + 63) & ~63
        log2 = self.padded_dim.bit_length() - 1
        # Rust: (usize::BITS - 1) - dim.leading_zeros()  ->  floor(log2(dim))
        log2 = int(np.floor(np.log2(dim)))
        self.trunc_dim = 1 << log2
        self.fac = 1.0 / float(np.sqrt(self.trunc_dim))

        state = seed
        bytes_per_flip = self.padded_dim // 8
        self.flips = []
        for _ in range(4):
            buf = np.zeros(bytes_per_flip, dtype=np.uint8)
            for i in range(bytes_per_flip):
                state ^= (state << 13) & MASK64
                state ^= state >> 7
                state ^= (state << 17) & MASK64
                state &= MASK64
                buf[i] = state & 0xFF
            self.flips.append(buf)

    @staticmethod
    def _flip_sign(flip: np.ndarray, data: np.ndarray) -> None:
        # 位展开成 ±1 掩码
        mask = np.unpackbits(flip, bitorder="little").astype(np.int8)
        mask = np.where(mask == 1, -1, 1).astype(np.float32)
        data *= mask[: data.size]

    @staticmethod
    def _fht_in_place(x: np.ndarray) -> None:
        n = x.size
        h = 1
        while h < n:
            view = x.reshape(-1, 2 * h)
            a = view[:, :h].copy()
            b = view[:, h:].copy()
            view[:, :h] = a + b
            view[:, h:] = a - b
            h *= 2

    @staticmethod
    def _kacs_walk(data: np.ndarray) -> None:
        half = data.size // 2
        a = data[:half].copy()
        b = data[half:].copy()
        data[:half] = a + b
        data[half:] = a - b

    def rotate(self, src: np.ndarray) -> np.ndarray:
        data = np.zeros(self.padded_dim, dtype=np.float32)
        copy_len = min(src.size, self.padded_dim)
        data[:copy_len] = src[:copy_len]

        start = self.padded_dim - self.trunc_dim
        if self.trunc_dim == self.padded_dim:
            for r in range(4):
                self._flip_sign(self.flips[r], data)
                self._fht_in_place(data[: self.trunc_dim])
                data[: self.trunc_dim] *= self.fac
        else:
            self._flip_sign(self.flips[0], data)
            self._fht_in_place(data[: self.trunc_dim])
            data[: self.trunc_dim] *= self.fac
            self._kacs_walk(data)

            self._flip_sign(self.flips[1], data)
            self._fht_in_place(data[start : start + self.trunc_dim])
            data[start : start + self.trunc_dim] *= self.fac
            self._kacs_walk(data)

            self._flip_sign(self.flips[2], data)
            self._fht_in_place(data[: self.trunc_dim])
            data[: self.trunc_dim] *= self.fac
            self._kacs_walk(data)

            self._flip_sign(self.flips[3], data)
            self._fht_in_place(data[start : start + self.trunc_dim])
            data[start : start + self.trunc_dim] *= self.fac
            self._kacs_walk(data)

            data *= 0.25
        return data


rot = Rotator(DIM, 42)
print("=" * 78)
print("FhtKacRotator 正交性验证")
print("=" * 78)
print(f"  dim={DIM}  padded_dim={rot.padded_dim}  trunc_dim={rot.trunc_dim}  fac={rot.fac:.8f}")
print(f"  注意: trunc_dim({rot.trunc_dim}) != padded_dim({rot.padded_dim}) -> 走 else 分支")
print("-" * 78)

train = np.fromfile(ROOT / "cohere_train.f32", dtype=np.float32).reshape(-1, DIM)[:400]
test = np.fromfile(ROOT / "cohere_test.f32", dtype=np.float32).reshape(-1, DIM)

# ── 判据 1: 范数保持 ──
norms_src = np.linalg.norm(train, axis=1)
rotated = np.array([rot.rotate(x) for x in train])
norms_dst = np.linalg.norm(rotated, axis=1)
ratios = norms_dst / norms_src
print(f"  判据1 范数保持: ||R(x)||/||x||  min={ratios.min():.6f} max={ratios.max():.6f} "
      f"mean={ratios.mean():.6f}")
print(f"        期望恒为 1.0 -> {'PASS' if np.allclose(ratios, 1.0, atol=1e-4) else 'FAIL'}")

# ── 判据 2: 内积保持 ──
print("-" * 78)
rng = np.random.default_rng(7)
qi = rng.choice(test.shape[0], size=64, replace=False)
xi = rng.choice(train.shape[0], size=64, replace=False)
src_ip = np.array([train[j] @ test[i] for i, j in zip(qi, xi)])
dst_ip = np.array([rotated[j] @ rot.rotate(test[i]) for i, j in zip(qi, xi)])
rel_err = np.abs(dst_ip - src_ip) / np.maximum(np.abs(src_ip), 1e-9)
print(f"  <q,x>      样本: {src_ip[:5]}")
print(f"  <Rq,Rx>    样本: {dst_ip[:5]}")
print(f"  相对误差  mean={rel_err.mean():.6f}  max={rel_err.max():.6f}")
ok = rel_err.max() < 1e-3
print(f"        期望相对误差 ~0 -> {'PASS' if ok else 'FAIL (旋转非正交!)'}")

# ── 判据 3: 二值化后的估计质量（有旋转 vs 无旋转）──
print("-" * 78)
N_TRAIN = 20_000
N_Q = 100
K = 10
tr = train[:N_TRAIN] if N_TRAIN <= train.shape[0] else np.fromfile(
    ROOT / "cohere_train.f32", dtype=np.float32).reshape(-1, DIM)[:N_TRAIN]
tr_rot = np.array([rot.rotate(x) for x in tr])
te = test[:N_Q]

tn = tr / np.maximum(np.linalg.norm(tr, axis=1, keepdims=True), 1e-12)
qn = te / np.maximum(np.linalg.norm(te, axis=1, keepdims=True), 1e-12)

gt = np.argsort(-(qn @ tn.T), axis=1)[:, :K]


def overlap(scores: np.ndarray) -> float:
    top = np.argsort(-scores, axis=1)[:, :K]
    return float(np.mean([len(set(top[i]) & set(gt[i])) for i in range(N_Q)]) / K)


# 无旋转: q 全精度 × sign(x)
no_rot = qn @ np.sign(tr).T
# 有旋转: Rq 全精度 × sign(Rx)
with_rot = np.array([rot.rotate(q) for q in te]) @ np.sign(tr_rot).T
# 有旋转: sign(Rq) × sign(Rx)  <- 基准的 sym 口径
sym = np.sign(np.array([rot.rotate(q) for q in te])) @ np.sign(tr_rot).T

print(f"  N_TRAIN={N_TRAIN} N_Q={N_Q} K={K}  (top-K 重合率 vs cosine GT)")
print(f"    无旋转  q·sign(x)      : {overlap(no_rot) * 100:6.2f}%")
print(f"    有旋转  Rq·sign(Rx)    : {overlap(with_rot) * 100:6.2f}%")
print(f"    有旋转  sign(Rq)·sign(Rx): {overlap(sym) * 100:6.2f}%  <- 基准 RBQ-sym 口径")
print("=" * 78)

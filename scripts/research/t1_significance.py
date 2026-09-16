"""对『旋转净增益为负』做配对显著性检验（Cohere-100K, 1 bit/dim）。"""
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIM, N_TRAIN, N_Q, K = 768, 100_000, 200, 10
MASK64 = (1 << 64) - 1


class BatchRotator:
    def __init__(self, dim, seed):
        self.padded_dim = (dim + 63) & ~63
        self.trunc_dim = 1 << int(np.floor(np.log2(dim)))
        self.fac = 1.0 / float(np.sqrt(self.trunc_dim))
        state, n_bytes, self.masks = seed, ((dim + 63) & ~63) // 8, []
        for _ in range(4):
            buf = np.zeros(n_bytes, dtype=np.uint8)
            for i in range(n_bytes):
                state ^= (state << 13) & MASK64
                state ^= state >> 7
                state ^= (state << 17) & MASK64
                state &= MASK64
                buf[i] = state & 0xFF
            bits = np.unpackbits(buf, bitorder="little")[: self.padded_dim]
            self.masks.append(np.where(bits == 1, -1.0, 1.0).astype(np.float32))

    def rotate(self, x):
        data = np.zeros((x.shape[0], self.padded_dim), dtype=np.float32)
        m = min(x.shape[1], self.padded_dim)
        data[:, :m] = x[:, :m]
        start = self.padded_dim - self.trunc_dim
        sl = (slice(None), slice(0, self.trunc_dim))
        sr = (slice(None), slice(start, start + self.trunc_dim))
        for flip, seg in zip(self.masks, [sl, sr, sl, sr]):
            data *= flip
            sub = data[seg]
            h, n = 1, self.trunc_dim
            while h < n:
                v = sub.reshape(sub.shape[0], -1, 2 * h)
                a, b = v[:, :, :h].copy(), v[:, :, h:].copy()
                v[:, :, :h], v[:, :, h:] = a + b, a - b
                h *= 2
            data[seg] = sub * self.fac
            half = data.shape[1] // 2
            a, b = data[:, :half].copy(), data[:, half:].copy()
            data[:, :half], data[:, half:] = a + b, a - b
        return data * 0.25


tr = np.fromfile(ROOT / "cohere_train.f32", dtype=np.float32).reshape(-1, DIM)[:N_TRAIN]
te = np.fromfile(ROOT / "cohere_test.f32", dtype=np.float32).reshape(-1, DIM)[:N_Q]

tn = tr / np.maximum(np.linalg.norm(tr, axis=1, keepdims=True), 1e-12)
qn = te / np.maximum(np.linalg.norm(te, axis=1, keepdims=True), 1e-12)
gt = np.argsort(-(qn @ tn.T), axis=1)[:, :K]

rot = BatchRotator(DIM, 42)
tr_r, te_r = rot.rotate(tr), rot.rotate(te)

no_rot = qn @ np.sign(tr).T
with_rot = te_r @ np.sign(tr_r).T

top_nr = np.argsort(-no_rot, axis=1)[:, :K]
top_wr = np.argsort(-with_rot, axis=1)[:, :K]

per_q_nr = np.array([len(set(top_nr[i]) & set(gt[i])) for i in range(N_Q)], dtype=np.float64) / K
per_q_wr = np.array([len(set(top_wr[i]) & set(gt[i])) for i in range(N_Q)], dtype=np.float64) / K
diff = per_q_wr - per_q_nr

print("=" * 76)
print("旋转净增益的配对显著性检验 (Cohere-100K, 1 bit/dim, K=10, 200 paired queries)")
print("=" * 76)
print(f"  无旋转 Recall@10 = {per_q_nr.mean() * 100:.2f}%   (逐查询 SE = "
      f"{per_q_nr.std(ddof=1) / np.sqrt(N_Q) * 100:.2f}pp)")
print(f"  有旋转 Recall@10 = {per_q_wr.mean() * 100:.2f}%   (逐查询 SE = "
      f"{per_q_wr.std(ddof=1) / np.sqrt(N_Q) * 100:.2f}pp)")
print(f"  配对差 mean = {diff.mean() * 100:+.2f}pp   (配对 SE = "
      f"{diff.std(ddof=1) / np.sqrt(N_Q) * 100:.2f}pp)")

t_stat = diff.mean() / (diff.std(ddof=1) / np.sqrt(N_Q))
print(f"  配对 t 统计量 = {t_stat:.2f}  (|t| > 1.97 即 p < 0.05 双尾)")
print(f"  旋转变好的查询数 = {(diff > 0).sum()}  变差 = {(diff < 0).sum()}  持平 = {(diff == 0).sum()}")
n_better, n_worse = int((diff > 0).sum()), int((diff < 0).sum())
n_eff = n_better + n_worse
sign_p = 2 * sum(math.comb(n_eff, i) for i in range(min(n_better, n_worse) + 1)) / 2 ** n_eff
print(f"  双侧符号检验 p ≈ {min(sign_p, 1.0):.6f}  (n_eff = {n_eff})")
print("=" * 76)

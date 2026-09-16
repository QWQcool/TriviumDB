"""T1 决策实验：等比特预算下『旋转』是否带来增益。

拆分两个被混淆的变量：
  变量 A = 比特预算 (1 vs 2 bits/dim)
  变量 B = 是否做随机旋转

若 B 在等比特下无增益 -> RaBitQ 的价值只在误差界理论，T1 应先补多比特实现
若 B 在等比特下有增益 -> 旋转本身有用，RaBitQ 融合路径成立
"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIM = 768
N_TRAIN = 100_000
N_Q = 200
K = 10
MASK64 = (1 << 64) - 1


class BatchRotator:
    def __init__(self, dim: int, seed: int) -> None:
        self.padded_dim = (dim + 63) & ~63
        self.trunc_dim = 1 << int(np.floor(np.log2(dim)))
        self.fac = 1.0 / float(np.sqrt(self.trunc_dim))
        state = seed
        n_bytes = self.padded_dim // 8
        self.masks = []
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

    def rotate(self, x: np.ndarray) -> np.ndarray:
        data = np.zeros((x.shape[0], self.padded_dim), dtype=np.float32)
        m = min(x.shape[1], self.padded_dim)
        data[:, :m] = x[:, :m]
        start = self.padded_dim - self.trunc_dim
        sl = (slice(None), slice(0, self.trunc_dim))
        sr = (slice(None), slice(start, start + self.trunc_dim))
        for flip, seg in zip(self.masks, [sl, sr, sl, sr], strict=True):
            data *= flip
            sub = data[seg]
            h, n = 1, self.trunc_dim
            while h < n:
                v = sub.reshape(sub.shape[0], -1, 2 * h)
                a = v[:, :, :h].copy()
                b = v[:, :, h:].copy()
                v[:, :, :h] = a + b
                v[:, :, h:] = a - b
                h *= 2
            data[seg] = sub * self.fac
            half = data.shape[1] // 2
            a = data[:, :half].copy()
            b = data[:, half:].copy()
            data[:, :half] = a + b
            data[:, half:] = a - b
        return data * 0.25


def bq2_dot(q_pos: np.ndarray, q_str: np.ndarray,
            d_pos: np.ndarray, d_str: np.ndarray) -> np.ndarray:
    """2-bit 加权点积（越大越近）。16 组 indicator matmul 累加。"""
    acc = np.zeros((q_pos.shape[0], d_pos.shape[0]), dtype=np.float32)
    for a in (0, 1):
        qa = (q_pos == a).astype(np.float32)
        for b in (0, 1):
            q_ab = qa * (q_str == b)
            if not q_ab.any():
                continue
            for c in (0, 1):
                ds_pos = (d_pos == c).astype(np.float32)
                for d in (0, 1):
                    d_cd = ds_pos * (d_str == d)
                    if not d_cd.any():
                        continue
                    pos_same = 1.0 if a == c else -1.0
                    if b and d:
                        w = 4.0
                    elif b != d:
                        w = 2.0
                    else:
                        w = 1.0
                    acc += (q_ab @ d_cd.T) * (pos_same * w)
    return acc


tr = np.fromfile(ROOT / "cohere_train.f32", dtype=np.float32).reshape(-1, DIM)[:N_TRAIN]
te = np.fromfile(ROOT / "cohere_test.f32", dtype=np.float32).reshape(-1, DIM)[:N_Q]

rot = BatchRotator(DIM, 42)
tr_r, te_r = rot.rotate(tr), rot.rotate(te)

tn = tr / np.maximum(np.linalg.norm(tr, axis=1, keepdims=True), 1e-12)
qn = te / np.maximum(np.linalg.norm(te, axis=1, keepdims=True), 1e-12)
gt = np.argsort(-(qn @ tn.T), axis=1)[:, :K]


def ov(scores: np.ndarray) -> float:
    top = np.argsort(-scores, axis=1)[:, :K]
    return float(np.mean([len(set(top[i]) & set(gt[i])) for i in range(N_Q)]) / K * 100)


print("=" * 88)
print("T1 决策实验：等比特预算下『旋转』的增益   (N_TRAIN=100K  N_Q=200  K=10)")
print("=" * 88)

# ── 1 比特：sign-only ──
print("\n[1 bit/dim]")
one_no_rot = qn @ np.sign(tr).T
one_rot = te_r @ np.sign(tr_r).T
print(f"  {'sign, 无旋转':<44}{ov(one_no_rot):>15.2f}%")
print(f"  {'sign, 有旋转':<44}{ov(one_rot):>15.2f}%")

# ── 2 比特：2-bit SM ──
print("\n[2 bit/dim]  (2-bit sign-magnitude, 加权距离)")

def sm_bits(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    alpha = np.abs(x).mean(axis=1, keepdims=True)
    return (x > 0), (np.abs(x) > alpha)


q_pos, q_str = sm_bits(te)
d_pos, d_str = sm_bits(tr)
two_no_rot = bq2_dot(q_pos, q_str, d_pos, d_str)
print(f"  {'2-bit SM, 无旋转 ( = BQ2)':<44}{ov(two_no_rot):>15.2f}%")

q_pos_r, q_str_r = sm_bits(te_r)
d_pos_r, d_str_r = sm_bits(tr_r)
two_rot = bq2_dot(q_pos_r, q_str_r, d_pos_r, d_str_r)
print(f"  {'2-bit SM, 有旋转':<44}{ov(two_rot):>15.2f}%")

# 归一化后再旋转
tn_r, qn_r = rot.rotate(tn * np.linalg.norm(tr, axis=1, keepdims=True)), \
             rot.rotate(qn * np.linalg.norm(te, axis=1, keepdims=True))
# 上面等价于直接 rotate(tr)/rotate(te) 再逐行归一
tn_r = tr_r / np.maximum(np.linalg.norm(tr_r, axis=1, keepdims=True), 1e-12)
qn_r = te_r / np.maximum(np.linalg.norm(te_r, axis=1, keepdims=True), 1e-12)
q_pos_nr, q_str_nr = sm_bits(qn_r)
d_pos_nr, d_str_nr = sm_bits(tn_r)
two_rot_norm = bq2_dot(q_pos_nr, q_str_nr, d_pos_nr, d_str_nr)
print(f"  {'2-bit SM, 有旋转 + L2 归一化':<44}{ov(two_rot_norm):>15.2f}%")

print("\n" + "=" * 88)
print("解读：等比特下『有旋转 - 无旋转』的差值即旋转的净贡献。")
print("=" * 88)

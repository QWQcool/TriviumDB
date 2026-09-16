"""验证『旋转的收益取决于数据各向同性』假设。

用各向同性高斯合成数据（方向在球面上均匀）重做同一个对比。
若旋转在合成数据上转为正增益 -> 假设成立：RaBitQ 旋转对结构化/非各向同性
数据有害，对球面分布有益。
"""
import numpy as np

DIM = 768
N_TRAIN = 50_000
N_Q = 200
K = 10
MASK64 = (1 << 64) - 1

# 复用同一旋转器（从 t1_equal_bits 复制核心逻辑）
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "t1", Path(__file__).resolve().parent / "t1_equal_bits.py")
# 不执行 t1（会跑完整流程），改为内联简化版旋转器
class BatchRotator:
    def __init__(self, dim, seed):
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


rng = np.random.default_rng(2026)
rot = BatchRotator(DIM, 42)


def run(tag: str, tr: np.ndarray, te: np.ndarray) -> None:
    tn = tr / np.maximum(np.linalg.norm(tr, axis=1, keepdims=True), 1e-12)
    qn = te / np.maximum(np.linalg.norm(te, axis=1, keepdims=True), 1e-12)
    gt = np.argsort(-(qn @ tn.T), axis=1)[:, :K]

    def ov(s: np.ndarray) -> float:
        top = np.argsort(-s, axis=1)[:, :K]
        return float(np.mean([len(set(top[i]) & set(gt[i])) for i in range(te.shape[0])]) / K * 100)

    tr_r, te_r = rot.rotate(tr), rot.rotate(te)
    no_rot = qn @ np.sign(tr).T
    with_rot = te_r @ np.sign(tr_r).T

    l1l2 = float((np.abs(tr).sum(axis=1) / np.linalg.norm(tr, axis=1)).mean())
    print(f"  [{tag}]  ‖x‖₁/‖x‖₂ = {l1l2:6.3f}  (各向同性期望 {np.sqrt(2 * DIM / np.pi):.3f})")
    print(f"      sign 无旋转 = {ov(no_rot):6.2f}%    sign 有旋转 = {ov(with_rot):6.2f}%"
          f"    旋转净增益 = {ov(with_rot) - ov(no_rot):+6.2f}pp")


print("=" * 84)
print("各向同性假设验证 (1 bit/dim, K=10)")
print("=" * 84)

# ① 各向同性高斯：坐标独立同分布 -> 方向在球面均匀
g_tr = rng.standard_normal((N_TRAIN, DIM)).astype(np.float32)
g_te = rng.standard_normal((N_Q, DIM)).astype(np.float32)
run("各向同性高斯", g_tr, g_te)

# ② 低秩 + 尖峰（模拟 embedding 的聚簇/结构化）—— 与 cohere 的 l1/l2 比值对齐
rank = 32
basis = rng.standard_normal((rank, DIM)).astype(np.float32)
coef = rng.standard_normal((N_TRAIN + N_Q, rank)).astype(np.float32)
coef = np.sign(coef) * np.abs(coef) ** 1.8            # 重尾 -> 尖峰
lowrank = (coef @ basis).astype(np.float32)
run("低秩+尖峰 (l1/l2 接近 cohere)", lowrank[:N_TRAIN], lowrank[N_TRAIN:])

print("=" * 84)

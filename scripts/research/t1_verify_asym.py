"""精确复现 bench_rbq2_precision.rs 的 RBQ-asym，并逐项二分定位。

批量实现旋转；N_TRAIN / N_Q / K 与基准对齐（100K / 200 / 10）。
约定：所有 score 统一为「越大越近」，再取 top-K 与 cosine GT 比重合。
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
    """逐位复刻 benches/bench_rbq2_precision.rs:36-110 的 FhtKacRotator（批量化）。"""

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


tr = np.fromfile(ROOT / "cohere_train.f32", dtype=np.float32).reshape(-1, DIM)[:N_TRAIN]
te = np.fromfile(ROOT / "cohere_test.f32", dtype=np.float32).reshape(-1, DIM)[:N_Q]

rot = BatchRotator(DIM, 42)
tr_r = rot.rotate(tr)
te_r = rot.rotate(te)

tn = tr / np.maximum(np.linalg.norm(tr, axis=1, keepdims=True), 1e-12)
qn = te / np.maximum(np.linalg.norm(te, axis=1, keepdims=True), 1e-12)
gt = np.argsort(-(qn @ tn.T), axis=1)[:, :K]


def ov(scores: np.ndarray) -> float:
    """scores: (N_Q, N_TRAIN)，越大越近。"""
    top = np.argsort(-scores, axis=1)[:, :K]
    return float(np.mean([len(set(top[i]) & set(gt[i])) for i in range(N_Q)]) / K * 100)


# ── 基准的逐向量因子（逐位对齐 encode_rabitq）──
l2_sqr = (tr_r * tr_r).sum(axis=1)                # ‖x_rot‖²
ip_xucb = np.abs(tr_r).sum(axis=1) * 0.5          # Σ x_i·xu_cb_i，xu_cb=±0.5
f_rescale = -l2_sqr / np.maximum(ip_xucb, 1e-12)  # 代码里就是这个（负）

sign_tr_r = np.sign(tr_r)
raw_dot = (te_r @ sign_tr_r.T) * 0.5              # Σ q_rot·(±0.5)

# 期望的 RaBitQ 量级： unit-normalized 下 f = ‖x_u‖₁/D
f_rabitq = np.abs(tr_r).sum(axis=1) / (np.sqrt(l2_sqr) * DIM)

print("=" * 88)
print("RBQ-asym 公式二分定位   (N_TRAIN=100,000  N_Q=200  K=10)")
print("=" * 88)
print(f"  f_rescale(基准)  min={f_rescale.min():.5f} max={f_rescale.max():.5f} "
      f"mean={f_rescale.mean():.5f}  全负={bool((f_rescale < 0).all())}")
print(f"  f_rabitq(应有)   min={f_rabitq.min():.5f} max={f_rabitq.max():.5f} "
      f"mean={f_rabitq.mean():.5f}  全正={bool((f_rabitq > 0).all())}")
print(f"  逐向量相对漂移   f_rescale CV={f_rescale.std() / np.abs(f_rescale).mean():.4f}, "
      f"f_rabitq CV={f_rabitq.std() / f_rabitq.mean():.4f}")
print("-" * 88)
print(f"  {'变体':<54}{'top-10 重合':>16}")
print(f"  {'-' * 54}{'-' * 16}")

no_scale = raw_dot                                   # 越大越近
bench_dir = -(f_rescale[None, :] * raw_dot)          # 基准方向（距离越小越近 -> 取负变越大越近）
correct_dir = f_rabitq[None, :] * raw_dot            # RaBitQ 方向
print(f"  {'① 无逐向量因子 (raw_dot)':<54}{ov(no_scale):>15.2f}%")
print(f"  {'② 基准 f_rescale = -‖x‖²/(0.5‖x‖₁)':<54}{ov(bench_dir):>15.2f}%")
print(f"  {'③ RaBitQ 式 f = ‖x_u‖₁/D':<54}{ov(correct_dir):>15.2f}%")

print("-" * 88)
print(f"  {'消融：把 f_rescale 换成常数（去掉逐向量漂移）':<54}")
const_dir = -np.full(N_TRAIN, np.abs(f_rescale).mean())[None, :] * raw_dot
print(f"  {'④ f = -mean(|f_rescale|) 常数':<54}{ov(const_dir):>15.2f}%")
# 取反符号，验证方向判断
print(f"  {'⑤ ②的符号取反（验证方向）':<54}{ov(-bench_dir):>15.2f}%")
print("=" * 88)

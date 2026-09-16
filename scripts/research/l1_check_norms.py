"""检查 cohere 数据是否已 L2 归一化（RaBitQ 推导前提之一）。"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIM = 768

train = np.fromfile(ROOT / "cohere_train.f32", dtype=np.float32).reshape(-1, DIM)[:20000]
test = np.fromfile(ROOT / "cohere_test.f32", dtype=np.float32).reshape(-1, DIM)

for name, arr in (("train[:20000]", train), ("test", test)):
    norms = np.linalg.norm(arr, axis=1)
    l1 = np.abs(arr).sum(axis=1)
    print(f"{name:16s} ||x||2: min={norms.min():.4f} max={norms.max():.4f} "
          f"mean={norms.mean():.4f} std={norms.std():.4f}")
    print(f"{'':16s} ||x||1 mean={l1.mean():.2f}  ratio l1/l2 mean={(l1 / norms).mean():.4f}"
          f"  (均匀随机期望 {np.sqrt(DIM * 2 / np.pi):.4f})")
    unit = np.allclose(norms, 1.0, atol=1e-3)
    print(f"{'':16s} 是否为近似单位向量: {unit}")
    print()

# RaBitQ 需要的修正因子 vs 代码里实际算的
x = train[:1]
n2 = float(x @ x.T)
n1 = float(np.abs(x).sum())
code_scale = 2 * n2 / n1                    # 代码: f_rescale 的绝对值
rabitq_scale = 2 * (n1 / np.linalg.norm(x)) / DIM  # 期望: 2*||x_u||_1 / D
print(f"代码 f_rescale  |.| = 2||x||^2/||x||_1 = {code_scale:.6f}")
print(f"RaBitQ 应有量级    = 2||x_u||_1/D      = {rabitq_scale:.6f}")
print(f"两者比值 = {code_scale / rabitq_scale:.4f}")

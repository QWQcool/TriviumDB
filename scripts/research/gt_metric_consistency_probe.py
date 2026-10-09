"""口径检查探针：shipped GT 与哪种精确搜索一致？（原始 IP / 原始 L2 / 归一化 IP = cosine）

背景（P8 队列第 1 步的意外发现）
--------------------------------
`scripts/research/ivf_recall_diagnostic.py` 测到：FAISS 精确 IVF-Flat **全表扫描**（nprobe = nlist）
对 cohere 的 shipped GT 只有 ~34.8 % R@10。若 GT 是"原始 f32 向量的精确 top-10"，这不可能。
本脚本用 numpy 精确搜索（不建索引）逐条查询核对三种口径，定位 GT 实际对应的度量与预处理：

  (i)   原始向量 + inner product          —— FAISS `IndexFlatIP` 在未归一化文件上的口径
  (ii)  原始向量 + L2                     —— FAISS 默认度量
  (iii) 归一化向量 + IP（= cosine）        —— 仓库 `prepare_all.py` / `bench_baselines.py` 的口径

结论用法：P8 的 cohere 同族对照（raw 向量、未归一化）对不上 GT，根因即在此；论文 §5.6(b) 的
"corrected" 对照必须先按 (iii) 归一化再比较。

不写任何索引，只 numpy 矩阵乘；内存 ≈ n_base × dim × 4 B（cohere 1 M × 768 ≈ 2.9 GiB）。

用法：`.venv/Scripts/python.exe scripts/research/gt_metric_consistency_probe.py cohere 768 [n_queries]`
产物：`results/t2/gt_metric_consistency_<prefix>.json`
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
K = 10


def top10(score):
    idx = np.argpartition(-score, K)[:K]
    return idx[np.argsort(-score[idx])].tolist()


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "cohere"
    dim = int(sys.argv[2]) if len(sys.argv) > 2 else 768
    nq = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    gt = np.fromfile(ROOT / f"{prefix}_groundtruth.i32", dtype=np.int32).reshape(te.shape[0], -1)
    nq = min(nq, te.shape[0])

    ntr = np.linalg.norm(tr, axis=1)
    nte = np.linalg.norm(te, axis=1)
    print(f"train={tr.shape} test={te.shape} gt={gt.shape}")
    print(f"train norm: mean={ntr.mean():.4f} std={ntr.std():.4f} min={ntr.min():.4f} max={ntr.max():.4f}")
    print(f"test  norm: mean={nte.mean():.4f} std={nte.std():.4f} min={nte.min():.4f} max={nte.max():.4f}")

    sq = np.einsum("ij,ij->i", tr, tr)
    qs = np.linspace(0, te.shape[0] - 1, nq, dtype=int).tolist()
    rows, o_ip, o_l2, o_cos = [], [], [], []
    for q in qs:
        x = te[q]
        g = gt[q][:K].tolist()
        s_ip = tr @ x
        t_ip = top10(s_ip)
        d2 = sq - 2.0 * s_ip + float(x @ x)
        t_l2 = top10(-d2)
        s_cos = s_ip / np.maximum(ntr * nte[q], 1e-12)
        t_cos = top10(s_cos)
        r1, r2, r3 = (len(set(t_ip) & set(g)), len(set(t_l2) & set(g)),
                      len(set(t_cos) & set(g)))
        o_ip.append(r1); o_l2.append(r2); o_cos.append(r3)
        rows.append({"query": int(q), "overlap_ip_raw": r1, "overlap_l2_raw": r2,
                     "overlap_ip_norm": r3, "gt_top5": g[:5]})
        print(f"q={q:<5} overlap: IP(raw)={r1}/10  L2(raw)={r2}/10  IP(norm)={r3}/10")

    mean = {"ip_raw": float(np.mean(o_ip)), "l2_raw": float(np.mean(o_l2)),
            "ip_norm": float(np.mean(o_cos))}
    if mean["ip_norm"] >= 9.9 and mean["ip_raw"] <= 5.0:
        verdict = "GT is cosine-aligned (IP on normalised vectors); raw-vector IP search cannot reproduce it"
    elif mean["ip_raw"] >= 9.9:
        verdict = "GT is raw-vector IP aligned"
    else:
        verdict = "unresolved — no tested metric reproduces the GT"
    print(f"\nmean overlap: IP(raw)={mean['ip_raw']:.1f}/10  "
          f"L2(raw)={mean['l2_raw']:.1f}/10  IP(norm)={mean['ip_norm']:.1f}/10")
    print(f"verdict: {verdict}")

    out = {"prefix": prefix, "dim": dim, "n_base": int(tr.shape[0]), "n_test": int(te.shape[0]),
           "gt_cols": int(gt.shape[1]), "queries": rows,
           "norms": {"train_mean": float(ntr.mean()), "train_std": float(ntr.std()),
                     "test_mean": float(nte.mean()), "test_std": float(nte.std())},
           "mean_overlap": mean, "verdict": verdict}
    p = ROOT / "results" / "t2" / f"gt_metric_consistency_{prefix}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

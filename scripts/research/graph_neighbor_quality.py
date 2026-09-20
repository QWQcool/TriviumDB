#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""L0 图质量探针 —— 直接测量"图的边是不是真近邻"，把 gist960 崩塌的归因
从"码的 oracle 推断"升级为"图质量的实测"。

# 为什么需要
`bench_t2_b2_partitioned` 的召回 = 「图拉取候选」+「f32 精排」。前面的 oracle 分析
只说明"码在候选池被 oracle 化后能到多少"，对**图本身好不好**只有间接证据。
本脚本直接把 L0 邻接（`bench_t2_build_recon` 的 CSR 导出）与三种"真 top-64"对比：

| 参照 | 含义 |
|---|---|
| `cos_top64` | 精确 cosine 的 64 近邻（**查询真正需要的**） |
| `w_top64` | **建图所用**的 weighted BQ2 度量的 64 近邻 |
| `c_top64` | **查询所用**的 cheap Hamming 度量（`distance_to_sig_cheap`）的 64 近邻 |

于是三条链可被分别证伪：
- 若 `overlap(L0, w_top64)` 高而 `overlap(L0, cos_top64)` 低
  ⇒ **图忠实执行了它被告知的度量，但那个度量不是 cosine** ⇒ 根因在度量选择（建图侧）。
- 若 `overlap(L0, cos_top64)` 高而召回仍低
  ⇒ 图没问题 ⇒ 根因在查询侧候选池（cheap 度量）。
- 若三者都低 ⇒ 图构造本身失效。

另附**偏置诊断**：weighted 度量在非负数据上退化为 `dim + |h_a| + |h_b| + <h_a,h_b>`
（`|h|` = strong 位计数）。若被选为"最近"的候选其 `|h|` 系统性偏离全局均值
（以 σ 计），说明该度量的排序被**与查询无关的候选偏置**主导。

用法:
    & .venv\\Scripts\\python.exe scripts\\research\\graph_neighbor_quality.py cohere gist960 gist960c
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "t2" / "gist960_collapse"
TOP = 64
N_NODES = 256
RNG_SEED = 20260917

DATASETS = {
    # 四个档位的代表 + 崩塌修复臂 + 合成对照（2026-09-20 扩充，覆盖 ≥6 数据集）
    "cohere": 768,          # competitive（QuIVer 唯一胜场）
    "coherec": 768,         # 去均值臂（中性）
    "wolt_clip": 512,       # moderate（被支配）
    "wolt_clipc": 512,      # 去均值臂（+5.3pp）
    "glove100": 100,        # usable（被支配）
    "sift128": 128,         # collapse（可修复）
    "gist960": 960,         # collapse（可修复）
    "gist960c": 960,        # 去均值臂（+49pp）
    "gauss960": 960,        # 任务不可分辨（不可修复）
    "gauss960plant": 960,   # 植入真近邻的正对照
    "minilm": 384,          # competitive（新补）
    "redcapsr42k": 512,     # moderate（新补，RedCaps 复现口径）
}


def load_csr(path):
    with open(path, "rb") as f:
        assert f.read(4) == b"T2CS", f"{path} magic 不对"
        n = int(np.fromfile(f, dtype=np.uint32, count=1)[0])
        m0 = int(np.fromfile(f, dtype=np.uint32, count=1)[0])
        entry = int(np.fromfile(f, dtype=np.uint32, count=1)[0])
        ec = int(np.fromfile(f, dtype=np.uint64, count=1)[0])
        offsets = np.fromfile(f, dtype=np.uint32, count=n + 1)
        adj = np.fromfile(f, dtype=np.uint32, count=ec)
    assert offsets[-1] == ec and offsets[0] == 0
    return n, m0, entry, offsets, adj


def normalize(a):
    a = a.copy()
    nrm = np.linalg.norm(a, axis=1)
    a *= (1.0 / np.maximum(nrm, 1e-12))[:, None]
    return a


def planes(v):
    alpha = np.abs(v).mean(axis=1)
    return v > 0.0, np.abs(v) > alpha[:, None]


def analyse(prefix, dim, rng):
    print(f"\n{'=' * 74}\n  {prefix}  dim={dim}\n{'=' * 74}")
    csr_path = ROOT / ".tmp" / f"l0_csr_{prefix}.bin"
    if not csr_path.exists():
        print(f"  缺少 {csr_path}，先跑 bench_t2_build_recon（T2_DUMP）")
        return None
    n, m0, entry, offsets, adj = load_csr(csr_path)
    tr = normalize(np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32)
                   .reshape(-1, dim))
    assert tr.shape[0] == n

    pos, strong = planes(tr)
    P = pos.astype(np.float32)
    S = strong.astype(np.float32)
    W = (2.0 * P - 1.0) * (1.0 + S)
    h = strong.sum(1).astype(np.float32)          # |h_b|：候选偏置项
    h_mu, h_sd = float(h.mean()), float(h.std())
    bias_i = P.sum(1) + S.sum(1)                  # cheap 度量的候选偏置（常量项）

    nodes = rng.choice(n, min(N_NODES, n), replace=False)
    q_cos = tr[nodes]                             # 精确 cosine（归一化后即内积）
    q_w = W[nodes]
    Pq, Sq = P[nodes], S[nodes]

    agg = {k: [] for k in ("deg", "ov_cos", "ov_w", "ov_c", "h_cos", "h_w", "h_c")}
    for i, u in enumerate(nodes):
        deg = int(offsets[u + 1] - offsets[u])
        nbrs = adj[offsets[u]:offsets[u + 1]].astype(np.int64)
        s_cos = tr @ q_cos[i]
        s_w = W @ q_w[i]                          # 加权口径：越大越近
        # ⚠️ 曾经写成 `s_c = -(距离)` 却仍用 `argpartition(s_c, TOP)` 升序取 ⇒ 取到的是**最远**的
        # 64 个邻居 ⇒ `L0∩cheap_top64` 恒为 0.00%（2026-09-20 修）。统一为"越小越近"。
        s_c = bias_i - 2.0 * (P @ Pq[i] + S @ Sq[i])      # cheap Hamming 距离（越小越近）
        s_cos[u] = -9e9
        s_w[u] = -9e9
        s_c[u] = 9e9
        t_cos = np.argpartition(-s_cos, TOP)[:TOP]
        t_w = np.argpartition(-s_w, TOP)[:TOP]
        t_c = np.argpartition(s_c, TOP)[:TOP]
        ns = set(nbrs.tolist())
        agg["deg"].append(deg)
        agg["ov_cos"].append(len(ns & set(t_cos.tolist())) / max(deg, 1))
        agg["ov_w"].append(len(ns & set(t_w.tolist())) / max(deg, 1))
        agg["ov_c"].append(len(ns & set(t_c.tolist())) / max(deg, 1))
        agg["h_cos"].append(float(h[t_cos].mean()))
        agg["h_w"].append(float(h[t_w].mean()))
        agg["h_c"].append(float(h[t_c].mean()))

    r = {"prefix": prefix, "dim": dim, "n": int(n), "n_nodes": int(len(nodes)),
         "top": TOP, "h_mean": h_mu, "h_std": h_sd,
         "mean_deg": float(np.mean(agg["deg"]))}
    print(f"  采样 {len(nodes)} 节点，平均出度 {r['mean_deg']:.1f}；"
          f"|h| 全局 {h_mu:.1f}±{h_sd:.1f}")
    print(f"  {'参照 top-64':<26}{'L0 命中率':>12}{'该参照的 |h| 均值(σ)':>24}")
    for key, label in (("cos", "精确 cosine"), ("w", "weighted BQ2（建图）"),
                       ("c", "cheap Hamming（查询）")):
        hit = float(np.mean(agg[f"ov_{key}"]) * 100)
        hb = (float(np.mean(agg[f"h_{key}"])) - h_mu) / h_sd
        r[f"overlap_{key}_pct"] = hit
        r[f"h_bias_{key}_sigma"] = hb
        print(f"  {label:<24}{hit:>11.2f}%{hb:>23.2f}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"graph_quality_{prefix}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    del tr, P, S, W, pos, strong
    return r


def main():
    names = sys.argv[1:] or ["cohere", "gist960", "gist960c"]
    rng = np.random.default_rng(RNG_SEED)
    rows = []
    for name in names:
        if name not in DATASETS:
            print(f"[错误] 未知数据集 {name}")
            return
        r = analyse(name, DATASETS[name], rng)
        if r:
            rows.append(r)
    print(f"\n{'=' * 74}\n  汇总（markdown）\n{'=' * 74}")
    print("| 数据集 | 平均出度 | L0∩cos_top64 | L0∩weighted_top64 | L0∩cheap_top64 |")
    print("|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['prefix']} | {r['mean_deg']:.1f} | {r['overlap_cos_pct']:.2f}% "
              f"| {r['overlap_w_pct']:.2f}% | {r['overlap_c_pct']:.2f}% |")


if __name__ == "__main__":
    main()

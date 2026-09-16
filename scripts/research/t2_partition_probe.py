"""T2 预实验 —— 分区质量探针（PiPNN 可行性上界）

## 背景与动机

T2 摸底（`docs/research/t2-pipnn-recon.md` §2）测出 QuIVer 批量建图的成本结构：

| 阶段 | 占比 |
|---|---|
| **束搜索寻路 / beam search** | **81.35%** |
| 前向选边 / forward select | 10.14% |
| 反向剪枝工作 / reverse work | 5.49% |
| Bitset 分配 | 2.99% |
| 反向剪枝锁等待 | 0.03% |

即：**PiPNN 要替代的是那 81% 的全局 beam search，而不是 5.5% 的反向剪枝**
（这修正了 `bootstrap-report.md` R4 的定位）。

PiPNN 的机制是：分区 → **分区内**用廉价局部搜索取候选 → 跨分区桥接。
所以它的**可行性前提**是一条可测量的事实：

> 若把候选获取限制在「本分区（∪ 少量邻接分区）」内，能不能覆盖全局 beam search
> 原本会选中的那些边？

本脚本不改任何 Rust 代码，只用**已冻结的 1M 图**（`bench_t2_build_recon` 导出的 L0 CSR）
+ 官方 GT，测量三个量：

| 指标 | 含义 | 判定 |
|---|---|---|
| **(a) 跨分区边率** | 冻结图中两端属不同分区的有向边占比 | 越低 → 分区内候选越充分，桥接需求越少 |
| **(b) GT 同分区召回上界** | 查询真 top-10 落在「查询所属分区」∪「J 个最近邻分区」内的比例 | **这是 PiPNN 的召回天花板**：无论分区内建图多好，都不可能超过它 |
| **(c) 分区均衡度** | 分区大小的 min/median/max 与基尼系数 | 各向异性数据（本数据集已实测）会让 k-means 失衡，影响并行负载均衡 |

## 方法

- 分区器：k-means（Lloyd），在 **50K 降采样**上拟合，再对全量 assign（用 BLAS matmul，秒级）
- 「邻接分区」：按**分区质心**到查询的距离排序（而非查询到具体点），J ∈ {1, 5, 10, 25}
- 对照组：**随机哈希分区**（`hash(i) % k`）作为下界，验证指标本身有区分度

## 用法

```
python scripts/research/t2_partition_probe.py
```
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

# Windows 控制台默认 GBK，中文与制表符会乱码/抛 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DIM = 768
N_QUERIES = 1000
TOP_K = 10
KS = [16, 64, 256]
J_LIST = [1, 5, 10, 25]
# B1 可达率曲线用的 J（含 2/3，便于看低 J 处的斜率）
J_LIST_B1 = [1, 2, 3, 5, 10, 25]
SAMPLE_FIT = 50_000
KM_ITERS = 25
CSR_PATH = os.path.join(".tmp", "l0_csr.bin")


def log(msg: str) -> None:
    print(msg, flush=True)


def load_csr(path: str) -> tuple[int, int, int, np.ndarray, np.ndarray]:
    """读取 bench_t2_build_recon 导出的 L0 CSR。

    布局: [magic 'T2CS' 4B][n u32][m0 u32][entry u32][edge_count u64]
          [offsets: (n+1)×u32][adj: edge_count×u32]
    """
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"T2CS":
            raise ValueError(f"{path} magic 不是 T2CS，实际 {magic!r}")
        n = int(np.fromfile(f, dtype=np.uint32, count=1)[0])
        m0 = int(np.fromfile(f, dtype=np.uint32, count=1)[0])
        entry = int(np.fromfile(f, dtype=np.uint32, count=1)[0])
        edge_count = int(np.fromfile(f, dtype=np.uint64, count=1)[0])
        offsets = np.fromfile(f, dtype=np.uint32, count=n + 1)
        adj = np.fromfile(f, dtype=np.uint32, count=edge_count)
    if offsets[0] != 0 or offsets[-1] != edge_count:
        raise ValueError(f"CSR 头尾不一致: {offsets[0]} / {offsets[-1]} vs {edge_count}")
    if offsets.shape[0] != n + 1 or adj.shape[0] != edge_count:
        raise ValueError("CSR 长度不符")
    return n, m0, entry, offsets, adj


def l2_normalize(x: np.ndarray) -> np.ndarray:
    nrm = np.linalg.norm(x, axis=1, keepdims=True)
    nrm[nrm < 1e-12] = 1.0
    return x / nrm


def kmeans_fit_assign(
    x: np.ndarray, k: int, sample: np.ndarray, iters: int, seed: int = 42
) -> tuple[np.ndarray, np.ndarray]:
    """在 sample 上跑 Lloyd k-means，返回 (centroids, 全量 assign)。

    距离用平方欧氏；数据已 L2 归一化，故等价于按 cosine 分区。
    """
    rng = np.random.default_rng(seed)
    cent = sample[rng.choice(sample.shape[0], size=k, replace=False)].copy()
    m = sample.shape[0]
    rows = np.arange(m)
    for _ in range(iters):
        # ‖a-b‖² = ‖a‖² - 2a·b + ‖b‖²，a 已归一化 ⇒ 只需 -2a·b + ‖b‖²
        d = -2.0 * (sample @ cent.T) + (cent * cent).sum(axis=1)[None, :]
        lab = np.argmin(d, axis=1)
        cnt = np.bincount(lab, minlength=k).astype(np.float64)
        # one-hot @ sample 走 BLAS，比 np.add.at 快两个数量级（后者是标量 scatter）
        onehot = np.zeros((m, k), dtype=np.float32)
        onehot[rows, lab] = 1.0
        cent = (onehot.T @ sample) / np.maximum(cnt[:, None], 1.0)
        empty = cnt == 0
        if empty.any():
            cent[empty] = sample[rng.choice(m, size=int(empty.sum()), replace=False)]
    d = -2.0 * (x @ cent.T) + (cent * cent).sum(axis=1)[None, :]
    return cent, np.argmin(d, axis=1).astype(np.int32)


def assign_to(x: np.ndarray, cent: np.ndarray) -> np.ndarray:
    d = -2.0 * (x @ cent.T) + (cent * cent).sum(axis=1)[None, :]
    return np.argmin(d, axis=1).astype(np.int32)


def nn_partitions(qn: np.ndarray, cent: np.ndarray) -> np.ndarray:
    """每个查询按质心距离排序的分区索引（含自身），形状 (nq, k)。"""
    d = -2.0 * (qn @ cent.T) + (cent * cent).sum(axis=1)[None, :]
    return np.argsort(d, axis=1).astype(np.int32)


def gini(counts: np.ndarray) -> float:
    c = np.sort(counts.astype(np.float64))
    n = c.size
    cum = np.cumsum(c)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def edge_reachability(
    assign: np.ndarray,
    cent: np.ndarray,
    x: np.ndarray,
    offsets: np.ndarray,
    adj: np.ndarray,
    k: int,
    j_list: list[int],
) -> dict:
    """B1 —— 分区受限候选池对**现有邻居**的可达率上界。

    对边 u→v，「可达」当且仅当 `part[v]` 落在「按质心距离离 u 最近的 J 个分区」内。

    这是**与选择算法无关的必要条件**：不在候选池里的邻居，任何基于该池的构造算法
    （无论 `vamana_select` 还是别的）都**不可能**选出来。因此它给出 PiPNN 的
    第一阶可行性信号，且能可靠止损：

      - 可达率高 ⇒ 分区内候选足以覆盖全局束搜索选中的边 → 值得进入 B2 真构造
      - 可达率低 ⇒ 候选池根本不含这些边 → 分区化必然丢质量，**立即止损**

    此外它是 B1 而非 C3 的严格加强版：C3 只看「边是否跨分区」，本函数看
    「**该边的目标分区是否在源节点的 J 近邻分区内**」——即真正决定候选可用性的量。
    """
    n = x.shape[0]
    # 逐节点的分区距离序：part_rank[u, p] = 分区 p 在 u 的距离序中的名次
    d = -2.0 * (x @ cent.T) + (cent * cent).sum(axis=1)[None, :]
    order = np.argsort(d, axis=1, kind="stable")
    del d
    part_rank = np.empty((n, k), dtype=np.int16)
    part_rank[np.arange(n, dtype=np.int64)[:, None], order] = np.arange(k, dtype=np.int16)
    del order

    deg = np.diff(offsets.astype(np.int64))
    src = np.repeat(np.arange(n, dtype=np.int32), deg)
    rank_of_edge = part_rank[src, assign[adj]]  # (E,) int16：每条边的目标分区名次
    del part_rank

    out: dict[int, dict] = {}
    for j in j_list:
        covered = (rank_of_edge < j).astype(np.float64)
        hit = np.bincount(src, weights=covered, minlength=n)
        node_rate = hit / np.maximum(deg, 1)
        out[j] = {
            "edge_coverage_pct": float(covered.mean()) * 100.0,
            "node_mean_pct": float(node_rate.mean()) * 100.0,
            "node_p10_pct": float(np.percentile(node_rate, 10)) * 100.0,
            "node_p50_pct": float(np.percentile(node_rate, 50)) * 100.0,
            "node_min_pct": float(node_rate.min()) * 100.0,
            "nodes_below_50pct": int((node_rate < 0.5).sum()),
        }
    return out


def eval_partition(
    name: str,
    assign: np.ndarray,
    cent: np.ndarray | None,
    q_assign: np.ndarray | None,
    offsets: np.ndarray,
    adj: np.ndarray,
    gt: np.ndarray,
    qn: np.ndarray,
    k: int,
) -> dict:
    """计算 (a) 跨分区边率、(b) GT 同分区/邻接分区召回上界、(c) 分区均衡度。

    ⚠️ `q_assign` 必须是**查询自身**的分区（由 `assign_to(qn, cent)` 得到）。
    早先版本误用 `assign[q_idx]`，而 `q_idx = arange(1000)` 是**训练集**下标，
    得到的是"训练向量 i 所在分区"，与查询无关 —— 该列数值（6.1/1.6/0.5%）因此无意义。
    已在 2026-09-16 修正（正确值应等于 J=1 列）。
    """
    # ── (a) 跨分区边率 ──
    src = np.repeat(
        np.arange(offsets.size - 1, dtype=np.int32),
        np.diff(offsets.astype(np.int64)).astype(np.int64),
    )
    cross_rate = 1.0 - float((assign[src] == assign[adj]).mean())

    # ── (c) 分区均衡度 ──
    counts = np.bincount(assign, minlength=k)
    bal = {
        "min": int(counts.min()),
        "median": int(np.median(counts)),
        "max": int(counts.max()),
        "ratio_max_min": float(counts.max() / max(counts.min(), 1)),
        "gini": gini(counts),
    }

    # ── (b) GT 召回上界 ──
    nq, nk = gt.shape
    gt_part = assign[gt]  # (nq, nk)
    # M[i,p] = 查询 i 的真 top-k 中落在分区 p 的个数
    M = np.zeros((nq, k), dtype=np.int32)
    np.add.at(M, (np.arange(nq, dtype=np.int64)[:, None].repeat(nk, 1), gt_part), 1)

    own = None
    ceilings: dict[int, float] = {}
    if q_assign is not None:
        own = float(M[np.arange(nq), q_assign].sum()) / (nq * nk) * 100.0
        # 邻接分区只在有几何结构（质心）时才有定义；随机对照不适用
        if cent is not None:
            near = nn_partitions(qn, cent)  # (nq, k) 按质心距离升序
            for j in J_LIST:
                jj = min(j, near.shape[1])
                vals = np.take_along_axis(M, near[:, :jj], axis=1).sum(axis=1)
                ceilings[j] = float(vals.sum()) / (nq * nk) * 100.0

    return {
        "name": name,
        "k": int(counts.size),
        "cross_edge_pct": cross_rate * 100.0,
        "own_partition_ceiling_pct": own,
        "ceilings_pct": ceilings,
        "balance": bal,
    }


def main() -> int:
    t0 = time.time()
    for p in ["cohere_train.f32", "cohere_test.f32", "cohere_groundtruth.i32", CSR_PATH]:
        if not os.path.exists(p):
            log(f"缺少 {p}")
            return 1

    log("=" * 74)
    log("  T2 预实验 — 分区质量探针（PiPNN 可行性上界）")
    log("=" * 74)

    n, m0, entry, offsets, adj = load_csr(CSR_PATH)
    log(f"  载入图: n={n} m0={m0} entry={entry} 边={adj.size} 平均度={adj.size / n:.1f}")

    x = np.fromfile("cohere_train.f32", dtype=np.float32).reshape(-1, DIM)
    q = np.fromfile("cohere_test.f32", dtype=np.float32).reshape(-1, DIM)[:N_QUERIES]
    gt_all = np.fromfile("cohere_groundtruth.i32", dtype=np.int32)
    k_gt = gt_all.size // q.shape[0]
    gt = gt_all.reshape(q.shape[0], k_gt)[:, :TOP_K].astype(np.int64)

    x = l2_normalize(x)
    qn = l2_normalize(q)
    log(
        f"  载入数据: train {x.shape} test {q.shape} GT {gt.shape} (K={k_gt})  "
        f"{time.time() - t0:.1f}s"
    )

    rng = np.random.default_rng(7)
    fit_idx = rng.choice(n, size=min(SAMPLE_FIT, n), replace=False)
    sample = x[fit_idx]

    # 守卫：GT 下标合法性
    assert gt.min() >= 0 and gt.max() < n, "GT 下标越界"
    log(f"  守卫 GT 下标合法: [{gt.min()}, {gt.max()}]  in [0, {n})  PASS")

    results = []

    # ── 对照组：随机哈希分区 ──
    # 查询用同一哈希分配 ⇒ 期望召回上界 ≈ 100/k %。这是指标管线本身的正确性自检：
    # 若实测显著偏离 100/k，说明 M 矩阵 / assign 索引有误。
    for k in KS:
        a = (np.arange(n, dtype=np.int64) * 2654435761 % k).astype(np.int32)
        qa = (np.arange(q.shape[0], dtype=np.int64) * 2654435761 % k).astype(np.int32)
        r = eval_partition(f"随机哈希 k={k}", a, None, qa, offsets, adj, gt, qn, k)
        results.append(r)
        exp = 100.0 / k
        log(
            f"  [{r['name']:<16}] 跨分区边 {r['cross_edge_pct']:5.1f}%  "
            f"本分区召回上界 {r['own_partition_ceiling_pct']:5.1f}%  "
            f"(期望 ≈ {exp:.1f}%)"
        )

    # ── k-means 分区 ──
    for k in KS:
        t = time.time()
        cent, assign = kmeans_fit_assign(x, k, sample, KM_ITERS)
        q_assign = assign_to(qn, cent)  # ★ 查询**自身**的分区
        r = eval_partition(f"k-means k={k}", assign, cent, q_assign, offsets, adj, gt, qn, k)
        r["fit_seconds"] = time.time() - t
        # ── B1：分区受限候选池的邻居可达率上界 ──
        t_b1 = time.time()
        r["reachability"] = edge_reachability(assign, cent, x, offsets, adj, k, J_LIST_B1)
        r["b1_seconds"] = time.time() - t_b1
        results.append(r)
        ceil_str = "  ".join(f"J={j}:{r['ceilings_pct'][j]:5.1f}%" for j in J_LIST)
        log(
            f"  [{r['name']:<16}] 跨分区边 {r['cross_edge_pct']:5.1f}%  "
            f"本分区 {r['own_partition_ceiling_pct']:5.1f}%  {ceil_str}  "
            f"({r['fit_seconds']:.1f}s)"
        )
        log(
            f"    └ 分区均衡: min={r['balance']['min']} med={r['balance']['median']} "
            f"max={r['balance']['max']} max/min={r['balance']['ratio_max_min']:.1f} "
            f"gini={r['balance']['gini']:.3f}"
        )
        rc = r["reachability"]
        log(
            "    └ B1 邻居可达率上界(边覆盖率 / 节点均值 / 节点p10): "
            + "  ".join(f"J={j}: {rc[j]['edge_coverage_pct']:.1f}%/{rc[j]['node_mean_pct']:.1f}%/{rc[j]['node_p10_pct']:.1f}%" for j in J_LIST_B1)
            + f"  ({r['b1_seconds']:.1f}s)"
        )

    # 守卫：随机对照必须落在 100/k 附近
    for r in results:
        if r["name"].startswith("随机哈希"):
            exp = 100.0 / r["k"]
            got = r["own_partition_ceiling_pct"]
            assert abs(got - exp) < 2.0, (
                f"守卫 指标管线失败: {r['name']} 召回上界 {got:.1f}% vs 期望 {exp:.1f}%"
            )
    log("  守卫 指标管线（随机对照 ≈ 100/k%）PASS")

    # ── markdown ──
    log("\n### T2 预实验：分区质量指标（1M × 768，官方 GT，1000 查询）\n")
    log("| 分区方案 | 跨分区边率 | 本分区召回上界 | J=1 | J=5 | J=10 | J=25 | 分区 max/min | gini |")
    log("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        c = r["ceilings_pct"]
        cells = " | ".join(f"{c[j]:.1f}%" if c and j in c else "—" for j in J_LIST)
        own = r["own_partition_ceiling_pct"]
        own_str = f"{own:.1f}%" if own is not None else "—"
        log(
            f"| {r['name']} | {r['cross_edge_pct']:.1f}% | {own_str} | {cells} | "
            f"{r['balance']['ratio_max_min']:.1f} | {r['balance']['gini']:.3f} |"
        )

    # ── B1 markdown ──
    log("\n### T2 B1：分区受限候选池的邻居可达率上界（全量 64M 边，非采样）\n")
    log("> 定义：边 `u→v` 可达 ⟺ `part[v]` 位于「离 `u` 最近的 J 个分区」内。")
    log("> 这是**与选择算法无关的必要条件**——不在池里的邻居，任何构造算法都选不出来。\n")
    log("| 分区 | J | 边覆盖率 | 节点均值 | 节点 p10 | 节点中位 | 可达率<50% 节点数 |")
    log("|---|---|---|---|---|---|---|")
    for r in results:
        rc = r.get("reachability")
        if not rc:
            continue
        for j in J_LIST_B1:
            v = rc[j]
            log(
                f"| {r['name']} | {j} | {v['edge_coverage_pct']:.1f}% | "
                f"{v['node_mean_pct']:.1f}% | {v['node_p10_pct']:.1f}% | "
                f"{v['node_p50_pct']:.1f}% | {v['nodes_below_50pct']:,} |"
            )

    os.makedirs(os.path.join("results", "t2"), exist_ok=True)
    out = os.path.join("results", "t2", "partition_probe.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "n": n,
                "m0": m0,
                "entry": entry,
                "edges": int(adj.size),
                "n_queries": int(q.shape[0]),
                "top_k": TOP_K,
                "ks": KS,
                "j_list": J_LIST,
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    log(f"\n  已写出 {out}")
    log(f"  总耗时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

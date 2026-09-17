#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P1 —— 码估计信噪比 SNR 探针（**探索后续研究路径的闸门实验**）

# 要回答的问题
已发表版本（PVLDB Vol. 20, 2027；arXiv `2605.02171`）给出的是**两个必要条件**
（Finding 1：符号位要有判别力；Finding 4：角间隙要够大）与**四档按观测召回划的事后标签**。
本探针检验一个**先算后测的单一预测量**能否替代它们：

    SNR = (GT10 − GT11) / σ_code
    信号 = 第 10 名与"第 11 名"的真实 cosine 间隔（top-10 是否可分辨）
    噪声 = 码的相似度估计在该区域的残差标准差（cosine 尺度）

**为什么是 min 而不是某一个度量**：本引擎**建图用 weighted（6 类权重），查询 L0 用 cheap（纯 Hamming）**
（`quiver.rs:1272-1281`）。两个度量不一致时，**召回由更差的那个决定**（已在
`t2-gist960-collapse.md` §5.1 实测：gist960 ≈ weighted oracle、gauss960 < 两个 oracle）。
故同时报 `SNR_w` / `SNR_c`，并定义 **`SNR_eff = min(SNR_w, SNR_c)`**（最弱环）。

# 预注册定义（先写死，再跑）
1. 采样 `NQ=200` 个查询（确定性 rng 种子）。
2. **全局标定**：抽 `N_PAIRS=100_000` 个随机对，对每个度量做仿射拟合 `cos ≈ a + b·score`
   （weighted 的 score = `<w_i,w_j>`，越大越近；cheap 的 score = `−Hamming`，越大越近）。
3. **局部噪声**：对每个查询取其**真实 top-200** 候选，计算残差 `cos − (a + b·score)` 的标准差
   ⇒ `σ_code`（这正是排序决策发生的区域）。跨查询取均值。
4. `gap` = 每个查询的 `cos[9] − cos[10]`，跨查询取**中位**（稳健，避免并列长尾）。
5. `SNR = gap / σ_code`；`SNR_eff = min(SNR_w, SNR_c)`。
6. 附带：**码自身 top-10 命中率**（全扫描、无 f32 精排）——这是论文
   "Practical Compatibility Test（top-K 重叠率 >~50%）"的同族量，但我们是**全库 1M 扫描**
   （比论文的 ~10K 样本协议**更严格**），故不可直接与论文阈值比较。

# 可证伪守卫（与 `bq2_code_ceiling.py` 同源，全部必须 PASS）
在 512 个随机对上，用**独立实现的位运算**验证本脚本用到的两个恒等式：
  (a) `Hamming_float` == `popcount(pos_a^pos_b) + popcount(strong_a^strong_b)`
  (b) `<w_a,w_b>` == `4·dim − weighted_6class(a,b)`，`w = (2·pos−1)(1+strong)`
最大差必须为 0，否则本探针全部数字作废（exit 1）。

# 判据（在 `paper-readiness.md` 预注册）
在**论文自己的数据集**上，`SNR_eff` 与论文 Table 11 的 `R@10@ef=64` 的 **Spearman 秩相关 ≥ 0.9**。
- 成立 ⇒ 可作论文核心图，继续 P2（补齐论文 12 个数据集）；
- 不成立 ⇒ 退回"符号平面信息率 + 图保真度 + 任务可解性"三指标并列写法，并如实报告 SNR 失败。

用法:
    & .venv\\Scripts\\python.exe scripts\\research\\code_snr_probe.py
    & .venv\\Scripts\\python.exe scripts\\research\\code_snr_probe.py gist960 gist960c cohere
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 复用已验证的分析式与守卫（`bq2_code_ceiling.py` 的首行守卫证明它们与 `src/index/bq.rs` 逐位一致）
from bq2_code_ceiling import bq2_planes, l2_normalize_inplace, ref_cheap, ref_weighted  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "t2" / "gist960_collapse"
OUT_JSON = OUT_DIR / "snr_probe.json"

NQ = 200            # 采样的查询数
N_PAIRS = 100_000   # 全局标定的随机对数
LOCAL_TOP = 200     # 局部噪声窗口（真实 top-K）
TOP_K = 10
QBATCH = 16         # 查询批大小（GEMM 输出 n_cand × B）
RNG_SEED = 20260917

# (前缀, 维数, 论文 Table 11 的 R@10@ef=64 或本仓实测值, 备注)
# 论文 4 行取自 arXiv HTML（待与 PDF 复核）；其余为本仓实测（同一 harness，见 paper-readiness.md §1）
DATASETS = [
    ("cohere",      768,  94.63, "论文 Table 11 = 95.13（Δ−0.50）"),
    ("glove100",    100,  32.82, "论文 Table 11 = 32.08（Δ+0.74）"),
    ("sift128",     128,  15.77, "论文 Table 11 = 14.85（Δ+0.92）"),
    ("gist960",     960,   2.10, "论文 Table 11 = 2.01（Δ+0.09）"),
    # 派生/判别臂（本会话，同一 harness）
    ("gist960c",    960,  39.74, "去均值（本会话）"),
    ("sift128c",    128,  30.64, "去均值（本会话）"),
    ("gauss960",    960,   0.41, "T-ctrl 各向同性高斯 → 对应论文 Random-Sphere(0.40)"),
    ("gauss960plant", 960, 99.70, "T-plant 植入真近邻（构造性上界对照）"),
]
PAPER_ROWS = {"cohere", "glove100", "sift128", "gist960"}


def spearman(x, y):
    """Spearman 秩相关（无 scipy 依赖）"""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    def rank(v):
        order = np.argsort(v, kind="stable")
        r = np.empty_like(v)
        r[order] = np.arange(len(v), dtype=np.float64)
        # 并列取平均秩
        _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
        if (cnt > 1).any():
            sums = np.zeros_like(cnt, dtype=np.float64)
            np.add.at(sums, inv, r)
            r = (sums / cnt)[inv]
        return r

    rx, ry = rank(x), rank(y)
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    denom = np.sqrt((rx * rx).sum() * (ry * ry).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else float("nan")


def guard(rng, dim):
    """可证伪守卫：本探针用到的两个恒等式与 `src/index/bq.rs` 的逐位实现一致"""
    n = 512
    a = rng.standard_normal((n, dim), dtype=np.float32)
    b = rng.standard_normal((n, dim), dtype=np.float32)
    a[: n // 2] = np.abs(a[: n // 2])          # 混入非负（复现 GIST/SIFT 退化）
    b[: n // 2] = np.abs(b[: n // 2])
    l2_normalize_inplace(a, dim)
    l2_normalize_inplace(b, dim)
    pa, sa = bq2_planes(a)
    pb, sb = bq2_planes(b)

    ham_ref = ref_cheap(pa, sa, pb, sb)
    ham_ana = (
        pa.sum(1) + pb.sum(1) + sa.sum(1) + sb.sum(1)
        - 2 * ((pa & pb).sum(1) + (sa & sb).sum(1))
    )
    w_ref = ref_weighted(pa, sa, pb, sb, dim)
    wa = (2.0 * pa.astype(np.float32) - 1.0) * (1.0 + sa.astype(np.float32))
    wb = (2.0 * pb.astype(np.float32) - 1.0) * (1.0 + sb.astype(np.float32))
    w_ana = 4 * dim - np.einsum("ij,ij->i", wa, wb)

    d_ham = int(np.abs(ham_ref - ham_ana).max())
    d_w = float(np.abs(w_ref - w_ana).max())
    print(f"  守卫 dim={dim}: |ΔHamming|={d_ham}  |Δ<w,w>|={d_w}  "
          f"{'PASS' if d_ham == 0 and d_w == 0 else 'FAIL'}")
    if d_ham != 0 or d_w != 0:
        sys.exit(1)


def fit_affine(score, cos):
    """一阶仿射拟合 cos ≈ a + b·score，返回 (a, b)"""
    A = np.vstack([np.ones_like(score), score]).T
    coef, *_ = np.linalg.lstsq(A, cos, rcond=None)
    return float(coef[0]), float(coef[1])


def probe(prefix, dim, recall_ef64, note, rng):
    print(f"\n{'=' * 74}\n  {prefix}  dim={dim}   R@10@ef=64 = {recall_ef64:.2f}%   [{note}]\n{'=' * 74}")
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    te = np.fromfile(ROOT / f"{prefix}_test.f32", dtype=np.float32).reshape(-1, dim)
    gt_all = np.fromfile(ROOT / f"{prefix}_groundtruth.i32", dtype=np.int32)
    n, nq_all = tr.shape[0], te.shape[0]
    gt = gt_all.reshape(nq_all, -1)[:, :TOP_K]
    l2_normalize_inplace(tr, dim)
    l2_normalize_inplace(te, dim)
    q0 = te[: min(nq_all, 64)]
    cos_max = float((q0 @ tr[:200_000].T).max())
    assert cos_max <= 1.0 + 1e-5, f"cosine={cos_max} > 1 ⇒ 归一化漏了"

    pos, strong = bq2_planes(tr)
    P = pos.astype(np.float32)
    S = strong.astype(np.float32)
    W = (2.0 * P - 1.0) * (1.0 + S)               # <w_i,w_j> = weighted 分数（越大越近）
    rs = P.sum(1) + S.sum(1)                       # cheap 的候选常量项
    # ⚠️ 查询侧必须用**测试向量自己**的码（不能用 train[q] 的行——那会让码的 top-1 变成候选自身，
    #    导致 code-only 命中恒为 0）。本脚本的 `code_only_top10_*` 就是这条的哨兵（见 §守卫）。
    qpos, qstrong = bq2_planes(te)
    Pt = qpos.astype(np.float32)
    St = qstrong.astype(np.float32)
    Wt = (2.0 * Pt - 1.0) * (1.0 + St)
    rq = Pt.sum(1) + St.sum(1)

    # ── 全局标定：N_PAIRS 个随机对 ──
    i = rng.integers(0, n, N_PAIRS)
    j = rng.integers(0, n, N_PAIRS)
    bad = i == j
    j[bad] = (j[bad] + 1) % n
    cos_p = np.einsum("ij,ij->i", tr[i], tr[j])
    sc_w = np.einsum("ij,ij->i", W[i], W[j])
    sc_c = -(rs[i] + rs[j]
             - 2.0 * (np.einsum("ij,ij->i", P[i], P[j]) + np.einsum("ij,ij->i", S[i], S[j])))
    aw, bw = fit_affine(sc_w, cos_p)
    ac, bc = fit_affine(sc_c, cos_p)
    r_w = cos_p - (aw + bw * sc_w)
    r_c = cos_p - (ac + bc * sc_c)
    print(f"  全局标定（{N_PAIRS:,} 对）:  R²_w = {1 - r_w.var() / cos_p.var():+.4f}"
          f"   R²_c = {1 - r_c.var() / cos_p.var():+.4f}")
    del cos_p, sc_w, sc_c, r_w, r_c

    # ── 局部噪声 + gap + 码 top-10 命中 ──
    qs = rng.choice(nq_all, min(NQ, nq_all), replace=False)
    sig_w, sig_c, gaps = [], [], []
    hit10_w = hit10_c = 0
    for b0 in range(0, len(qs), QBATCH):
        qb = qs[b0 : b0 + QBATCH]
        TC = tr @ te[qb].T                                   # (n, B) 真实 cosine
        SW = W @ Wt[qb].T                                    # (n, B) weighted 分数
        SC = -(rs[:, None] + rq[qb][None, :]
               - 2.0 * ((P @ Pt[qb].T) + (S @ St[qb].T)))    # (n, B) cheap 分数
        for bi, q in enumerate(qb):
            tc, sw, sc = TC[:, bi], SW[:, bi], SC[:, bi]
            order = np.argsort(-tc, kind="stable")
            gaps.append(float(tc[order[9]] - tc[order[10]]))
            loc = order[:LOCAL_TOP]
            sig_w.append(float((tc[loc] - (aw + bw * sw[loc])).std()))
            sig_c.append(float((tc[loc] - (ac + bc * sc[loc])).std()))
            g = gt[q]
            hit10_w += int(np.isin(np.argpartition(-sw, TOP_K)[:TOP_K], g).sum())
            hit10_c += int(np.isin(np.argpartition(-sc, TOP_K)[:TOP_K], g).sum())
        del TC, SW, SC

    gap = float(np.median(gaps))
    sw_, sc_ = float(np.mean(sig_w)), float(np.mean(sig_c))
    snr_w, snr_c = gap / sw_, gap / sc_
    ov_w = hit10_w / (len(qs) * TOP_K) * 100
    ov_c = hit10_c / (len(qs) * TOP_K) * 100
    print(f"  gap = GT10−GT11（中位）      = {gap:.6f}")
    print(f"  σ_code  local: weighted {sw_:.5f} | cheap {sc_:.5f}")
    print(f"  ★ SNR: weighted {snr_w:.4f} | cheap {snr_c:.4f} | **eff=min {min(snr_w, snr_c):.4f}**")
    print(f"  码自身 top-10 命中（全扫，无精排）: weighted {ov_w:.2f}% | cheap {ov_c:.2f}%"
          f"   （论文探针同族量，但我们是全库扫描，更严格）")
    # ★ 哨兵：查询侧若误用 train[q] 的行做码，码的 top-1 会变成候选自身 ⇒ 命中恒为 0。
    #   `bq2_code_ceiling.py` 的已知值（glove100 32.23/19.31、sift128 3.11/10.03）是对拍基准。
    assert max(ov_w, ov_c) > 0.5, (
        f"{prefix}: 码自身 top-10 命中 = {ov_w:.2f}/{ov_c:.2f}% ⇒ 怀疑查询侧码索引有误"
        f"（应用测试向量自己的签名，而非 train[q] 的行）"
    )
    return {
        "prefix": prefix, "dim": dim, "recall_ef64": recall_ef64, "note": note,
        "gap_med": gap, "sigma_w": sw_, "sigma_c": sc_,
        "snr_w": snr_w, "snr_c": snr_c, "snr_eff": min(snr_w, snr_c),
        "code_only_top10_w_pct": ov_w, "code_only_top10_c_pct": ov_c,
        "nq_used": int(len(qs)), "cos_max_guard": cos_max,
    }


CANDIDATE_PREDICTORS = (
    ("snr_eff", "SNR_eff = min(SNR_w, SNR_c)"),           # ★ 预注册主判据
    ("snr_w", "SNR_w"),
    ("snr_c", "SNR_c"),
    ("gap_med", "gap 单独"),
    ("min_code", "min(码自身 top-10 命中 w,c)"),          # 探索性（论文探针族 + 两度量取弱环）
    ("code_only_top10_w_pct", "码自身 top-10 命中 (w)"),
    ("code_only_top10_c_pct", "码自身 top-10 命中 (c)"),
)


def evaluate(rows):
    """打印汇总表 + 各候选预测量的 Spearman 秩相关"""
    print(f"\n{'=' * 100}\n  汇总\n{'=' * 100}")
    print("| 数据集 | dim | R@10@ef=64 | gap | σ_w | σ_c | SNR_w | SNR_c | SNR_eff "
          "| 码top10(w) | 码top10(c) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['prefix']} | {r['dim']} | {r['recall_ef64']:.2f}% | {r['gap_med']:.6f} "
              f"| {r['sigma_w']:.5f} | {r['sigma_c']:.5f} | {r['snr_w']:.4f} | {r['snr_c']:.4f} "
              f"| **{r['snr_eff']:.4f}** | {r['code_only_top10_w_pct']:.2f}% "
              f"| {r['code_only_top10_c_pct']:.2f}% |")

    for r in rows:
        r["min_code"] = min(r["code_only_top10_w_pct"], r["code_only_top10_c_pct"])
    subsets = {
        "论文 12 行中我们有的 4 行": [r for r in rows if r["prefix"] in PAPER_ROWS],
        "+ Random-Sphere 对应臂（gauss960）": [r for r in rows
                                               if r["prefix"] in PAPER_ROWS | {"gauss960"}],
        "全部真实臂（不含构造性 T-plant）": [r for r in rows if r["prefix"] != "gauss960plant"],
        "全部 8 行（含 T-plant）": rows,
    }
    print(f"\n  ★ 预注册主判据：在论文自己的数据集上，SNR_eff 与 R@10@ef=64 的 Spearman ρ ≥ 0.9")
    print(f"    —— 其中 Random-Sphere 是论文 12 行之一，我们以 gauss960（各向同性高斯，"
          f"实测 {[r['recall_ef64'] for r in rows if r['prefix']=='gauss960'][0]:.2f}% "
          f"vs 论文 0.40%）作其对应臂。\n")
    print(f"  {'子集':<34}{'n':>3}  " + "".join(f"{k:>26}" for k, _ in CANDIDATE_PREDICTORS))
    verdict = {}
    for name, sel in subsets.items():
        if len(sel) < 3:
            continue
        cells = []
        for key, _ in CANDIDATE_PREDICTORS:
            rho = spearman([r[key] for r in sel], [r["recall_ef64"] for r in sel])
            verdict.setdefault(key, {})[name] = rho
            cells.append(f"{rho:>+26.4f}")
        print(f"  {name:<34}{len(sel):>3}  " + "".join(cells))
    print("\n  说明（诚实性）：上表中只有 `snr_eff` 是**预注册主判据**；其余为**事后探索**，"
          "证据强度更低。")
    return verdict


def _load_rows():
    """读已落盘的行（兼容早期把 rows 存成 list 的格式）"""
    if not OUT_JSON.exists():
        return {}
    raw = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("rows", {})
    if isinstance(raw, list):
        raw = {r["prefix"]: r for r in raw}
    return raw


def main():
    if "--report" in sys.argv:
        rows = sorted(_load_rows().values(), key=lambda r: -r["recall_ef64"])
        evaluate(rows)
        print(f"\n  （读自 {OUT_JSON.relative_to(ROOT)}，共 {len(rows)} 行）")
        return

    wanted = [a for a in sys.argv[1:] if not a.startswith("--")]
    grng = np.random.default_rng(RNG_SEED)
    guard(grng, 128)
    guard(grng, 960)

    old = _load_rows()
    for prefix, dim, recall, note in DATASETS:
        if wanted and prefix not in wanted:
            continue
        # 每个数据集用**独立且确定**的种子 ⇒ 单跑/合跑/顺序都不影响该行的数值
        rng = np.random.default_rng([RNG_SEED, dim, sum(map(ord, prefix))])
        old[prefix] = probe(prefix, dim, recall, note, rng)

    rows = sorted(old.values(), key=lambda r: -r["recall_ef64"])
    verdict = evaluate(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "definition": {
            "gap": "median(GT[9]-GT[10]) over sampled queries",
            "sigma": "std of (cos - affine_fit(score)) over each query's true top-200",
            "snr_eff": "min(snr_w, snr_c)  ← 预注册主判据",
            "min_code": "min(码自身 top-10 命中 w,c)  ← 事后探索",
            "nq": NQ, "n_pairs": N_PAIRS, "local_top": LOCAL_TOP,
        },
        "spearman": {k: {s: v for s, v in d.items()} for k, d in verdict.items()},
        "rows": old,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  结果写入 {OUT_JSON.relative_to(ROOT)}（可再次用 --report 复现上表）")


if __name__ == "__main__":
    main()

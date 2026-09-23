"""P7-②：把 PQ/OPQ 管线、HNSW 家族与 QuIVer 放到**同召回**下比（并把结论画成第 5 张图）。

口径（避免"各取最好"的不可比）：
  * 对目标召回 `r`，报告"**能达到 ≥ r 召回的最快点**"的 QPS —— 不做内插假设，且对基线保守（我们不会替它挑好点）。
  * 若某方法在整条扫描里都达不到 `r`，记 `—` 并标出其最高召回。
  * **线程数必须一致**才可比：本脚本把线程数印在每条曲线上（`threads=`），跨线程的行不做结论。

数据来源：
  * PQ/OPQ：`.tmp/p7_pq_cohere.log`（仓库 `bench_baselines.py` 的输出，列 nprobe [k_factor] R@10 1T-QPS MT-QPS）
  * 图索引：`results/baseline/competitors_<prefix>.json`（hnswlib / FAISS-HNSW / USearch / IVF-Flat）
  * QuIVer：bench 日志（`.tmp/*.log` 里的 `ef_search=N R@10 X% Y QPS` 行）

用法：`.venv/Scripts/python.exe scripts/research/pq_matched_recall.py cohere --quiv .tmp/f1_off_cohere.log`
"""
import json
import math
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "paper" / "figures"
TARGETS = (99.0, 99.5, 99.8, 99.9)
COLORS = {"QuIVer": "#188038", "hnswlib": "#d93025", "FAISS-HNSW": "#f9ab00",
          "USearch": "#a142f4", "IVF-Flat": "#00897b", "PQ/OPQ+Refine": "#1a73e8"}

ROW = re.compile(r"^\s*(\d+)\s+(?:(\d+)\s+)?([\d.]+)%\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)")


def parse_pq(path: Path):
    """→ {配置名: [(recall, mt_qps), ...]}

    ⚠️ 日志里的分隔线本身也是 `---...---`，所以捕获组必须以**非短横**开头，
    否则会把分隔线当成配置名（会让整段数据丢失）。
    """
    txt = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n---\s*([^-][^\n]*?)\s*---\n", txt)
    out = {}
    for i in range(1, len(blocks), 2):
        name = blocks[i].strip()
        pts = []
        for line in blocks[i + 1].splitlines():
            m = ROW.match(line)
            if m:
                pts.append((float(m.group(3)), float(m.group(5).replace(",", ""))))
        if pts:
            out[name] = [(r, q) for r, q in pts]
    return out


def parse_quiv(paths):
    pts, ef = [], None
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"ef_search=(\d+)\s+R@10\s+([\d.]+)%\s+([\d,]+)\s+QPS", line)
            if m:
                pts.append((float(m.group(2)), float(m.group(3).replace(",", "")), int(m.group(1))))
    return sorted(pts, key=lambda x: x[2])


def parse_competitors(prefix):
    f = ROOT / "results" / "baseline" / f"competitors_{prefix}.json"
    out, threads = {}, None
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        threads = d.get("threads")
        nice = {"hnswlib": "hnswlib", "faiss_hnsw": "FAISS-HNSW", "usearch": "USearch",
                "faiss_ivf_flat": "IVF-Flat"}
        for arm in d["results"]:
            if arm["name"] in nice:
                pts = [(r["recall"], r["qps"]) for r in arm["rows"]
                       if r["recall"] is not None and r["qps"]]
                if pts:
                    out[nice[arm["name"]]] = sorted(pts)
    # P7-④：IVF+RaBitQ+Refine（论文 §5.3 的基线之一；本机 faiss 1.15 支持）
    g = ROOT / "results" / "t2" / f"rabitq_refine_{prefix}.json"
    if g.exists():
        d = json.loads(g.read_text(encoding="utf-8"))
        pts = [(r["recall"], r["qps"]) for r in d["results"][0]["rows"] if r.get("qps")]
        if pts:
            out["IVF+RaBitQ+Refine"] = sorted(pts)
            threads = threads or d.get("threads")
    return out, threads


def qps_at(pts, target):
    """≥ target 召回里最快的点的 QPS；达不到返回 None"""
    ok = [q for r, q in pts if r >= target]
    return max(ok) if ok else None


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "cohere"
    qv = [a for a in sys.argv if a.endswith(".log")]
    curves = {}
    pq = parse_pq(ROOT / ".tmp" / f"p7_pq_{prefix}.log")
    # 每个 (nlist,m_pq) 配置各自是一条曲线；总曲线上取"每召回处最快"
    merged = []
    for name, pts in pq.items():
        merged += pts
    if merged:
        curves["PQ/OPQ+Refine"] = merged
        print(f"  PQ 配置数 {len(pq)}：")
        for name, pts in pq.items():
            best = max(pts)
            print(f"    {name:<44} 最高 {best[0]:.2f}% @ {best[1]:,.0f} MT-QPS")
    comp, threads = parse_competitors(prefix)
    curves.update(comp)
    if qv:
        curves["QuIVer"] = [(r, q) for r, q, _ in parse_quiv(qv)]

    print(f"\n{'=' * 96}\n  {prefix}：同召回对照（≥r 召回里最快的点）\n{'=' * 96}")
    print(f"  {'方法':<18}{'最高召回':>10}  " + "".join(f"{f'≥{t}%':>14}" for t in TARGETS))
    for name, pts in curves.items():
        top = max(r for r, _ in pts)
        cells = []
        for t in TARGETS:
            q = qps_at(pts, t)
            cells.append(f"{q:,.0f}" if q else "—")
        print(f"  {name:<18}{top:>9.2f}%  " + "".join(f"{c:>14}" for c in cells))
    print(f"\n  （竞品 JSON 记录的线程数 = {threads}；PQ 脚本自报 32 线程；"
          f"QuIVer 线程数见其日志——跨线程的行不可直接比）")
    (ROOT / "results" / "t2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "t2" / f"pq_matched_recall_{prefix}.json").write_text(
        json.dumps({"prefix": prefix, "targets": TARGETS,
                    "curves": {k: v for k, v in curves.items()}}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"  [OK] results/t2/pq_matched_recall_{prefix}.json")


if __name__ == "__main__":
    main()

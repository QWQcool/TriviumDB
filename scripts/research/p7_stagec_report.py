"""P7 Stage C 报告：item 11（多种子置信区间）+ item 12（探针 K=5 的裁决稳定性）。

用法：`.venv/Scripts/python.exe scripts/research/p7_stagec_report.py`
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
ARMS = ("gist960c", "sift128c", "glove100c", "wolt_clipc", "coherec")
R64 = re.compile(r"ef_search=64\s+R@10\s+([\d.]+)%")
R1K = re.compile(r"ef_search=1024\s+R@10\s+([\d.]+)%")


def item11():
    print("\n=== item 11：5 集 × 3 次独立建图（多种子 CI）===")
    print(f"  {'臂':<14}{'s1@64':>9}{'s2@64':>9}{'s3@64':>9}{'@64 极差':>10}{'@1024 极差':>11}  判定")
    out = {}
    for arm in ARMS:
        r64, r1k = [], []
        for s in (1, 2, 3):
            f = ROOT / ".tmp" / f"p7q_{arm}_seed{s}.log"
            if not f.exists():
                continue
            t = f.read_text(encoding="utf-8", errors="replace")
            m, k = R64.search(t), R1K.search(t)
            if m:
                r64.append(float(m.group(1)))
            if k:
                r1k.append(float(k.group(1)))
        if len(r64) < 3:
            print(f"  {arm:<14} 数据不全（{len(r64)}/3）")
            continue
        sp64, sp1k = max(r64) - min(r64), max(r1k) - min(r1k)
        verdict = "稳定" if sp64 < 0.6 else "⚠️ 波动大"
        out[arm] = {"r64": r64, "r1024": r1k, "spread64": sp64, "spread1024": sp1k}
        print(f"  {arm:<14}{r64[0]:>8.2f}%{r64[1]:>8.2f}%{r64[2]:>8.2f}%"
              f"{sp64:>9.2f}pp{sp1k:>10.2f}pp  {verdict}")
    if out:
        worst = max(v["spread64"] for v in out.values())
        print(f"  ⇒ 最大 @ef=64 极差 **{worst:.2f}pp**（论文 §3.5 噪声下限声明用这个数）")
    return out


def item12():
    print("\n=== item 12：探针 K=5 与 K=3 的裁决稳定性 ===")
    rows = {r["prefix"]: r for r in json.loads(
        (ROOT / "results" / "t2" / "deployability_gate.json").read_text(encoding="utf-8"))}
    t = (ROOT / ".tmp" / "p7q_gate_k5.log").read_text(encoding="utf-8", errors="replace")
    pat = re.compile(r"^\s*(\S+)\s+dim=\d+\s+sign_info=([\d.]+)/[\d.]+\s.*?"
                     r"probe_ef=\s*([\d.]+)%\s*实测@128=(\S+)\s*导航=(\S+)", re.M)
    hits = pat.findall(t)
    print(f"  K=5 日志里解析到 {len(hits)} 个臂")
    checked = drift = 0
    nav_change = []
    for arm, si, k5, _meas, nav5 in hits:
        if arm not in rows:
            continue
        r = rows[arm]
        k3 = r.get("probe_topef_min")
        nav3 = r.get("nav_recommendation")
        checked += 1
        if k3 is not None and abs(float(k5) - k3) > 3.0:
            drift += 1
            print(f"  ⚠️ {arm:<16} probe_ef K=3 {k3:.1f}% → K=5 {float(k5):.1f}%（差 {float(k5) - k3:+.1f}pp）")
        if nav3 and nav5 and nav3 != nav5:
            nav_change.append((arm, nav3, nav5))
            print(f"  ⚠️ {arm:<16} 导航建议 K=3={nav3} → K=5={nav5}")
    print(f"  ⇒ 对拍 {checked} 个臂：probe_ef 漂移 >3pp 的 **{drift}** 个；"
          f"导航建议变化 **{len(nav_change)}** 个")
    return {"checked": checked, "drift": drift, "nav_change": nav_change}


if __name__ == "__main__":
    out = {"item11": item11(), "item12": item12()}
    (ROOT / "results" / "t2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "t2" / "p7_stagec_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n  [OK] results/t2/p7_stagec_report.json")

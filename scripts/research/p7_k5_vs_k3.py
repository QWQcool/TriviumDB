"""item 12 对拍：探针 **K=5**（Stage C 跑的）与 **K=3**（HEAD 里提交的那份）是否改变任何裁决。

背景：判据脚本把结果 **合并写回** `results/t2/deployability_gate.json`，
所以 K=5 那轮**覆盖**了 K=3 的数值 ⇒ 拿 HEAD 里的版本作为 K=3 的对照（这正好是干净的 A/B）。

用法：`.venv/Scripts/python.exe scripts/research/p7_k5_vs_k3.py`
"""
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
REL = "results/t2/deployability_gate.json"


def main():
    new = {r["prefix"]: r for r in json.loads((ROOT / REL).read_text(encoding="utf-8"))}
    raw = subprocess.check_output(["git", "show", f"HEAD:{REL}"], cwd=ROOT)
    old = {r["prefix"]: r for r in json.loads(raw.decode("utf-8"))}

    print(f"  当前 JSON probe_k = {sorted({r.get('probe_k') for r in new.values()})}")
    print(f"  HEAD   JSON probe_k = {sorted({r.get('probe_k') for r in old.values()})}")
    common = sorted(p for p in new if p in old and new[p].get("probe_topef_min") is not None)
    print(f"\n  对拍 {len(common)} 个臂（K=3 → K=5）\n")
    print(f"  {'arm':<16}{'K=3 probe_ef':>14}{'K=5 probe_ef':>14}{'drift':>10}{'sign_info':>18}  nav")
    big, navchg = [], []
    for p in common:
        a, b = old[p], new[p]
        d = b["probe_topef_min"] - a["probe_topef_min"]
        nc = a.get("nav_recommendation") != b.get("nav_recommendation")
        if abs(d) > 3.0:
            big.append((p, a["probe_topef_min"], b["probe_topef_min"], d))
        if nc:
            navchg.append((p, a.get("nav_recommendation"), b.get("nav_recommendation")))
        mark = "  <<<" if (abs(d) > 3.0 or nc) else ""
        print(f"  {p:<16}{a['probe_topef_min']:>13.1f}%{b['probe_topef_min']:>13.1f}%"
              f"{d:>+9.1f}pp{a['sign_info']:>10.3f}→{b['sign_info']:.3f}"
              f"  {a.get('nav_recommendation')}→{b.get('nav_recommendation')}{mark}")
    print(f"\n  ⇒ probe_ef 漂移 >3pp：**{len(big)}** 个"
          + ("（" + ", ".join(f"{p} {d:+.1f}pp" for p, _, _, d in big) + "）" if big else ""))
    print(f"  ⇒ 导航建议变化：**{len(navchg)}** 个"
          + ("（" + ", ".join(f"{p}: {x}→{y}" for p, x, y in navchg) + "）" if navchg else ""))
    print(f"  ⇒ 新增到 JSON 的臂：{sorted(set(new) - set(old))}")
    out = {"pairs": len(common), "drift_gt_3pp": big, "nav_changes": navchg,
           "new_arms": sorted(set(new) - set(old)),
           "current_probe_k": sorted({r.get("probe_k") for r in new.values()})}
    (ROOT / "results" / "t2" / "p7_k5_vs_k3.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  [OK] results/t2/p7_k5_vs_k3.json")


if __name__ == "__main__":
    main()

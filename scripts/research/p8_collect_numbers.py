"""预印本收尾取数：把要写进 §5/§7/§8/§9/§10 的 **P5/P6/P7** 数字**全部从产物读出来**。

准则（B3 教训）：正文里每个数字都必须来自产物，不允许凭印象。本脚本只读。

用法：`.venv/Scripts/python.exe scripts/research/p8_collect_numbers.py`
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
T2 = ROOT / "results" / "t2"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def jload(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception as e:                                               # noqa: BLE001
        print(f"  !! 读不了 {p}: {e}")
        return None


def log_lines(f, pat, limit=8):
    lines = [ANSI.sub("", x).strip()
             for x in Path(f).read_text(encoding="utf-8", errors="replace").splitlines()]
    return [x for x in lines if re.search(pat, x)][:limit]


def main():
    print("\n=========== A. PQ / 量化类对照（§5.3、§8.7）===========")
    for f in sorted(T2.glob("pq_*.json")):
        d = jload(f)
        if not d:
            continue
        print(f"\n -- {f.name}: prefix={d.get('prefix')} dim={d.get('dim')} "
              f"m={d.get('m')} nbits={d.get('nbits')} threads={d.get('threads')} "
              f"metric={d.get('metric')}")
        for arm in d.get("results", []):
            rows = arm.get("rows", [])
            print(f"    {str(arm.get('name')):<24} build={arm.get('build_s', 0):7.1f}s  "
                  + " ".join(f"{r.get('recall'):.2f}%@{r.get('qps', 0):,.0f}" for r in rows[:6]))
        for k, v in d.items():
            if isinstance(v, (int, float, str)) and k not in (
                    "prefix", "dim", "m", "nbits", "threads", "metric", "results", "notes", "doc"):
                print(f"    {k} = {str(v)[:160]}")

    print("\n=========== B. 位预算天花板（§6.4）===========")
    for f in sorted(T2.glob("bitbudget*.json")) + sorted(T2.glob("*bit_budget*.json")):
        d = jload(f)
        if d:
            print(f"\n -- {f.name}\n    " + json.dumps(d, ensure_ascii=False)[:1500])

    print("\n=========== C. RaBitQ / 控制臂（§5.3）===========")
    for f in sorted(T2.glob("rabitq_refine_*.json")) + sorted(T2.glob("ivfflat_control_*.json")):
        d = jload(f)
        if not d:
            continue
        print(f"\n -- {f.name}  control={d.get('control')}  build={d.get('build_s', 0):.1f}s"
              f"  threads={d.get('threads')}")
        for arm in d.get("results", []):
            for r in arm.get("rows", []):
                print(f"    nprobe={r['ef']:<5} k_fac={str(r.get('k_factor')):<5} "
                      f"{r['recall']:6.2f}%  1T={r.get('st_qps', 0):>8,.0f}  MT={r.get('qps', 0):>8,.0f}")

    print("\n=========== D. 旋转 / 引擎开关 / VIBE 日志===========")
    for label, pat in (("P4-A 旋转", "p4a_*.log"), ("P4-A 组合", "p4a_*rc*.log"),
                       ("P5 引擎开关", "p5_*.log"), ("P6 VIBE", "p6_*.log"),
                       ("P7 前瞻", "p7q_*seed1.log")):
        fs = sorted((ROOT / ".tmp").glob(pat))
        print(f"\n -- {label}: {len(fs)} 个文件")
        for f in fs[:8]:
            hits = log_lines(f, r"ef_search=64\s+R@10|ef_search=1024\s+R@10|建图\s+[\d.]+s")
            if hits:
                print(f"    {f.name}")
                for h in hits[:4]:
                    print("       " + h[:120])

    print("\n=========== E. Stage C：多种子 CI + K=5（§3.5、§7.3）===========")
    for name in ("p7_stagec_report.json", "p7_k5_vs_k3.json"):
        d = jload(T2 / name)
        if not d:
            print(f"  [{name}] 缺")
            continue
        print(f"\n -- {name}")
        if name.startswith("p7_stagec"):
            print("    item11 多种子极差：")
            for arm, v in (d.get("item11") or {}).items():
                print(f"      {arm:<14} @64 极差 {v['spread64']:.2f}pp  "
                      f"@1024 极差 {v['spread1024']:.2f}pp  {v['r64']}")
        else:
            print(f"    对拍 {d.get('pairs')} 臂：漂移>3pp {len(d.get('drift_gt_3pp') or [])} 个，"
                  f"导航真变化 {len(d.get('nav_changes') or [])} 个，"
                  f"probe_k={d.get('current_probe_k')}")

    print("\n=========== F. 判据链前瞻验证（§7.3）===========")
    for f in sorted(T2.glob("*prospective*.json")) + sorted(T2.glob("*nav_rule*.json")):
        d = jload(f)
        if d:
            print(f"\n -- {f.name}\n    " + json.dumps(d, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()

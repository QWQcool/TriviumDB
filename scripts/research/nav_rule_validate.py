"""P7-⑦：**导航度量规则的前瞻验证** —— `probe_ef(加权) > probe_ef(Hamming)` ⇒ 开加权导航。

为什么叫"前瞻"：这条规则是在 10 个**已知**臂（F1 的 A/B）上看出来的；
下面这些臂是**规则定下来之后**才跑的（VIBE 五行 + `gist960rc`），它们没参与拟合。
规则若在它们身上也成立，就不是"事后挑规则"。

数据来源：判据日志 `.tmp/p7q_gate_<arm>.log`（或 `results/t2/deployability_gate.json`）
          与两臂 bench 日志 `.tmp/p7q_<arm>_w{0,1}.log` / `.tmp/*_w{0,1}.log`。

用法：`.venv/Scripts/python.exe scripts/research/nav_rule_validate.py`
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]

# 前瞻臂：判据日志前缀 + 两臂日志文件名
PROSPECTIVE = [
    ("arxiv_nomic", ".tmp/p7q_gate_arxiv_nomic.log", ".tmp/p7q_arxiv_nomic_w0.log", ".tmp/p7q_arxiv_nomic_w1.log"),
    ("codesearch_jina", ".tmp/p7q_gate_codesearch_jina.log", ".tmp/p7q_codesearch_jina_w0.log", ".tmp/p7q_codesearch_jina_w1.log"),
    ("gooaq_roberta", ".tmp/p7q_gate_gooaq_roberta.log", ".tmp/p7q_gooaq_roberta_w0.log", ".tmp/p7q_gooaq_roberta_w1.log"),
    ("landmark_nomic", ".tmp/p7q_gate_landmark_nomic.log", ".tmp/p7q_landmark_nomic_w0.log", ".tmp/p7q_landmark_nomic_w1.log"),
    ("landmark_dino", ".tmp/p7q_gate_landmark_dino.log", ".tmp/p7q_landmark_dino_w0.log", ".tmp/p7q_landmark_dino_w1.log"),
    ("gist960rc", None, ".tmp/p7q_gist960rc_w0.log", ".tmp/p7q_gist960rc_w1.log"),
]
# 拟合集（F1 时代，规则就是在这些臂上看出来的）
FITTED = [
    ("glove100", 72.8, 44.8, "+21.8"), ("gauss960", 55.0, 4.7, "×2.9"),
    ("cohere", 99.1, 98.7, "+0.5"), ("wolt_clip", 87.0, 87.5, "+0.9"),
    ("gist960", 2.2, 20.9, "−1.3"), ("sift128", 10.4, 30.3, "−13.4"),
]

R64 = re.compile(r"ef_search=64\s+R@10\s+([\d.]+)%")


def recall64(path):
    p = ROOT / path
    if not p.exists():
        return None
    m = R64.search(p.read_text(encoding="utf-8", errors="replace"))
    return float(m.group(1)) if m else None


def gate_of(arm, log):
    """优先用判据日志；**日志不存在或正则不命中**时回退到 deployability_gate.json

    （日志常被 Tee/过滤截断 ⇒ 回退不是可选项而是常态路径。）
    """
    f = ROOT / log if log else None
    if f and f.exists():
        t = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\(w ([\d.]+)/c ([\d.]+)\)", t)
        if m:
            return float(m.group(1)), float(m.group(2))
    rows = {r["prefix"]: r for r in json.loads(
        (ROOT / "results" / "t2" / "deployability_gate.json").read_text(encoding="utf-8"))}
    if arm in rows:
        return rows[arm]["probe_topef_w"], rows[arm]["probe_topef_c"]
    return None


def main():
    print("\n=== 拟合集（F1 时代的 10 个臂，规则由此得出）===")
    fit_ok = fit_tot = 0
    for arm, pw, pc, delta in FITTED:
        pred = "加权" if pw > pc else "cheap"
        got = "加权" if delta.startswith(("+", "×")) else "cheap"
        ok = pred == got
        fit_ok += ok
        fit_tot += 1
        print(f"  {arm:<16} probe w={pw:5.1f}% c={pc:5.1f}% ⇒ 规则:{pred:<6} 实测 Δ={delta:>6} ⇒ {'✅' if ok else '❌'}")
    print(f"  拟合集命中 {fit_ok}/{fit_tot}")

    print("\n=== ★ 前瞻集（规则定下来之后才跑的臂，未参与拟合）===")
    rows, ok_n = [], 0
    for arm, glog, w0, w1 in PROSPECTIVE:
        g = gate_of(arm, glog)
        a, b = recall64(w0), recall64(w1)
        if not g or a is None or b is None:
            print(f"  {arm:<16} 数据不全（gate={bool(g)} w0={a} w1={b}）")
            continue
        pw, pc = g
        pred = "加权" if pw > pc else "cheap"
        d = b - a
        ok = (pred == "加权") == (d > 0)
        ok_n += ok
        rows.append({"arm": arm, "probe_w": pw, "probe_c": pc, "pred": pred,
                     "w0": a, "w1": b, "delta": d, "ok": bool(ok)})
        print(f"  {arm:<16} probe w={pw:5.1f}% c={pc:5.1f}% ⇒ 规则:{pred:<6} "
              f"实测 w0={a:6.2f}% → w1={b:6.2f}%（Δ={d:+6.2f}）⇒ {'✅' if ok else '❌'}")
    print(f"  前瞻集命中 {ok_n}/{len(rows)}")

    out = {"fitted": {"hit": fit_ok, "total": fit_tot}, "prospective": rows,
           "prospective_hit": ok_n}
    (ROOT / "results" / "t2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "t2" / "nav_rule_validation.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  [OK] results/t2/nav_rule_validation.json")


if __name__ == "__main__":
    main()

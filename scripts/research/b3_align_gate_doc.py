"""B3：把 t2-deployability-gate.md 里"单次 200 查询"时代的探针值对齐到 K=3 均值（产物 JSON）。

原则：只改能被 `results/t2/deployability_gate.json` 逐字段核对的值；每处替换都断言命中。
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
doc = ROOT / "docs" / "research" / "t2-deployability-gate.md"
rows = {r["prefix"]: r for r in json.loads(
    (ROOT / "results" / "t2" / "deployability_gate.json").read_text(encoding="utf-8"))}

sph, gc = rows["sphere"], rows["gist960c"]
g0 = rows["gist960"]
print(f"JSON 真值：sphere  top10_w={sph['probe_top10_w']:.1f} c={sph['probe_top10_c']:.1f} "
      f"| topef_w={sph['probe_topef_w']:.1f} c={sph['probe_topef_c']:.1f} min={sph['probe_topef_min']:.1f} K={sph['probe_k']}")
print(f"            gist960 w={g0['probe_topef_w']:.1f} c={g0['probe_topef_c']:.1f} | "
      f"gist960c w={gc['probe_topef_w']:.1f} c={gc['probe_topef_c']:.1f} | "
      f"glove100c min={rows['glove100c']['probe_topef_min']:.1f}")

PAIRS = [
    # §3-② 假阳性表
    ("| top-10 | 16.2% | 0.6% | 0.6% |",
     f"| top-10 | {sph['probe_top10_w']:.1f}% | {sph['probe_top10_c']:.1f}% | {min(sph['probe_top10_w'], sph['probe_top10_c']):.1f}% |"),
    ("| **top-128 → 精排** | **53.9%** ✅ 过 50% 阈值 | **4.7%** ❌ | **4.7%** ❌ |",
     f"| **top-128 → 精排** | **{sph['probe_topef_w']:.1f}%** ✅ 过 50% 阈值 "
     f"| **{sph['probe_topef_c']:.1f}%** ❌ | **{sph['probe_topef_min']:.1f}%** ❌ |"),
    ("**取双度量最弱（`min`）恰好修掉这个假阳性**（4.7%）",
     f"**取双度量最弱（`min`）恰好修掉这个假阳性**（{sph['probe_topef_min']:.1f}%）"),
    # §3-③ 探针闭合
    ("`gist960`（加权 top-ef）**2.3% → 去均值后 78.0%**（Hamming 22.1% → 70.7%）",
     f"`gist960`（加权 top-ef）**{g0['probe_topef_w']:.1f}% → 去均值后 {gc['probe_topef_w']:.1f}%**"
     f"（Hamming {g0['probe_topef_c']:.1f}% → {gc['probe_topef_c']:.1f}%）"),
    # §1.2 与 §4 的 top-10 偏悲观举例
    ("判为 26.7%", f"判为 {gc['probe_top10_min']:.1f}%"),
    # §2 表 gist960c 行
    ("| gist960c | 960 | 0.981/0.962 | 0.024 | +0.347 | 26.7% | 70.7% | 51.96% | ④ 可用 | ✅ |",
     f"| gist960c | 960 | 0.981/0.962 | 0.024 | +0.347 | {gc['probe_top10_min']:.1f}% "
     f"| {gc['probe_topef_min']:.1f}% | 51.96% | ④ 可用 | ✅ |"),
    # 边界案例
    ("`probe_ef` 45.6%", f"`probe_ef` {rows['glove100c']['probe_topef_min']:.1f}%"),
]

text = doc.read_text(encoding="utf-8")
miss = []
for old, new in PAIRS:
    n = text.count(old)
    if n == 0:
        miss.append(old[:70])
    else:
        text = text.replace(old, new)
        print(f"  OK 替换 {n} 处：{old[:52]} -> {new[:52]}")
doc.write_text(text, encoding="utf-8")
print("未命中（需人工看）：", miss if miss else "无")

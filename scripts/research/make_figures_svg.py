"""P4-D：论文图（零依赖，直接写 SVG —— 本 venv 无 matplotlib，且 SVG 是矢量更适合论文）。

产出 docs/paper/figures/：
  fig1-repair-bars.svg       三个"修复前/后"对比（原始 / 去均值 / 旋转）@ef_s=64
  fig2-gist960-curves.svg    GIST-960：QuIVer（旋转）与竞品的 召回-QPS 曲线（标出"竞品无工作点"的召回带）
  fig3-signinfo-gain.svg     `sign_info` vs 修复增益（去均值臂 + 旋转臂；含无操作对照）

用法：`.venv/Scripts/python.exe scripts/research/make_figures_svg.py`
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

FONT = "font-family='DejaVu Sans,Segoe UI,sans-serif'"
C = {"orig": "#9aa0a6", "centre": "#1a73e8", "rotate": "#188038",
     "hnsw": "#d93025", "faiss": "#f9ab00", "ivf": "#a142f4", "quiver": "#188038"}


def head(w, h, title):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
            f"<rect width='{w}' height='{h}' fill='white'/>"
            f"<text x='{w / 2}' y='26' text-anchor='middle' {FONT} font-size='16' "
            f"font-weight='600' fill='#202124'>{title}</text>")


def txt(x, y, s, size=11, anchor="start", color="#3c4043", weight="400", rotate=None):
    r = f" transform='rotate({rotate} {x} {y})'" if rotate else ""
    return (f"<text x='{x}' y='{y}' text-anchor='{anchor}' {FONT} font-size='{size}' "
            f"fill='{color}' font-weight='{weight}'{r}>{s}</text>")


def line(x1, y1, x2, y2, color="#dadce0", w=1, dash=None):
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' stroke-width='{w}'{d}/>"


def rect(x, y, w, h, fill, op=1.0):
    return f"<rect x='{x}' y='{y}' width='{max(w, 0)}' height='{max(h, 0)}' fill='{fill}' opacity='{op}'/>"


def circle(cx, cy, r, fill, stroke="white", sw=1.5):
    return f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='{fill}' stroke='{stroke}' stroke-width='{sw}'/>"


def poly(pts, color, w=2.2):
    p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return f"<polyline points='{p}' fill='none' stroke='{color}' stroke-width='{w}'/>"


# ── 图 1：修复对比柱状 ────────────────────────────────────────────────
def fig1():
    W, H = 760, 380
    L, R, T, B = 78, 24, 74, 74
    plot_h = H - T - B
    data = [  # (标签, 原始, 去均值, 旋转, 备注)
        ("GIST-960", 2.10, 39.74, 60.22, ""),
        ("SIFT-128", 15.77, 30.64, 60.24, ""),
        ("GloVe-100", 32.82, 36.11, 32.26, "旋转+加权导航 54.06"),
        ("Cohere-768", 94.63, 93.48, 89.82, "旋转有害 −4.8pp"),
    ]
    s = [head(W, H, "Repair comparison @ef_s=64 (cheap navigation)")]
    x0, gw, bw = L + 22, (W - L - R - 40) / len(data), 26
    for gy in range(0, 101, 20):
        y = T + plot_h * (1 - gy / 100)
        s.append(line(L, y, W - R, y))
        s.append(txt(L - 8, y + 4, f"{gy}%", 10, "end"))
    s.append(line(L, T, L, T + plot_h))
    for i, (name, o, c, r, note) in enumerate(data):
        bx = x0 + i * gw
        for j, (v, key) in enumerate(((o, "orig"), (c, "centre"), (r, "rotate"))):
            h = plot_h * v / 100
            s.append(rect(bx + j * (bw + 4), T + plot_h - h, bw, h, C[key]))
            s.append(txt(bx + j * (bw + 4) + bw / 2, T + plot_h - h - 5, f"{v:.1f}", 9, "middle"))
        s.append(txt(bx + 1.5 * bw, T + plot_h + 18, name, 11, "middle", weight="600"))
        if note:
            s.append(txt(bx + 1.5 * bw, T + plot_h + 33, note, 9, "middle", "#188038"))
    for j, (key, lbl) in enumerate((("orig", "original"), ("centre", "centred"),
                                    ("rotate", "rotated (seeded)"))):
        x = L + 10 + j * 130
        y = H - 16
        s.append(rect(x, y - 9, 12, 12, C[key]))
        s.append(txt(x + 18, y + 1, lbl, 10))
    s.append("</svg>")
    (OUT / "fig1-repair-bars.svg").write_text("".join(s), encoding="utf-8")


# ── 图 2：GIST-960 召回-QPS 曲线 ─────────────────────────────────────
def fig2():
    W, H = 780, 430
    L, R, T, B = 66, 210, 76, 62
    pw, ph = W - L - R, H - T - B
    q = [(42261, 60.22), (25057, 70.95), (13836, 78.88), (7148, 84.41), (3609, 88.99)]
    comp = json.loads((ROOT / "results" / "baseline" / "competitors_gist960.json")
                      .read_text(encoding="utf-8"))
    series = [("quiver", "QuIVer (rotated, §8.6)", q)]
    for arm in comp["results"]:
        if arm["name"] in ("hnswlib", "faiss_hnsw", "faiss_ivf_flat", "usearch"):
            key = {"hnswlib": "hnsw", "faiss_hnsw": "faiss",
                   "faiss_ivf_flat": "ivf", "usearch": "faiss"}[arm["name"]]
            series.append((key, arm["name"], [(r["qps"], r["recall"]) for r in arm["rows"]]))
    xs = [p[0] for _, _, pts in series for p in pts]
    ys = [p[1] for _, _, pts in series for p in pts]
    x_lo, x_hi = 300, 60000
    y_lo, y_hi = 55, 101
    import math
    def sx(v):
        return L + pw * (math.log10(v) - math.log10(x_lo)) / (math.log10(x_hi) - math.log10(x_lo))
    def sy(v):
        return T + ph * (1 - (v - y_lo) / (y_hi - y_lo))
    s = [head(W, H, "GIST-960: recall vs throughput (M=32, ef_c=128)")]
    for gy in range(60, 101, 10):
        s.append(line(L, sy(gy), L + pw, sy(gy)))
        s.append(txt(L - 8, sy(gy) + 4, f"{gy}%", 10, "end"))
    for gx in (300, 1000, 3000, 10000, 30000):
        s.append(line(sx(gx), T, sx(gx), T + ph))
        s.append(txt(sx(gx), T + ph + 16, f"{gx // 1000}k" if gx >= 1000 else str(gx), 10, "middle"))
    s.append(line(L, T, L, T + ph))
    s.append(txt(L + pw / 2, H - 12, "MT-QPS (log)", 11, "middle", weight="600"))
    s.append(txt(16, T + ph / 2, "Recall@10", 11, "middle", weight="600", rotate=-90))
    # "no competitor operating point" band: 60.22 .. 84.11
    s.append(rect(L, sy(84.11), pw, sy(60.22) - sy(84.11), "#188038", 0.07))
    s.append(txt(L + 8, sy(72) + 4, "no HNSW operating point in this band", 10, "#188038"))
    for key, lbl, pts in series:
        pts = sorted(pts)
        s.append(poly([(sx(a), sy(b)) for a, b in pts], C[key], 2.4 if key == "quiver" else 1.6))
        for a, b in pts:
            s.append(circle(sx(a), sy(b), 3.4, C[key]))
    for j, (key, lbl, _) in enumerate(series):
        y = T + 8 + j * 20
        s.append(line(L + pw + 16, y, L + pw + 38, y, C[key], 3))
        s.append(txt(L + pw + 44, y + 4, lbl, 10))
    s.append(txt(L + pw + 16, T + 8 + len(series) * 20 + 12,
                 "rotated QuIVer is 1.32× faster than", 9, color="#5f6368"))
    s.append(txt(L + pw + 16, T + 8 + len(series) * 20 + 26,
                 "hnswlib at 84.4% recall", 9, color="#5f6368"))
    s.append("</svg>")
    (OUT / "fig2-gist960-curves.svg").write_text("".join(s), encoding="utf-8")


# ── 图 3：sign_info vs 修复增益 ──────────────────────────────────────
def fig3():
    W, H = 760, 420
    L, R, T, B = 72, 40, 70, 66
    pw, ph = W - L - R, H - T - B
    pts = [  # (sign_info, Δ@ef=64, 标签, 臂型)
        (0.000, 37.6, "GIST-960", "centre"), (0.000, 58.1, "GIST-960", "rotate"),
        (0.000, 14.9, "SIFT-128", "centre"), (0.000, 44.5, "SIFT-128", "rotate"),
        (0.204, 0.3, "Synth-LR", "centre"),
        (0.354, 3.3, "GloVe-100", "centre"), (0.946, -0.6, "GloVe-100", "rotate"),
        (0.797, 5.3, "Wolt-CLIP", "centre"),
        (0.834, -1.2, "Cohere-768", "centre"), (0.747, -4.8, "Cohere-768", "rotate"),
        (0.001, 0.03, "Random-Sphere", "centre"),
    ]
    x_lo, x_hi, y_lo, y_hi = -0.03, 1.03, -10, 62
    sx = lambda v: L + pw * (v - x_lo) / (x_hi - x_lo)
    sy = lambda v: T + ph * (1 - (v - y_lo) / (y_hi - y_lo))
    s = [head(W, H, "Sign-plane information vs repair gain (ΔR@10 @ef_s=64)")]
    for gy in range(-10, 61, 10):
        s.append(line(L, sy(gy), L + pw, sy(gy)))
        s.append(txt(L - 8, sy(gy) + 4, f"{gy:+d}", 10, "end"))
    s.append(line(L, sy(0), L + pw, sy(0), "#9aa0a6", 1.2))
    for gx in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        s.append(line(sx(gx), T, sx(gx), T + ph))
        s.append(txt(sx(gx), T + ph + 16, f"{gx:.1f}", 10, "middle"))
    s.append(txt(L + pw / 2, H - 14, "sign_info  (mean per-coordinate sign entropy, bits)", 11,
                 "middle", weight="600"))
    s.append(txt(16, T + ph / 2, "Δ recall (pp)", 11, "middle", weight="600", rotate=-90))
    seen = set()
    for x, y, lbl, kind in pts:
        s.append(circle(sx(x), sy(y), 5, C[kind]))
        if (lbl, kind) not in seen:
            s.append(txt(sx(x) + 9, sy(y) + 4, f"{lbl} ({'rot' if kind == 'rotate' else 'cen'})", 9))
            seen.add((lbl, kind))
    s.append(txt(L + pw + 6, T - 8, "dead sign plane ⇒ rotate", 10, "#188038", weight="600"))
    s.append(txt(L + pw * 0.62, T - 8, "alive ⇒ do not rotate", 10, "#d93025", weight="600"))
    for j, (key, lbl) in enumerate((("centre", "centring"), ("rotate", "seeded rotation"))):
        x, y = L + 10 + j * 150, H - 32
        s.append(circle(x, y - 4, 5, C[key]))
        s.append(txt(x + 12, y, lbl, 10))
    s.append("</svg>")
    (OUT / "fig3-signinfo-gain.svg").write_text("".join(s), encoding="utf-8")


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    for p in sorted(OUT.glob("*.svg")):
        print(f"  {p.name}  {p.stat().st_size / 1024:.1f} KB")

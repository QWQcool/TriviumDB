"""把 `docs/paper/section-*.md` 草稿打包成投稿件（单文件 Markdown → LaTeX → PDF）。

四件事：
  1. 六张 SVG 图 → PDF（PyMuPDF；XeTeX 不认 SVG），写入 `submission/figures/`；
  2. 按 §0…§12 顺序拼装单文件 Markdown：去掉内部 `> **Draft**` 行、去掉 §12.5（构建说明本身）、
     去掉 §0 的"Section index"表（那是仓库用的目录），图路径 `.svg` → `.pdf`；
     标题与摘要进 Pandoc 元数据（摘要渲染成 `\begin{abstract}`），摘要去 Markdown 记号；
  3. 生成 arXiv 元数据用的短摘要（脚本内校验 ≤ 1920 字符）；
  4. Pandoc 出 `.tex`，Tectonic 出 `.pdf`；复核文件另写给 `submission/README.md`。

工具位置：环境变量 `PANDOC` / `TECTONIC`；否则用 `%LOCALAPPDATA%\\TriviumPaperTools` 下的默认路径。

用法：`.venv/Scripts/python.exe scripts/paper/build_submission.py`
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs" / "paper"
SUB = PAPER / "submission"
SUBFIGS = SUB / "figures"
STEM = "quiver-independent-eval"

TOOLS = Path(os.environ.get("LOCALAPPDATA", "")) / "TriviumPaperTools"


def _tool(env_key: str, glob: str, fallback: str) -> str:
    if os.environ.get(env_key):
        return os.environ[env_key]
    hits = sorted(TOOLS.glob(glob))
    return str(hits[-1]) if hits else fallback


PANDOC = _tool("PANDOC", "pandoc-*/pandoc.exe", "pandoc")
TECTONIC = _tool("TECTONIC", "tectonic.exe", "tectonic")

TITLE = ("Applicability Is Not Competitiveness: An Independent Evaluation and a Data-Side Repair "
         "for BQ-Native Graph Indexing")
AUTHOR_PLACEHOLDER = "AUTHOR NAMES, AFFILIATION, E-MAIL  [TO BE FILLED IN BY THE AUTHORS]"
DATE = "October 9, 2026"

SHORT_ABSTRACT = (
    "Binary-quantized (BQ) graph indexes navigate on 2-bit codes instead of full-precision vectors; the "
    "published answer to \"when is that usable?\" is a 12-dataset table (0.40-95.65% Recall@10) plus one "
    "index-free probe. Re-running it on the authors' released implementation (11 of 12 rows within +-1.84 pp; "
    "one row protocol-ambiguous), we report five findings. (i) The tiers describe applicability but are read "
    "as competitiveness: where competitor curves exist, three of four tiers are dominated by plain HNSW, "
    "sometimes with no curve intersection at all. (ii) The bottom tier mixes three failures - a repairable "
    "encoding failure (constant sign plane, sign_info = 0.000), an index-agnostic task failure on which every "
    "competitor also collapses (Gaussian-960: 1.10-1.39% at ef=64), and a capacity failure (coco_nomic) where "
    "the bit budget binds: every collapse row reaches >= 94.6% at 4 bits per dimension. (iii) The probe is "
    "under-specified (metric, sample size, instrument); with the paper's own default metric it calls "
    "Random-Sphere \"compatible\" (53.9%) on a dataset whose measured recall is 0.91%, while the weaker of the "
    "engine's two metrics removes the false positive without changing any other verdict. (iv) The collapse is "
    "repairable without touching the index: x' = normalize(x - mu) takes GIST-960 from 2.10% to 39.74% and "
    "SIFT-128 from 15.77% to 30.64% at ef=64 (isotropic control +0.03 pp), a task-preserving seeded rotation "
    "reaches 60.2% where the sign plane is dead, and a navigation-metric switch adds up to +21.8 pp where it "
    "is alive and hurts where it is dead. (v) A PQ/OPQ pipeline with the same exact re-ranking never collapses "
    "on any of the six cells measured (98.99% / 98.42% on the two hardest) at about 4.7x QuIVer's memory, so "
    "the published boundary is the 2-bit code's, not quantization's."
)

HEADER_TEX = r"""
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{etoolbox}
\usepackage{graphicx}
\usepackage{float}
\AtBeginEnvironment{longtable}{\footnotesize}
\setlength{\tabcolsep}{4pt}
\renewcommand{\arraystretch}{1.05}
\setlength{\emergencystretch}{2em}
% 图注编号由正文手写（"**Figure N.**"），这里关掉 LaTeX 的自动编号与分隔符，避免双编号
\captionsetup[figure]{labelformat=empty,labelsep=none}
"""

# Latin Modern 在 XeTeX 下缺部分数学字形（≈ ≤ ≥ 等，尤其是等宽字号里），统一映射为 LaTeX 数学
GLYPH_MAP = {
    "\u2264": r"$\leq$", "\u2265": r"$\geq$", "\u2248": r"$\approx$",
    "\u00d7": r"$\times$", "\u2212": r"$-$", "\u2192": r"$\rightarrow$",
    "\u21d2": r"$\Rightarrow$", "\u03bc": r"$\mu$", "\u03b1": r"$\alpha$",
    "\u03c1": r"$\rho$", "\u03c3": r"$\sigma$", "\u0394": r"$\Delta$",
    "\u2016": r"$\|$", "\u2208": r"$\in$", "\u2229": r"$\cap$",
    "\u2260": r"$\neq$", "\u00b1": r"$\pm$", "\u221a": r"$\surd$",
    "\u2261": r"$\equiv$", "\u226a": r"$\ll$", "\uff5c": r"$|$",
    "\u2460": "(1)", "\u2461": "(2)", "\u2462": "(3)", "\u2463": "(4)",
}

# 代码块与标题行内的非 ASCII 一律降级为 ASCII：
#   * 等宽字体（lmmono）缺 ⇒ Σ τ ₂ ①②③④ 等字形，XeTeX 只会留空；
#   * 标题还会进 PDF 书签（\texorpdfstring 第二参数），那里不允许数学模式。
ASCII_MAP = {
    "\u2212": "-", "\u21d2": "=>", "\u00b7": "*", "\u2208": "in", "\u2082": "_2",
    "\u2016": "||", "\u03c4": "tau", "\u03a3": "sum", "\u2460": "(1)", "\u2461": "(2)",
    "\u2462": "(3)", "\u2463": "(4)", "\u2265": ">=", "\u2264": "<=", "\u2192": "->",
    "\u03bc": "mu", "\u2248": "~=", "\u00d7": "x", "\u2261": "==", "\u00a7": "Sec. ",
    "\u2229": "cap", "\u0394": "Delta", "\u03b1": "alpha", "\u03c3": "sigma",
    "\u03c1": "rho", "\u00b1": "+/-", "\u2260": "!=", "\u226a": "<<", "\uff5c": "|",
}


def asciify_context(text: str) -> str:
    """代码块、标题行内的非 ASCII 统一降级为 ASCII（见 ASCII_MAP 的说明）。"""
    out, in_code = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code or re.match(r"^#{1,4} ", line):
            line = "".join(ASCII_MAP.get(ch, ch) for ch in line)
        out.append(line)
    return "\n".join(out)


def demarkdown(s: str) -> str:
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    return s


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def convert_figures() -> list:
    import pymupdf
    SUBFIGS.mkdir(parents=True, exist_ok=True)
    made = []
    for svg in sorted((PAPER / "figures").glob("fig*.svg")):
        doc = pymupdf.open(svg)
        pdf = SUBFIGS / (svg.stem + ".pdf")
        pdf.write_bytes(doc.convert_to_pdf())
        made.append(pdf)
        print(f"  fig: {svg.name} -> figures/{pdf.name} ({pdf.stat().st_size / 1024:.1f} KB)")
    return made


def split_abstract(s0: str):
    m = re.search(r"\*\*Abstract\.\*\*(.*?)\n\n---", s0, re.S)
    abstract = " ".join(m.group(1).split())
    e = re.search(r"\*\*Evidence base\.\*\*(.*)", s0, re.S)
    evidence = "**Evidence base.**" + e.group(1)
    return abstract, evidence


def body_markdown() -> str:
    s0 = read(PAPER / "section-0-abstract.md")
    abstract, evidence = split_abstract(s0)
    names = {1: "intro", 2: "background", 3: "methodology", 4: "reproduction", 5: "boundary",
             6: "diagnosis", 7: "judge", 8: "repair", 9: "discussion", 10: "limitations",
             11: "artifacts", 12: "references"}
    parts = [evidence.strip()]
    for i in range(1, 13):
        f = PAPER / f"section-{i}-{names[i]}.md"
        txt = read(f)
        # 内部构建说明不进投稿件
        if f.name.startswith("section-12"):
            txt = re.split(r"\n## 12\.5 ", txt)[0].rstrip() + "\n"
        # 去掉内部 Draft 行
        txt = "\n".join(l for l in txt.splitlines() if not l.startswith("> **Draft**"))
        parts.append(txt.strip())
    body = "\n\n".join(parts)
    body = re.sub(r"\]\(figures/(fig\d-[a-z0-9-]+)\.svg\)", r"](figures/\1.pdf)", body)
    body = asciify_context(body)
    return body, abstract


def main():
    SUB.mkdir(parents=True, exist_ok=True)
    print("1) 图 → PDF")
    convert_figures()
    print("2) 拼装 Markdown")
    body, abstract = body_markdown()
    md = (f"---\ntitle: \"{TITLE}\"\nauthor: \"{AUTHOR_PLACEHOLDER}\"\ndate: \"{DATE}\"\n"
          f"abstract: |\n  " + demarkdown(abstract).replace("\n", " ") + "\n---\n\n" + body + "\n")
    (SUB / "paper.md").write_text(md, encoding="utf-8")
    print(f"  submission/paper.md  ({len(md)} 字符)")
    print("3) 短摘要")
    n = len(SHORT_ABSTRACT)
    assert n <= 1920, f"短摘要 {n} 字符 > arXiv 上限 1920"
    (SUB / "abstract-short.txt").write_text(SHORT_ABSTRACT + "\n", encoding="utf-8")
    print(f"  submission/abstract-short.txt  ({n} 字符, 上限 1920)")
    print("4) Pandoc → LaTeX")
    (SUB / "_header.tex").write_text(HEADER_TEX, encoding="utf-8")
    cmd = [PANDOC, str(SUB / "paper.md"), "-o", str(SUB / f"{STEM}.tex"), "--standalone",
           # 注意：不传 --number-sections —— 章节标题自带编号（"## 5.6 …"），文本里的 §N.M 引用与之一致
           "--toc", "--from", "markdown+pipe_tables+implicit_figures",
           "--to", "latex", "--variable", "tables=true", "--variable", "geometry:margin=2.2cm",
           "--variable", "fontsize=10pt", "--variable", "colorlinks=true",
           "--include-in-header", str(SUB / "_header.tex")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("  pandoc exit =", r.returncode)
    if r.stderr.strip():
        print("  stderr:", r.stderr.strip()[:800])
    if r.returncode != 0:
        return 1
    tex_path = SUB / f"{STEM}.tex"
    tex = tex_path.read_text(encoding="utf-8")
    n_glyph = 0
    for ch, rep in GLYPH_MAP.items():
        c = tex.count(ch)
        if c:
            tex = tex.replace(ch, rep)
            n_glyph += c
    tex_path.write_text(tex, encoding="utf-8")
    print(f"  字形映射：{n_glyph} 处 Unicode 数学 → LaTeX 数学命令")
    print("5) Tectonic → PDF")
    r = subprocess.run([TECTONIC, "-X", "compile", str(SUB / f"{STEM}.tex"), "--outdir", str(SUB)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-4:]
    print("  tectonic exit =", r.returncode)
    for l in tail:
        print("   ", l[:160])
    if r.returncode != 0:
        print("  stderr:", (r.stderr or "")[-1500:])
        return 1
    missing = [l for l in (r.stdout or "").splitlines() if "Missing character" in l]
    if missing:
        print(f"  ⚠️ 仍有 {len(missing)} 处缺字形（应在 ASCII_MAP/GLYPH_MAP 里补上）：")
        for l in sorted(set(missing))[:6]:
            print("     ", l[:150])
    else:
        print("  字形检查：无缺字形警告")
    produced = SUB / f"{STEM}.pdf"
    if produced.exists():
        print(f"  OK  {produced.relative_to(ROOT)}  ({produced.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

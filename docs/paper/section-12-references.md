# 12. References, Artifact Statement, and How to Assemble This Draft

> Every entry below was checked against its published version on 2026-10-09 (arXiv ids, venues and author
> lists verified against the arXiv abstract pages). We list what we actually used, with the version we used.

## 12.1 The object of study

1. **QuIVer: Rethinking ANN Graph Topology via Training-Free Binary Quantization.** W. Xiao, P. Zhu, Z. Wang,
   C. Li. arXiv:2605.02171 (2026), cs.DB. — the paper re-examined throughout §§4–7; C. Li is a co-author and
   the provenance disclosure of §1.1 applies.
2. **README_QUIVER.md** (shipped with the implementation). — dataset preparation, benchmark drivers, and the
   step-by-step reproduction guide this work follows. §4.2's "one protocol deviation" is a deviation from
   *this* document, not from the paper text.
3. Repository README (`README.md` / `README_EN.md`) — the published claims about hot/cold memory separation,
   the dimension guidance (≤ 3072), and the TSNG research track. §5 and §11.3a check the memory claim;
   §10.3/L11 records that the TSNG path was not A/B-tested under our navigation switch.

## 12.2 Baseline implementations we measured against

| # | Baseline | Reference / source |
|---|---|---|
| 4 | HNSW (algorithm) | Yu. A. Malkov, D. A. Yashunin. *Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs.* IEEE TPAMI 42(4), 2020. arXiv:1603.09320 |
| 5 | hnswlib (implementation) | https://github.com/nmslib/hnswlib |
| 6 | FAISS (library) | J. Johnson, M. Douze, H. Jégou. *Billion-scale similarity search with GPUs.* IEEE Trans. Big Data, 2019. arXiv:1702.08734; and M. Douze, A. Guzhva, C. Deng, J. Johnson, G. Szilvasy, P.-E. Mazaré, M. Lomeli, L. Hosseini, H. Jégou. *The Faiss library.* arXiv:2401.08281 (2025) |
| 7 | USearch (implementation) | https://github.com/unum-cloud/usearch |
| 8 | Inverted-file index (IVF / IVF-Flat) | J. Sivic, A. Zisserman. *Video Google: a text retrieval approach to object matching in videos.* ICCV 2003 |
| 9 | Product quantization (PQ) | H. Jégou, M. Douze, C. Schmid. *Product quantization for nearest neighbor search.* IEEE TPAMI 33(1), 2011 |
| 10 | Optimized PQ (OPQ) | T. Ge, K. He, Q. Ke, J. Sun. *Optimized product quantization for approximate nearest neighbor search.* CVPR 2013 |
| 11 | RaBitQ | J. Gao, C. Long. *RaBitQ: Quantizing high-dimensional vectors with a theoretical error bound for approximate nearest neighbor search.* SIGMOD 2024 (DOI 10.1145/3654970). arXiv:2405.12497 |
| 12 | DiskANN / Vamana graph | S. Subramanya, et al. *DiskANN: Fast accurate billion-point nearest neighbor search on a single node.* NeurIPS 2019 |
| 13 | FAISS `IndexIVFRaBitQ` / `IndexRefineFlat` / `IndexPreTransform` | FAISS 1.15 API (the same-family RaBitQ arm of §5.6(b), and the PQ arm of §5.6(a)) |

*Not measured, and why:* the paper's DiskANN-**Rust** and VSAG arms (§10.3/L13) — a C/C++/BLAS toolchain is
absent on the evaluation machine and the `pyvsag` wheel available there is a Linux/build-mismatched artifact.

## 12.3 Background and method references

14. J. Mu, P. Viswanath. *All-but-the-Top: Simple and effective postprocessing for word representations.*
    ICLR 2018. arXiv:1702.01417 — the centring step of §8.1 is this post-processing, applied to the query and
    base vectors before quantization.
15. **VIBE: Vector Index Benchmark for Embeddings.** E. Jääsaari, V. Hyvönen, M. Ceccarello, T. Roos,
    M. Aumüller. arXiv:2505.17810 (2025); J. Data-centric ML Research (2026) —
    https://github.com/vector-index-bench/vector-index-bench. The seven external benchmarks of §9.5.
16. Embedding models whose released vectors we use (Cohere-768, OpenAI-1536/3072, Nomic-768, Jina-768,
    DINOv2, MiniLM, BGE-M3, GloVe-100, Wolt-CLIP-512): cited via the dataset preparation scripts of (2) and
    (15), which name the model and revision for each row. We make no claim about the models themselves.

## 12.4 Artifact statement (what is ours, what is upstream, and the licence)

The upstream project is licensed **Apache-2.0** (`LICENSE`). This fork keeps that licence, and every change
we made is confined to the following, so a reader can separate our work from upstream's line by line.
**Provenance and disclosure:** one of us (C.L.) co-authored the evaluated system and its published benchmark;
this report is a **self-critical re-examination**, and §1.1 states what we did to keep it honest — including
shipping every artifact and raw log it cites:

| Directory / file | Ours? | Content |
|---|---|---|
| `Cargo.toml`, `src/**` (except two switches) | upstream | the QuIVer implementation we evaluate |
| `src/index/bq.rs` | **ours, +2 switches** | `TRIVIUM_NAV_WEIGHTED` (§8.3) and `TRIVIUM_SIGN_ROTATE` (§8.6): both **default off and bit-identical when unset**, shipped as reviewable patches in `patches/`, plus 2 new unit tests |
| `benches/bench_t2_b2_partitioned.rs` | upstream | the index-side harness we drive via `T2_*` environment variables (no source change needed) |
| `benches/bench_baselines.py` | upstream, **+env overrides** | grids/thread counts made overridable so the quantizer arm can be run at 32 threads (§10.4) |
| `scripts/research/**` | **ours** | index-free gate, competitor maps, rotation/centring preparation, PQ & RaBitQ arms, bit-budget probe, memory footprint, multi-seed spread, all report scripts |
| `docs/paper/**` | **ours** | this draft (§0–§12) |
| `docs/research/**` | **ours** | the audit trail: every claim with its evidence, **including our own conclusions that were retracted along the way** (most recently the raw-vector RaBitQ numbers, §5.6b) |
| `results/**` | **ours (generated)** | the citable store: every product the paper cites, plus the **raw stdout logs** under `results/logs/` (277 files copied out of the local scratch directory, so a clone of this repository is self-sufficient for verification) |

**Traceability.** Every number in this draft resolves to a file under `results/**` or a log under `results/logs/**`,
and §11.3 + §11.6 give the table → artifact mapping. Statements without an artifact are explicitly labelled
as assumptions (e.g. the RedCaps row, §4.4).

**Licence.** This report is released under **Creative Commons Attribution 4.0 International (CC BY 4.0)**.
The code, scripts and artifacts in the accompanying repository remain under the upstream **Apache-2.0**
licence (`LICENSE`).

**Reproduction entry points.** §11.4 (the central claim, five commands) and §11.6 (the second repair, the
quantizer arm, the external benchmarks). The full unattended batch that produced the last group of numbers is
`scripts/research/p8_queue.py`, whose per-step log and summary
(`results/t2/p8_queue_summary.json`) are part of the artifact.

**What is *not* in the artifact.** The upstream paper's own source or LaTeX; the VIBE and embedding-model
downloads (public, large, and pinned by their own repositories); and the two blocked baselines of §10.3/L13.

## 12.5 Assembling this draft, and the submission build

This draft is thirteen Markdown files, `section-0-abstract.md` … `section-12-references.md`, in that order;
the section index in `section-0-abstract.md` is the authoritative table of contents. A submission build is
produced by one script, which assembles the sections in order, converts and embeds the six figures
(SVG → PDF) and compiles the PDF with Pandoc + Tectonic:

```bash
python scripts/paper/build_submission.py
# -> docs/paper/submission/quiver-reexamination.tex
# -> docs/paper/submission/quiver-reexamination.pdf
# -> docs/paper/submission/abstract-short.txt   (for the arXiv metadata field)
# -> docs/paper/submission/README.md            (fill-in checklist)
```

What remains before an actual submission, and cannot be automated: the **author/affiliation/e-mail block**
(filled from `README.md`'s placeholder), the **license choice**, and optionally folding §12's list into a
BibTeX bibliography. None of it changes any number in this draft.

# 1. Introduction

Binary-quantized (BQ) graph indexes promise a graph that navigates on 2-bit codes instead of full-precision
vectors: an order of magnitude less memory, and a hot path that is mostly popcount. Whether such an index is
*usable* on a given embedding distribution is therefore a question with real deployment consequences — and it
is the question the QuIVer paper (PVLDB 20) answers with a cross-dataset table spanning more than 90 points of
Recall@10 (0.40 % → 95.65 %) and a single index-free probe that predicts which side of the usability line a
dataset is on.

This paper is a **self-critical re-examination** of that claim by one of its co-authors, plus a constructive
repair of its two weakest points. We re-run the published benchmark on the released implementation, on a
machine without AVX-512, and report what survives, what does not, and what a deployer should do instead.
§1.1 states the provenance, and what we did to keep the exercise honest.

**What we find.**

1. **All twelve rows reproduce** (eleven unconditionally within ±1.84 pp; the RedCaps row only under an assumed sampling protocol, whose four plausible readings span 7.4 pp). Our numbers come
   from the authors' own index driven by our harness, with all arms in a single process — so the table in §4
   is comparable value-for-value with the published one. This is the foundation for everything else.
2. **The published tiers describe *applicability*, and are routinely read as *competitiveness* — they are not
   the same thing (§5).** Where competitor curves exist, three of the four tiers are dominated by plain HNSW,
   including the tier the paper labels "moderate". The judgement needs no QPS argument: on several rows
   QuIVer's recall *ceiling* sits below the baseline's *lowest* operating point, so the curves never intersect.
3. **The bottom tier contains three different failures (§6).** Some datasets collapse because the 2-bit code is
   asked to do something it cannot do (their sign plane is constant, `sign_info = 0.000`) — an *encoding*
   problem. Others collapse because the task has no usable neighbourhood structure at all: on Random-Sphere,
   HNSW also collapses (1.40 % at `ef=64`), and on Gaussian-960 all three HNSW implementations and IVF-Flat do
   (1.10–2.41 %). A third fails on code *capacity* alone — the VIBE benchmark `coco_nomic` is the clean example
   (§9.5) — and here the fix is a different code: at 4 bits per dimension every collapse row measures ≥ 94.6 %
   (§6.5). The paper answers all three with "use float32", which hides that the first is repairable, the second
   is not, and the third is repairable only by changing the code.
4. **The probe is under-specified, and the gaps have consequences (§7).** §6 of the paper does not say which
   of the engine's two BQ distances to use, how many samples, or which instrument. Implemented with the
   paper's own default metric, the probe calls Random-Sphere *compatible* (53.9%) on a dataset whose measured
   recall is **0.91 %**. Taking the weaker of the two metrics fixes this without changing any other verdict,
   and pairing it with a sign-entropy statistic yields a four-step decision chain that we validate on 22 arms
   — including a **6/6 prospective hold-out** frozen before those six arms were measured (§7.3).
5. **The collapse is repairable by a two-step, data-side intervention (§8).** One translation
   (`x' = normalize(x − μ)`) moves GIST-960 from 2.10 % to 39.74 % and SIFT-128 from 15.77 % to 30.64 % at
   `ef=64`, with an isotropic control that moves by **+0.03 pp**; making the L0 navigation metric match the
   one the graph was built with adds up to **+21.8 pp** on rows whose sign plane is alive — and *hurts* rows
   whose sign plane is dead, which is why we ship it as a default-off switch with a decision rule.
   After the repair, two arms move from "dominated" to "parity" or "intersecting" — but the paper's honest
   sentence survives: **a smaller gap is not availability**. Where the sign plane is *dead*, a **seeded random
   rotation** — which leaves the similarity function untouched (GT overlap 99.87–100 %) — does better still
   (**60.22 % / 60.24 %** at `ef=64`) and turns GIST-960 into a *win* (1.3× faster than HNSW at 84 % recall,
   and the only measured option in the 60–84 % recall band); on a live sign plane it hurts (Cohere −4.8 pp),
   so the same statistic decides which of the two repairs to use.
6. **The boundary is the code's, not the data's — and a different code steps around it (§5.6, §8.7).** Table 11
   carries no quantizer baseline; on all six cells we measured, an OPQ+IVF-PQ+Refine pipeline with the same f32
   re-ranking never collapses — 98.99 % / 98.42 % on the two tasks where the 2-bit code collapses hardest — at
   ≈ 4.7× QuIVer's memory. QuIVer keeps the win at the competitive tier (3.7× at ≥ 99 % recall). The same
   measurement also surfaced a trap that can fake such a verdict — a cosine ground truth on raw vector files —
   which we diagnose and document rather than hide (§5.6b).
7. **Two engineering facts the paper does not report (§8.3, §9.2)**: the L0 query navigation uses a *different*
   distance than build/prune/upper layers, and the `α` default sits at the worst end of its own platform.

**What we do not claim.** We do not claim the paper is wrong: its mechanism (Finding 1 — the sign plane of
non-negative embeddings carries no information) is the same mechanism we measure, and we reproduce it. We do
not propose a new quantizer, and we do not claim a single scalar can predict recall: our two attempts to build
one failed and are reported as failures (§7.4). The contribution is a deployment-oriented *triage rule*, a
*competitiveness* boundary the published table does not draw, and a quantified repair path.

**Roadmap.** §2 fixes notation; §3 the harness and protocol; §4 the reproduction; §5 competitiveness;
§6 diagnosis; §7 the probe and our repaired chain; §8 the repair and its competitor consequence;
§9 discussion; §10 limitations; §11 artifacts.

## 1.1 Provenance, conflict of interest, and how we kept ourselves honest

**Provenance.** One of us (C.L.) is a co-author of QuIVer and of the accompanying implementation — i.e. of the
artifact this report evaluates, and of the claims it takes as its object of study. This is therefore a
**self-critical re-examination, not an independent evaluation**, and it should be cited as such. Several of
our own earlier claims do not survive the baselines and controls added here.

**Why publish it anyway.** A published boundary is only as strong as the strongest test it has survived, and
the tests that matter for this boundary — competitor curves on the same task, what a *different* quantizer
family does on the same rows, and where the probe's unstated parameters lead — were missing from our own
account. Reporting them ourselves is less comfortable, and more useful, than waiting for someone else to.

**What we did to keep it honest.** (i) Every number, script and **raw stdout log** is in the artifact
repository (`results/**`, `results/logs/`), so any claim here can be re-derived or refuted; (ii) findings that
argue against our own published claims appear where they are contradicted, not in an appendix; (iii) our own
intermediate conclusions are **retracted in the audit trail** (`docs/research/**`) rather than quietly dropped;
(iv) the two single-scalar recall predictors we pre-registered failed, and are reported as failures (§7.4);
and (v) the one comparison that inverted — a same-family quantizer arm measured against a ground truth that
disagreed with the vector files on the metric — is documented in full (§5.6b) instead of deleted. External
replication is welcome; nothing here requires trusting us.

**AI-assistant disclosure.** In the spirit of the disclosure in our earlier paper, we note that the
implementation work, the analysis scripts and the manuscript were prepared with substantial assistance from an
AI coding assistant; all research design, experiment execution, analysis and conclusions remain the
responsibility of the author.

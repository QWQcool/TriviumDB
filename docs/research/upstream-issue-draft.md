# Upstream issue drafts — paste-ready, NOT YET FILED

> **Status: DRAFT.** Nothing here has been sent. Reviewer: pick the issues you want, paste the body into
> `YoKONCy/TriviumDB` (or email the authors), and attach the linked artifacts.
> Evidence lives in `results/**` and `docs/research/*.md` in this fork
> (`github.com/QWQcool/TriviumDB`, branch `research/quiver2-pipnn-rabitq-tsng`).
> Tone: we reproduce the mechanism and agree with it; these reports are specification gaps and defaults,
> not claims that the method is wrong. Full Chinese evidence: `docs/research/upstream-issues.md`.

---

## Draft 1 — L0 query navigation uses a different BQ distance than build/prune

**Title:** `L0 beam search uses plain Hamming while build/prune use the weighted BQ distance — intentional?`

**Body:**

Build/prune/upper layers use `distance_to_sig` (2-bit, 6-class **weighted**), while the **L0 beam search**
uses `distance_to_sig_cheap` (**plain Hamming**). There are three navigation sites:
`src/index/quiver.rs` lines 1272–1281 (main path), 1343–1346 (dual/signal path), 1513–1518 (384-d scratch path).

The paper's §3.2/§3.3 read as if one family of symmetric BQ distances is used throughout
("XOR + Popcount"), so this may be an implementation/paper wording gap rather than a deliberate choice.

We measured an A/B with a **default-off** switch that makes the three sites consistent
(`patches/f1-nav-weighted.patch`; with the switch unset the behaviour is bit-identical — frozen values
reproduce within 0.17 pp). Same binary, same task, 32 threads:

| dataset | `sign_info` | ΔR@10 @ef_s=64 | ΔR@10 @ef_s=1024 | QPS cost |
|---|---|---|---|---|
| GloVe-100 | 0.946 | **+21.8 pp** | +21.6 pp | −4.9 % |
| Gaussian-960 | 1.000 | **×2.9** (0.83 → 2.44 %) | ×4.6 | −9.3 % |
| Wolt-CLIP-512 | 0.836 | +0.9 pp | +2.5 pp | −6.1 % |
| Cohere-768 | 0.747 | +0.5 pp | +0.2 pp | −6.9 % |
| SIFT-128 | **0.000** | **−13.4 pp** | −10.8 pp | −5.7 % |
| GIST-960 | **0.000** | −1.3 pp | −1.2 pp | −3.6 % |

Perfect separation by `sign_info` (mean per-coordinate sign entropy, §6.2 of our report): ≥ 0.74 ⇒ every
dataset gains; `= 0.000` ⇒ every dataset is harmed. So we ship it as a *data-dependent* switch with
`sign_info` as the decision rule, not as an unconditional fix.

**Question:** is the Hamming-at-L0 choice deliberate (cheap metric for QPS), or should the three sites use the
build metric? Either way §3.2/§3.3's wording could state which distance applies where.

**Patch:** `patches/f1-nav-weighted.patch` (also fixes the `TsngNavigationScorer::max_bq_distance` truncation
bound, `2·dim → 4·dim`, which otherwise saturates all weighted distances).

---

## Draft 2 — The "Practical compatibility test" (§6) needs three specifications

**Title:** `§6 compatibility probe: which BQ distance, how many samples, which instrument?`

**Body:**

The probe is defined as "≈10 K sample vectors, rank by the BQ code, compare with the float32 ranking by
top-K overlap, > ~50 % ⇒ compatible". Three things are unstated, and each one changes verdicts:

| observation | number |
|---|---|
| Implemented with the paper's own default metric (`weighted`) | **Random-Sphere** (measured R@10 @ef=64 = **0.91 %**) probes at **53.9 % > 50 %** ⇒ "compatible" — a **false positive** |
| With `min(weighted, cheap)` instead | **4.7 %** ⇒ correct warning; **no other row's verdict changes** |
| Candidate-sample-size sensitivity | probe value moves by up to **6.8×**, systematically **more optimistic with fewer samples** |
| Query-subset sensitivity | 4–7 pp spread between subsets |
| Instrument: literal "code top-10" vs "code top-ef → f32 re-rank" | top-10 understates what search achieves (GloVe-100: 67.8 % vs measured 71.7 %); top-ef tracks recall (ρ = +0.95 on our 9-dataset check) |

Suggested spec additions: (1) state the metric (we suggest the **weaker of the two**); (2) state the sample
size *and its rationale*, and average over several subsets; (3) define the instrument as
**"code top-ef → f32 re-rank"**. Otherwise the same dataset can flip between go and no-go by changing an
unstated parameter.

---

## Draft 3 — Two vector→code paths must share any transform (trap we hit)

**Title:** `Note for future transforms: Bq2Signature::from_vector and Bq2Store::push_from_vector are two code paths`

**Body:**

If a transform (rotation, scaling, PCA) is ever applied to the codes, note that the engine creates codes in
**two** places: `Bq2Signature::from_vector` and `Bq2Store::push_from_vector`. In our seeded-rotation
experiment, rotating only the first left the *stored* codes unrotated and SIFT-128 read **0.01 %** at
`ef=64` — far worse than doing nothing. Sharing one transform between the two paths fixed it (152 library
tests pass). No action requested if you do not plan a transform; reporting it because the failure mode is
silent.

---

## Draft 4 — RedCaps-1M sampling protocol (our only unreproduced row)

**Title:** `RedCaps-1M row: which 1M slice, and are self-matches excluded?`

**Body:**

We downloaded the Zenodo record 13137120 referenced by `README_QUIVER.md` §1c (22.12 GiB, MD5 verified) and
reproduced 11 of 12 rows of Table 11 within ±1.84 pp. The RedCaps row is the exception, because two
specification gaps in the guide change the number:

1. **Which 1 M of the 11,588,824 rows** forms the base — file order → 69.66 %; random seeds 7/2026/42 →
   73.94 / 75.27 / 76.02 %.
2. **Self-match policy** — `random_test` is drawn from the same pool as `train` (≈ 9.7 % of queries have an
   exact duplicate in any 1 M base); keeping self-matches gives our best value **77.08 %**.

Across the four plausible readings the row spans **7.4 pp** (69.66 → 77.08) against the paper's 78.41 %.
We report 77.08 % as "conditional on an inferred protocol". If you can state the rule (and whether ground
truth was recomputed inside the chosen 1 M), we will re-run and report the exact value.

---

## Draft 5 — Defaults and doc nits (one line each)

**Title:** `Defaults: m=16 vs paper's m=32; alpha=1.2; README numbering; "zero preprocessing" wording`

1. `QuIVerConfig::default().m = 16`, while every experiment in the paper uses **m = 32** — users who take the
   library default run at a different operating point; a README note would help.
2. `alpha` default **1.2** sits at the worst end of its own platform in our sweep; **α = 1.0** gives
   +1.02 pp on Cohere and +5.02 pp on SIFT-128 (build cost +14–22 % in our runs vs the paper's Table 9
   reporting 2.4× — worth confirming which number is right).
3. `README_QUIVER.md` numbering: the text says "§5.6 Table 10 & Figure 4" where it means **Table 11 /
   Figure 3** (Table 10 is the encoding ablation).
4. "zero preprocessing" is the *largest applicability premise* of the design: on a dead sign plane a single
   centring (`x' = normalize(x − μ)`) is the repair we measured (GIST-960 2.10 → 39.74 %, SIFT-128
   15.77 → 30.64 %, isotropic control +0.03 pp; Cohere neutral −1.2 pp). A sentence in §7 pointing at that
   would make the boundary statement actionable. (Rotation is the task-preserving alternative —
   GIST-960 60.22 %, SIFT-128 60.24 % at `ef=64`, no change to the similarity function.)

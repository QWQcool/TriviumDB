# Applicability Is Not Competitiveness: An Independent Evaluation and a Data-Side Repair for BQ-Native Graph Indexing

**Abstract.** Binary-quantized graph indexes navigate on 2-bit codes instead of full-precision vectors, and
the published answer to "when is that usable?" is a 12-dataset table spanning 0.40 % → 95.65 % Recall@10 plus a
single index-free compatibility probe. We re-run that benchmark on the authors' released implementation (11 of
12 rows reproduced within ±1.84 pp; one row is protocol-ambiguous) and report four things the published
account does not cover. **(i)** The table's tiers describe *applicability*, and are read as *competitiveness*;
where competitor curves exist, three of the four tiers are dominated by plain HNSW — on several rows QuIVer's
recall ceiling lies below the baseline's lowest operating point, so the curves cannot intersect. **(ii)** The
bottom tier mixes two different failures: a *repairable encoding* failure (the sign plane is globally constant,
`sign_info = 0.000`) and an *index-agnostic task* failure on which HNSW also collapses (Random-Sphere: 1.40 %
at `ef=64`). **(iii)** The published probe is under-specified — it does not fix the BQ distance, the sample
size, or the instrument. Implemented with the paper's own default distance, it calls Random-Sphere *compatible*
(53.9%) on a dataset whose measured recall is **0.91 %**; taking the weaker of the engine's two distances
removes this false positive without changing any other verdict, and a sign-entropy statistic paired with it
yields a four-step decision chain validated on 22 arms. **(iv)** The collapse is repairable without touching
the index: one translation (`x' = normalize(x − μ)`) takes GIST-960 from 2.10 % to 39.74 % and SIFT-128 from
15.77 % to 30.64 % at `ef=64`, with an isotropic control moving **+0.03 pp**; making the L0 navigation metric
match the metric the graph was built with adds up to **+21.8 pp** where the sign plane is alive and *hurts*
where it is dead, so we ship it as a default-off switch with a decision rule. After the repair two arms move
from "dominated" to "parity" or "intersecting" — but the honest sentence survives: **a smaller gap is not
availability.** We do not claim the paper is wrong (its mechanism is the one we measure), we propose no new
quantizer, and we report our own two failed attempts at a single-scalar recall predictor.

---

## Section index

| § | File | Content |
|---|---|---|
| 1 | `section-1-intro.md` | motivation, six findings, what we do **not** claim, roadmap |
| 2 | `section-2-background.md` | the 2-bit encoding, the two distances, what the paper already establishes, baselines, relation to rotation-based quantizers |
| 3 | `section-3-methodology.md` | harness + equivalence, metrics, configuration, protocol deviations, noise floor, index-free instruments, the competitiveness-vs-QPS rule |
| 4 | `section-4-reproduction.md` | the 12-row reproduction table, speed re-check, tie floors |
| 5 | `section-5-boundary.md` | applicability ≠ competitiveness; the tier × competitor map; QPS-free domination test |
| 6 | `section-6-diagnosis.md` | the mechanism in closed form; `sign_info`; graph fidelity (9 datasets); **two kinds of collapse** |
| 7 | `section-7-judge.md` | the three specification gaps and their measured cost; the repaired four-step chain; our two failed predictors |
| 8 | `section-8-repair.md` | centring tier-by-tier with the no-op control; the navigation-metric A/B; the **7-arm competitor map**; what the repair is not |
| 9 | `section-9-discussion.md` | the deployment decision table; why translation rather than rotation; what this implies for the published claim |
| 10 | `section-10-limitations.md` | platform, protocol, the one unresolved row, the tie floor, scope, statistical conventions |
| 11 | `section-11-artifacts.md` | harness, scripts, table → artifact map, one-command reproduction, upstream material |

**Evidence base.** Every number in this paper resolves to a file under `results/**` or a log under `.tmp/`;
the audit trail (including three conclusions of ours that were retracted) is in `docs/research/*.md`.
The only library change is a default-off switch shipped as `patches/f1-nav-weighted.patch`.

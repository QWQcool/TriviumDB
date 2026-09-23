# 8. A Two-Step Data-Side Repair

> **Draft** 2026-09-22 ｜ sources: `t2-gist960-collapse.md`, `f1-metric-consistency.md`, `audit-and-direction.md` §1.2/§9
> ⚠️ **Read the task definition first.** Centring changes the similarity function: every "after" number below is
> Recall@10 **on the centred-cosine task**, not an improvement on the original task (limitation L3, §10).
> Centring is also not our invention — it is standard post-processing in the embedding literature
> (all-but-the-top family). What is new is that it is **triage-able in seconds** and that we quantify when it
> works, when it is neutral, and when it is useless.

## 8.1 Step 1 — centre: `x' = normalize(x − μ)`

`μ` is the mean of the **normalised** training vectors. Implementation guard (a real bug we hit):
the on-disk vectors of some sources are **not** unit-norm (Cohere's are not), so taking the mean of the raw
rows gives `‖μ‖ = 11.5` — subtracting that from unit vectors collapses every direction
(random-pair cosine 0.9973). We therefore assert `‖μ‖ ≤ 1` (the mean of unit vectors cannot exceed 1) and
compute `μ` after re-normalisation. This guard is in the released script.

## 8.2 What centring does, tier by tier

| Tier | Dataset | `‖μ‖` | @ef_s=64 before → after | Δ | @ef_s=1024 before → after | Δ |
|---|---|---|---|---|---|---|
| collapse | **GIST-960** | 0.868 | 2.10 % → **39.74 %** | **+37.6** | 4.38 % → 79.44 % | +75.1 |
| collapse | **SIFT-128** | 0.650 | 15.77 % → **30.64 %** | **+14.9** | 47.23 % → 85.21 % | +38.0 |
| collapse | Random-Sphere (**control**) | **0.001** | 0.48 % → 0.51 % | **+0.03** | 6.46 % → 6.58 % | +0.12 |
| usable | **GloVe-100** | 0.354 | 32.82 % → **36.11 %** | +3.3 | 71.69 % → 73.28 % | +1.6 |
| usable | Synthetic-LR | 0.204 | 43.60 % → 43.89 % | +0.3 | 92.52 % → 94.69 % | +2.2 |
| moderate | **Wolt-CLIP-512** | 0.797 | 71.48 % → **76.81 %** | **+5.3** | 86.81 % → 89.14 % | +2.3 |
| competitive | **Cohere-768** | 0.834 | 94.63 % → 93.48 % | **−1.2** | 99.78 % → 99.86 % | +0.1 |

Two readings that matter for the paper's framing:

1. **The no-op control is clean.** Random-Sphere is already isotropic (`‖μ‖ = 0.001`); its Δ is **+0.03 pp**,
   i.e. the pipeline introduces no artefact. Centring is therefore *not* a general-purpose trick that
   "always helps a bit".
2. **The gain is not a function of `‖μ‖` alone — it is a function of whether the sign plane was dead.**
   Cohere has `‖μ‖ = 0.834`, the same order as GIST's 0.868, yet its Δ is **−1.2 pp** (neutral): 41 % of its
   coordinates are negative, so the sign plane is alive and there is little to repair. Conversely
   GloVe (`‖μ‖ = 0.354`) still gains **+3.3 pp** because its sign plane is marginal.
   This is exactly what `sign_info` (§6.2) measures: **0.000 for the two big gainers**, ≥ 0.597 for everyone else.
3. **The repair does not fix an index-agnostic collapse.** Random-Sphere's +0.03 pp is the honest boundary of
   the method; §6.4 explains why, and §8.4 shows the competitor consequence.

## 8.3 Step 2 — use the metric the graph was built with (data-dependent)

The engine builds and prunes with the 6-class weighted distance but navigates L0 with plain Hamming.
We added a default-off switch (`TRIVIUM_NAV_WEIGHTED`) that makes the three navigation sites consistent
(§9.2 of the upstream material; patch in `patches/`). Measured A/B on 6 datasets, same binary, same task:

| Dataset | `sign_info` | ΔR@10 @ef_s=64 | ΔR@10 @ef_s=1024 | QPS cost |
|---|---|---|---|---|
| GloVe-100 | **0.946** | **+21.8 pp** | +21.6 pp | −4.9 % |
| Gaussian-960 | **1.000** | **×2.9** (0.83 → 2.44 %) | ×4.6 | −9.3 % |
| Wolt-CLIP-512 | **0.836** | +0.9 pp | +2.5 pp | −6.1 % |
| Cohere-768 | **0.747** | +0.5 pp | +0.2 pp | −6.9 % |
| **SIFT-128** | **0.000** | **−13.4 pp** | −10.8 pp | −5.7 % |
| **GIST-960** | **0.000** | −1.3 pp | −1.2 pp | −3.6 % |

**Perfect separation by `sign_info`**: ≥ 0.74 ⇒ every dataset benefits; = 0.000 ⇒ every dataset is harmed.
Mechanism: when the sign plane still carries information, the weighted metric also exploits the magnitude
plane and navigates better; when it is dead, the weighted metric's `|h|` bias is *navigated into* directly.
⇒ This is a **data-dependent trade-off**, not an unconditional bug fix; the switch is the delivery vehicle,
`sign_info` is the decision rule. Regression guard: with the switch **off**, frozen recall values reproduce
(Cohere 97.52 / GIST 2.79 / GloVe 45.60 within ≤ 0.17 pp, i.e. within the measured G-det spread of 0.27 pp).

## 8.4 The competitor map: what the repair does and does not buy

Same task on both sides (the centred task's own GT; competitor curves rebuilt on the centred data), so the
verdict is machine-independent. "Pipeline upper" = centring + weighted navigation.

| Tier | Arm | Before: QuIVer upper / HNSW `ef=64` | After: pipeline upper (@QPS) | After: competitor (best point) | Verdict |
|---|---|---|---|---|---|
| collapse | GIST-960 | 4.38 % / 84.11 % @5,417 | **82.77 %** @4,717 | 84.85 % @6,734 | dominated → **dominated** (gap 79.7 → **2.1 pp**) |
| collapse | SIFT-128 | 47.21 % / 97.46 % @45,118 | **92.47 %** @15,629 | 97.06 % @50,547 (centred curve) | dominated → **dominated** (49.9 → **4.6 pp**; baseline also 3.2× faster at that recall) |
| collapse | Random-Sphere | 6.46 % / **1.40 %** (HNSW also collapses) | **17.78 %** @1,867 | 17.43 % @285 (ef=1024) | **parity-or-better: 6.3–7.9× faster at matched recall** |
| usable | GloVe-100 | 71.69 % / 82.05 % @36,047 | **93.32 %** @11,675 | 93.45 % @10,893 (ef=256) | dominated → **parity (≈1.07×)** |
| usable | Synthetic-LR | 92.52 % / *not measured on the original task* | **97.05 %** @2,638 | USearch 97.45 % @375; FAISS-HNSW 97.90 % @342 | after: **QuIVer ~7.0–8.5× faster at matched recall** (no "before" verdict available) |
| moderate | Wolt-CLIP-512 | 86.81 % / 87.86 % @19,606 | **89.05 %** @9,356 | 87.88 % @20,849 (centred curve) | dominated → **curves intersect** (≤87.9 % baseline 1.1–1.3× faster; ≥89 % QuIVer **2.3–3.9×** faster) |
| competitive | Cohere-768 | 99.78 % / 96.30 % @9,514（HNSW's best point 99.84 % @741 ⇒ ≈4.6× at ~99.8 %） | **99.89 %** @4,037 | 99.93 % @1,435 (99.79 % @2,544) | win → **win, narrower: ≈2.7–3.4×** at matched recall |

**The honest sentence this table requires**: *a smaller gap is not availability.* GIST and SIFT move from
"hopeless" to "within 2–5 pp" — but at that recall the baseline is also faster. The arms where the verdict
actually changes are GloVe (**dominated → parity**) and Wolt-CLIP (**dominated → intersecting**); on
Random-Sphere and Synthetic-LR QuIVer's pipeline is the faster index at matched recall, but in the first case
*no* graph index is usable and in the second the "before" verdict was never measured.
On the competitive tier the win survives centring but narrows (≈4.6× → ≈2.7–3.4×), because centring helps
HNSW as well: its centred curve is faster at the same recall (99.79 % @2,544 vs 99.84 % @741 uncentred).

## 8.5 What this repair is not

* It does not change the similarity function's *meaning* (L3) — a deployer must accept centered-cosine.
* It does not help index-agnostic collapse (Random-Sphere, Gaussian-960): +0.03 pp.
* It does not touch the competitive tier's victory, and it does not create one where none existed.
* It adds no new theory: the mechanism is the paper's own Finding 1, and centring is known post-processing.
  The contribution is the **triage rule** (`sign_info`) + the **quantification** + the two-arm delivery path.

## 8.6 A second repair, and on the collapse tier a better one: a seeded rotation

Centring has the defect we disclosed up front (L3): it **changes the similarity function**. There is a
classical alternative that does not — a random orthogonal transform. For unit vectors `cos(Qa, Qb) = cos(a,b)`,
so **the task is provably unchanged** (we verify it: the rotated task's GT overlaps the original's by
**99.87–100 %**), while the *code* is recomputed in a basis where the sign plane is alive. We generate `Q` by
QR-factorising a Gaussian matrix from a **fixed seed**, so it costs **zero storage** (dim + seed suffice) and
no training — it is the same device RaBitQ uses.

**Collapse tier: rotation beats centring, and keeps the task.**

| Dataset | original @ef=64 | centred @ef=64 | **rotated @ef=64** | original @1024 | centred @1024 | **rotated @1024** |
|---|---|---|---|---|---|---|
| GIST-960 | 2.10 % | 39.74 % | **60.22 %** (+58.1 pp) | 4.38 % | 79.44 % | **88.99 %** |
| SIFT-128 | 15.77 % | 30.64 % | **60.24 %** (+44.5 pp) | 47.23 % | 85.21 % | **95.74 %** |

Graph construction also gets **2–6× faster** (GIST 290.4 s → 47.2 s; Cohere 202.4 s → 31.5 s), and the sign
statistic moves from `sign_info = 0.000` to 0.507/0.759.

**…but it is not a universal repair.** Rotation mixes coordinates: it revives the sign plane and *flattens*
the magnitude plane. So it is a pure win exactly where the magnitude plane was a *harmful* signal, and a
loss where both planes carried information:

| Tier | Dataset | `sign_info` before → after | Δ @ef=64 | reading |
|---|---|---|---|---|
| collapse | GIST-960 | 0.000 → 0.507 | **+58.1 pp** | sign plane dead, magnitude plane harmful ⇒ rotating is pure gain |
| collapse | SIFT-128 | 0.000 → 0.759 | **+44.5 pp** | same |
| usable | GloVe-100 | 0.946 → 0.938 | −0.6 pp alone, **+21.8 pp** with the weighted navigation | magnitude plane useful ⇒ needs §8.3's nav metric to pay off |
| competitive | Cohere-768 | 0.747 → 0.572 | **−4.8 pp** | both planes useful ⇒ rotation is a net loss |

⇒ The decision rule stays `sign_info`: **0.000 ⇒ rotate** (better than centring *and* task-preserving);
**alive ⇒ do not rotate** (Cohere's −4.8 pp is the empirical warning).

**Competitor consequence** (no re-measurement needed: the task is unchanged, so the §5 curves still apply):

| Dataset | matched point | rotated QuIVer | strongest competitor | verdict |
|---|---|---|---|---|
| **GIST-960** | ~84.4 % | **84.41 % @7,148** | hnswlib 84.11 % @5,417 | ✅ **QuIVer is 1.32× faster** |
| | ~89.0 % | 88.99 % @3,609 | IVF-Flat 88.36 % @765 | ✅ 4.7× vs IVF; ≈parity vs HNSW (interpolated) |
| | **60–84 % band** | 42,261 → 7,148 QPS | **no operating point** (hnswlib's lowest `ef=64` already gives 84.11 %) | ✅ in that band QuIVer is the only option measured here |
| SIFT-128 | ~95.7 % | 95.74 % @17,536 | hnswlib **97.46 % @45,118** | ❌ still dominated (gap 49.9 → **1.7 pp**) |

⇒ **GIST-960 moves from "strictly dominated (79.7 pp gap)" to "faster at both ends of the usable band, and
the only option in the 60–84 % band".** SIFT stays dominated — HNSW is simply excellent there — but the gap
shrinks from ~50 pp to **1.7 pp**, and no task definition is harmed in either case.

**One more thing rotation buys us.** Because the two navigation metrics of §8.3 are decided by the *same*
code-only probe, we can now pick the navigation metric *predictively* instead of by `sign_info`:
use the weighted navigation iff `probe_ef(weighted) > probe_ef(cheap)`. Across the ten arms where we have both
the probe pair and an A/B measurement, this rule gets the **sign right in 9 cases**; the single miss
(`wolt_clip`) has −0.5 pp probe difference and +0.9 pp measured difference, i.e. both inside the noise floor.
It also fixes the one place where the `sign_info ≥ 0.75` heuristic fails (`sift128r`: `sign_info = 0.759`
would predict a gain, the measurement is **−10.2 pp**).

# 6. Diagnosis: Why the Code Fails, and Three Different Failures

> **Draft** 2026-09-22 ｜ every number traceable to `results/**` or `results/logs/*.log`
> Notation as in §4. *Sign plane* = the `pos = (v > 0)` plane; *magnitude plane* = the `strong = (|v| > mean|v|)` plane.

## 6.1 The mechanism, in one identity

QuIVer's weighted distance is a monotone transform of

```
S(a,b) = <w_a, w_b>,   where   w = (2p − 1) · (1 + s) ∈ {−2, −1, +1, +2}
```

We verified this against the implementation bit-for-bit (`bq2_code_ceiling.py::verify_identities`, max |analytic − bitwise| = 0).
Two consequences follow immediately.

**If the sign plane is constant**, `p ≡ 0` for every dimension, so `w = −(1 + s)` and

```
S(a,b) = <1 + s_a, 1 + s_b>  =  D + <s_a, s_b>  + Σ(s_a + s_b)
```

i.e. the ordering is dominated by the **magnitude statistics** of the two codes, not by their direction.
On GIST-960 we measure the resulting bias at **+3.34 σ** of the true (cosine) score spread, and the
`pos`-plane Hamming rate at **0.0000** — the sign plane carries **zero** bits of information.

**If the sign plane is alive**, the weighted score is a genuine two-plane match and the ordering tracks
cosine. This is why the repair in §8 works at all, and why it is *data-dependent* rather than universal.

## 6.2 Quantifying "alive": `sign_info`

We summarise the sign plane by the mean per-coordinate sign entropy

```
sign_info = mean_j H(p_j),   p_j = P(v_j < 0),   H(p) = −p log₂ p − (1−p) log₂(1−p)   [bits]
```

On **22 arms** (12 paper datasets + centred variants + planted controls) the distribution is *bimodal with a
wide gap*: `sign_info = 0.000` exactly for `gist960` (at 128/256/512/768/960 dims) and `sift128`, and
**0.597 – 1.000** for every other arm. This is the quantity that distinguishes "the code is being asked to
do something it cannot do" from "the task itself is hard" — see §6.4.

*Negative result we report:* the per-coordinate **minimum** `min_j H(p_j)` is **not** usable — it fires on
healthy data (Cohere, R@10 97.51 %, has `min_j H(p_j) = 0.000` because a few coordinates are pinned by a
strong mean direction). Only the *mean* separates.

## 6.3 The graph is faithful to the wrong metric

For each dataset we exported the L0 adjacency (CSR, `bench_t2_build_recon`) and measured its overlap with the
true top-64 under three metrics (256 sampled nodes, self-loops excluded):

| Dataset | Tier | **L0 ∩ cos_top64** | L0 ∩ w_top64 (**build** metric) | L0 ∩ cheap_top64 (**query** metric) | measured R@10 @128 |
|---|---|---|---|---|---|
| Cohere-768 | competitive | **56.84 %** | 77.84 % | 62.82 % | 97.51 % |
| MiniLM-384 | competitive | **65.80 %** | 82.10 % | 58.11 % | 94.28 % |
| Wolt-CLIP-512 | moderate | **53.19 %** | 72.40 % | 58.50 % | 77.73 % |
| GloVe-100 | usable | **31.82 %** | 64.24 % | 20.78 % | 45.60 % |
| GIST-960 (centred) | repaired | **27.98 %** | 53.60 % | 30.07 % | 51.96 % |
| SIFT-128 | collapse | **4.34 %** | 60.99 % | 17.00 % | 21.88 % |
| GIST-960 | collapse | **1.01 %** | 65.62 % | 0.79 % | 2.81 % |
| Gaussian-960 (control) | index-agnostic | 4.67 % | 7.13 % | 1.80 % | 0.83 % |
| Gaussian-960 + planted NN | positive control | 4.47 % | 7.24 % | 1.84 % | **100.00 %** |

Three readings:

1. **The index executes its instructions.** `L0 ∩ w_top64` is 53–82 % everywhere, while `L0 ∩ cos_top64`
   spans **1.01 % → 65.80 %**. Collapse rows have graphs that are *cosine-random* (GIST 1.01 %), not badly
   built graphs.
2. **Fidelity tracks recall across 9 datasets** (1.01→2.81, 4.34→21.88, 27.98→51.96, 31.82→45.60,
   53.19→77.73, 56.84→97.51, 65.80→94.28) — it is closer to the real bottleneck than any code-side probe.
3. **But it is not sufficient**: the planted-NN control reaches **100 %** recall with 4.47 % fidelity (the
   planted neighbours are so close that even a bad graph finds them). Consistent with our two failed
   single-scalar predictors (§7.4): there is no one quantity that predicts everything.

## 6.4 Three different failures inside the paper's "< 15 %" tier

The competitor curves we ran on the *same* tasks (§8.4) plus the VIBE row `coco_nomic` (§9.5) reveal that the
paper's bottom tier mixes three phenomena with three different deployment answers:

| | **(i) Code-specific collapse** | **(ii) Index-agnostic collapse** | **(iii) Capacity collapse** |
|---|---|---|---|
| Representatives | GIST-960, SIFT-128 | Random-Sphere-1M, Gaussian-960 | `coco_nomic` (VIBE, 768-d) |
| `sign_info` | **0.000** | **1.000** | **0.382** |
| HNSW `ef=64`, same task | **normal**: 84.11 % / 97.06 % | **also collapses: 1.40 % (Random-Sphere) / 1.10–1.39 % (Gaussian-960, three implementations)** | **normal: 86.23 %** @ 17,053 |
| Centring | **+37.6 / +14.9 pp** (2.10→39.74, 15.77→30.64 @ef_s=64) | **+0.03 pp** (0.48→0.51) | helps little (still 2-bit) |
| Seeded rotation (task-preserving) | **+58.1 / +44.5 pp** (2.10→60.22 @ef=64) | no gain (report: +0.03 pp) | **useless: 0.21 → 0.70 %** |
| PQ/OPQ+Refine, same task | — (not measured) | — (not measured) | **98.42 %** @ 7,771 |
| 4-bit uniform code + re-rank | 99.05 % | **99.30 %** | 94.60 % |
| `L0 ∩ cos_top64` | 1.01 % / 4.34 % (27.98 % centred) | 4.67 % | — |
| What a deployer should do | centre **or** rotate — and still prefer HNSW unless a 2–5 pp gap is acceptable | **do not build a graph index on this task** | **change the code** (PQ pays 4.7× memory) or accept the loss |

**A second witness for (ii).** On Gaussian-960 we ran the full competitor set on the same task: hnswlib
**1.10 %**, FAISS-HNSW **1.30 %**, USearch **1.39 %**, and IVF-Flat **2.41 %** at `ef=64` — with every curve
still ≤ 19 % at `ef=1024`. Four independent indexes agree that this task has no usable neighbourhood structure,
so the index-agnostic reading is not an artefact of one HNSW implementation.

The paper answers all three with one sentence ("use float32"), which is correct as far as it goes but hides
that (i) is an *encoding* problem that can be repaired, (ii) is a *task* problem that cannot, and (iii) is a
*capacity* problem where the fix is a different code — the one remedy that gives up the 675 MiB advantage
this index exists for. `sign_info` separates (i) from (ii) for free, before any index is built; (iii) is the
case where both planes are partially alive and no pre-index statistic we tested separates it (§7.4).

## 6.5 The axis that actually moves the outcome: bits per dimension

To test whether "collapse" is a property of the data or of the code, hold the code family fixed and vary only
the budget. Instrument: per-dimension uniform quantization at *b* bits (min/max scaled), re-ranked exactly in
float32 over the code's top-128 (`ef=128`, 200 K sampled base vectors, 200 queries) — the same instrument as
the paper's own probe (§7.1), with the resolution turned into a variable (Figure 6).

| Dataset (tier the paper assigns) | 1 bit | **2 bit** | 3 bit | **4 bit** | 6 bit | 16 bit |
|---|---|---|---|---|---|---|
| GIST-960 (collapse) | 3.55 % | **55.25 %** | 60.25 % | **99.05 %** | 99.95 % | 100 % |
| Gaussian-960 (index-agnostic collapse) | 21.85 % | **23.05 %** | 76.10 % | **99.50 %** | 100 % | 100 % |
| Random-Sphere (collapse) | 20.85 % | **23.25 %** | 76.75 % | **99.30 %** | 100 % | 100 % |
| `coco_nomic` (capacity collapse) | 9.75 % | **31.60 %** | 76.10 % | **94.60 %** | 99.00 % | 100 % |

Three consequences, in order of how much they change the paper's wording:

1. **All four "collapse" datasets are ≥ 94.6 % at 4 bits.** The bottom tier is largely "2 bits per dimension
   cannot hold this distribution", not "this dataset cannot be quantized".
2. **The 2-bit sign–magnitude scheme is worse than naïve 2-bit uniform quantization** on the datasets where
   both exist: `coco_nomic` 3.59 % measured vs **31.60 %** in this table; Gaussian-960 0.83 % vs **23.05 %**.
   Spending one of the two bits on an almost-constant sign plane has a measurable price, and it is the
   quantity our repairs (centre / rotate) recover *without* adding bits.
3. **Random-Sphere's failure is not (only) in the code.** A 4-bit code with exact re-ranking reaches 99.30 %
   on that task, yet HNSW collapses (1.40 %) — so its problem is in the *graph*, consistent with §6.3's
   fidelity instrument. Only the code-side statistic and the graph-side statistic *together* separate the
   three failure types, which is why §7's chain uses both.

**Scope.** The 1-bit row of this table is **naïve 1-bit uniform**, and is *not* QuIVer's 1-bit ablation; it is
reported to bracket the axis, not as a competing implementation. The 16-bit row is the float32-equivalent
upper bound (100 % by construction, up to tie degeneracy).

![**Figure 6.** Bits per dimension vs achievable recall for a uniform scalar code with exact f32 re-ranking over the code's top-128 (200 K base / 200 queries, four collapse datasets). All four cross ≈ 94 % at 4 bits; the red markers are the shipped 2-bit sign–magnitude code measured on the same tasks.](figures/fig6-bit-budget.svg)

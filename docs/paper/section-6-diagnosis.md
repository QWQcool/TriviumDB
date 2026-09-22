# 6. Diagnosis: Why the Code Fails, and Two Different Failures

> **Draft** 2026-09-22 ｜ every number traceable to `results/**` or `.tmp/*.log`
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

## 6.4 Two different failures inside the paper's "< 15 %" tier

The competitor curves we ran on the *same* tasks (§8.4) reveal that the paper's bottom tier mixes two
phenomena with opposite deployment advice:

| | **(i) Code-specific collapse** | **(ii) Index-agnostic collapse** |
|---|---|---|
| Representatives | GIST-960, SIFT-128 | Random-Sphere-1M, Gaussian-960 |
| `sign_info` | **0.000** | **1.000** |
| HNSW `ef=64` on the same task | **normal**: 84.11 % / 97.06 % | **also collapses: 1.40 %** |
| Effect of centring | **+37.6 / +14.9 pp** (@ef_s=64: 2.10→39.74, 15.77→30.64) | **+0.03 pp** (0.48→0.51); Gaussian-960 same order |
| `L0 ∩ cos_top64` | 1.01 % / 4.34 % (27.98 % after centring) | 4.67 % |
| What a deployer should do | centre it — and *still* prefer HNSW unless a 2–5 pp recall gap is acceptable | **do not use any graph index on this task** |
| QuIVer vs HNSW | dominated before and after | **parity or better**: at matched recall QuIVer is **6.3–7.9×** faster |

The paper answers both with one sentence ("use float32"), which is correct as far as it goes but hides that
(i) is an *encoding* problem that can be repaired and (ii) is a *task* problem that cannot.
`sign_info` separates them for free, before any index is built.

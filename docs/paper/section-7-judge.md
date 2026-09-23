# 7. The Judge: Three Specification Gaps, and a Repaired Chain

> **Draft** 2026-09-22 ｜ sources: `p2-revised-result.md`, `t2-deployability-gate.md`, `results/t2/deployability_gate.json`
> We do **not** claim the paper's probe is wrong. We claim it is **under-specified**, and we measure what the
> specification gaps cost.

## 7.1 What is specified, and what is not

§6 of the paper ("Practical compatibility test") states: take ≈10 K sample vectors, rank them by the BQ code,
compare with the float32 ranking by top-K overlap, and read **> ~50 % ⇒ compatible, < 50 % ⇒ use a float32
index**. It needs no index. Three things are left open:

| gap | why it matters |
|---|---|
| **which** BQ distance | the engine has two: `weighted` (6-class, used for build/prune/upper layers) and `cheap` (plain Hamming, used for L0 query navigation) |
| sample **source and size** | base only, or base+queries? how many? |
| the **instrument** | "BQ-ranked Top-10" (literal) vs "code top-*ef* → f32 re-rank" (what a graph search actually does) |

## 7.2 What the gaps cost (measured)

**(a) The metric flips the verdict, and can produce a false positive.**
Implemented exactly as written with the paper's own default metric (`weighted`), the probe returns

| dataset | probe (`weighted`, top-ef) | probe (`min(w, cheap)`, top-ef) | measured R@10 @ef=64 |
|---|---|---|---|
| **Random-Sphere-1M** | **53.9 % ⇒ "compatible"** | **4.9 % ⇒ "use float32"** | **0.91 %** (paper: 0.40 %) |
| **Gaussian-960** (our control) | **55.0 % ⇒ "compatible"** | **4.7 % ⇒ "use float32"** | **0.83 %** |

So the verdict is *go* or *no-go* depending on an unstated choice — and the `weighted` reading is a false
positive on **two** datasets whose actual recall is under 1 %.
Taking the weaker of the two metrics repairs both without changing any other arm's verdict
(a third instance of the same ambiguity, measured with the literal top-10 instrument, is Synthetic-LR:
`weighted` 66.95 % vs `cheap` 45.25 % — opposite verdicts on the same data).

**(b) The probe is strongly sample-size dependent.** Sweeping the candidate sample size changes the probe
value by up to **6.8×**, and the direction is systematic: *fewer samples ⇒ more optimistic*.
Independently, different query subsets give a **4–7 pp** spread, so a single-run number is not quotable.

**(c) The literal instrument is pessimistic.** "Code top-10 ∩ f32 GT" understates what a graph search
achieves, because search uses the code to *navigate* and then re-ranks `ef` candidates in float32.
GIST-960 (centred) is the clearest case: top-10 gives **25.4–29.8 %** while the `top-ef` instrument gives
**70.5 %**, against a measured recall of **51.96 %**. On GloVe-100 the `top-ef` instrument returns **44.8 %**
against a measured **45.60 %**, and on Cohere **98.7 %** against **97.51 %**. In the P2 analysis the
`code_oracle` variant of this instrument tracked recall at ρ = +0.95; we therefore report the `top-ef`
instrument and never a single-run `top-10` value as a usability verdict.

## 7.3 The repaired chain

Four quantities, all computable in seconds and **before building any index**:

```
① sign_info  < 0.2                     ⇒ rotate (§8.6; task-preserving) or centre — the sign plane is globally degenerate
② ‖μ‖ ≥ 0.3 and headroom > 5 pp        ⇒ centre as well (the shift is large and there is room to gain)
③ probe_ef (min over both metrics,
   code top-128 → f32 re-rank) < 50 %  ⇒ use a float32 index
④ otherwise                            ⇒ BQ-native is usable (competitiveness is *not* predicted here)
```

Validated on **22 arms: 21 defensible verdicts** (the table in `results/t2/deployability_gate.json`; the
bimodal gap that makes rule ① work is `sign_info = 0.000` for the six GIST/SIFT arms vs **≥ 0.597** for all
other 18). The single boundary case is centred GloVe-100
(`probe_ef` = 44.9 % against a 50 % threshold), where "use float32" happens to be right for a *different*
reason (it is dominated by HNSW anyway, §8.4). Re-running the whole table with K = 3 query subsets
reproduces every verdict.

Two design notes that came out of the data, not of taste:

* **`sign_info` must be the mean** over coordinates (see §6.2) — the minimum fires on healthy data.
* **The gate deliberately abstains on competitiveness.** We show in §5 that competitiveness is a
  *per-workload* question (it needs a competitor curve), not a property of the code. Any single-number
  predictor of it is a promise we cannot keep (§7.4).

## 7.4 Our own two failed predictors (reported as such)

We pre-registered two single-scalar predictors and **both failed**; they are part of the record:

| attempt | pre-registered criterion | outcome |
|---|---|---|
| code-estimate SNR `(GT10 − GT11)/σ_code` | ρ ≥ 0.9 vs R@10 | ❌ **ρ = +0.30** with the Random-Sphere arm — `σ_code` is scale-free and collapses on unstructured data |
| separability (`cos_std` of random pairs) as a boundary predictor | monotone relation | ❌ **retracted** — centred SIFT is a counterexample (separability *falls* while recall doubles) |

Final position: the chain is **triage plus a necessary condition**, not a sufficiency claim. That is also why
the graph-fidelity axis (§6.3) is reported as a *correlate* (9 points) and not as a formula — fidelity is high
for the planted-NN control (100 % recall at 4.47 % fidelity) which no monotone predictor can accommodate.

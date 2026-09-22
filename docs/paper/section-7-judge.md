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

| dataset | probe (`weighted`, top-ef) | probe (`min(w, cheap)`) | measured R@10 @ef=64 |
|---|---|---|---|
| **Random-Sphere-1M** | **53.2 % ⇒ "compatible"** | **4.7 % ⇒ "use float32"** | **0.91 %** (paper: 0.40 %) |
| Synthetic-LR-1M | 66.95 % ⇒ compatible | **45.25 %** ⇒ **incompatible** | 43.60 % (paper: 41.76 %) |

So the same dataset is *go* or *no-go* depending on an unstated choice — and on Random-Sphere the
`weighted` reading is a false positive (**53.2 % vs an actual recall of 0.91 %**).
Taking the weaker of the two metrics repairs it without changing any other arm's verdict.

**(b) The probe is strongly sample-size dependent.** Sweeping the candidate sample size changes the probe
value by up to **6.8×**, and the direction is systematic: *fewer samples ⇒ more optimistic*.
Independently, different query subsets give a **4–7 pp** spread, so a single-run number is not quotable.

**(c) The literal instrument is pessimistic.** "Code top-10 ∩ f32 GT" understates what a graph search
achieves, because search uses the code to *navigate* and then re-ranks `ef` candidates in float32.
GIST-960 (centred) is the clearest case: top-10 gives **26.7 %** while the `top-ef` instrument gives **70.7 %**
and the measured recall is **51.96 %**. Across datasets the `top-ef` instrument tracks recall at **ρ = +0.95**
(GloVe-100: 67.79 % ↔ 71.69 %).

## 7.3 The repaired chain

Four quantities, all computable in seconds and **before building any index**:

```
① sign_info  < 0.2                     ⇒ centre (the sign plane is globally degenerate)
② ‖μ‖ ≥ 0.3 and headroom > 5 pp        ⇒ centre as well (the shift is large and there is room to gain)
③ probe_ef (min over both metrics,
   code top-128 → f32 re-rank) < 50 %  ⇒ use a float32 index
④ otherwise                            ⇒ BQ-native is usable (competitiveness is *not* predicted here)
```

Validated on **22 arms: 21 defensible verdicts**. The single boundary case is centred GloVe-100
(`probe_ef` = 45.6 % against a 50 % threshold), where "use float32" happens to be right for a *different*
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

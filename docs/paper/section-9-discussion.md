# 9. Discussion

## 9.1 The decision a deployer actually faces

Combining §5–§8 into one table — every quantity is computable **before** building an index, in seconds:

| `sign_info` | `‖μ‖` (headroom) | `probe_ef` (min of both metrics) | what to do | expected outcome |
|---|---|---|---|---|
| **= 0.000** (sign plane dead) | any | — | **centre**, then re-run the gate | encoding recovered: GIST 2.10→39.74 %, SIFT 15.77→30.64 % @ef=64; **still check §9.2 before deploying** |
| **≥ 0.6**, `‖μ‖ ≥ 0.3`, headroom > 5 pp | large | ≥ 50 % | centre as a cheap option | small-to-moderate gain (+0.3…+5.3 pp), never harmful in our 6-dataset set |
| **≥ 0.6** but headroom ≤ 5 pp | large | ≥ 50 % | **do not bother** | Cohere: −1.2 pp (neutral) — the tier is already at 95 % |
| any | any | **< 50 %** | **use a float32 index** | the code cannot rank; the fault is not fixable by translation |
| `sign_info` **= 1.000** but recall ≪ 50 % | ~0 | < 50 % | **do not build any graph index on this task** | index-agnostic collapse (Random-Sphere, Gaussian-960): HNSW also collapses (1.40 %) |

And one row the gate deliberately does **not** cover, because it needs a competitor curve:

| measured recall ≥ ~88 % on a competitive embedding | — | — | **QuIVer is the right index**: 4.6–5.0× at matched recall vs the best HNSW | the only tier where the paper's index actually wins (§5) |

## 9.2 Why translation, and not rotation or training

The failure we document is **first-order**: a non-negative embedding's mass lies off the origin, so the sign
plane is constant. An orthogonal transform would also revive it (a random rotation spreads the mass across
coordinates, so signs vary) — indeed rotation-based quantizers like RaBitQ rely on exactly that mechanism,
and learned variants (OPQ/PQ) go further and optimise the rotation. **We do not claim centring dominates
them.** We chose it because it is the minimal intervention that is *diagnosable*:

* it is a translation — no rotation matrix to store, no training, no change to the index;
* it preserves the geometry up to a constant shift (centred cosine = Pearson correlation);
* and, decisively, **the same statistic (`sign_info`) that detects the problem also decides whether applying
  the fix is worth it** (§8.3). A rotation has no equivalent triage signal in our measurements.

A head-to-head of centring vs a random/learned rotation, on the same tasks, is a natural next experiment;
**we did not run it**, and we do not infer an ordering.

## 9.3 What this says about the published applicability claim

The paper's four tiers are an **applicability** gradient (a description of achieved recall) and are read by
practitioners as a **competitiveness** gradient. Our competitor map (§8.4) shows the two differ:
before repair, three of the four tiers with competitor data were dominated by HNSW; after repair, one becomes
parity and one becomes a genuine intersection — but the only tier with a clear win remains the competitive one.
The practical statement we would put in a deployment guide is therefore narrower than the paper's:

> Use a BQ-native graph **when the embedding is competitive-tier (≥ ~88 % recall) and you need memory/QPS**;
> on collapse-tier data, first check `sign_info` — if it is 0.000, centre it, knowing that this buys 2–5 pp of
> absolute recall but usually *not* the win.

## 9.4 A methodological note we owe the reader

Both the paper's probe and our gate end up in the same place: **there is no single scalar that predicts
recall**. Our two attempts to build one failed (§7.4), and the two strongest correlates we found
(graph fidelity, `sign_info`) each have a counterexample that forbids a monotone formula. The deliverable is
therefore a **triage rule plus a necessary condition**, with its abstention made explicit — which is, we
suspect, the honest form of this kind of result, and the reason we report the failures alongside the wins.

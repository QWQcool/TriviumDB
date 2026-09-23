# 9. Discussion

## 9.1 The decision a deployer actually faces

Combining §5–§8 into one table — every quantity is computable **before** building an index, in seconds:

| `sign_info` | `‖μ‖` (headroom) | `probe_ef` (min of both metrics) | what to do | expected outcome |
|---|---|---|---|---|
| **= 0.000** (sign plane dead) | any | — | **rotate (§8.6)** — task-preserving *and* stronger; centre only if rotation is not an option | GIST 2.10→**60.22 %**, SIFT 15.77→**60.24 %** @ef=64 (centring: 39.74 / 30.64); GIST becomes **1.3× faster than HNSW** at 84 % recall |
| **≥ 0.6**, `‖μ‖ ≥ 0.3`, headroom > 5 pp | large | ≥ 50 % | centre as a cheap option | small-to-moderate gain (+0.3…+5.3 pp), never harmful in our 6-dataset set |
| **≥ 0.6** but headroom ≤ 5 pp | large | ≥ 50 % | **do not bother** | Cohere: −1.2 pp (neutral) — the tier is already at 95 % |
| any | any | **< 50 %** | **use a float32 index** | the code cannot rank; the fault is not fixable by translation |
| `sign_info` **= 1.000** but recall ≪ 50 % | ~0 | < 50 % | **do not build any graph index on this task** | index-agnostic collapse (Random-Sphere, Gaussian-960): HNSW also collapses (1.40 %) |

And one row the gate deliberately does **not** cover, because it needs a competitor curve:

| measured recall ≥ ~88 % on a competitive embedding | — | — | **QuIVer is the right index**: 4.6–5.0× at matched recall vs the best HNSW | the only tier where the paper's index actually wins (§5) |

## 9.2 Translation or rotation? The head-to-head

Both revive the sign plane; they differ in what *else* they change. We ran the comparison (§8.6, seeded random
rotation, zero storage, no training):

| tier | centring | rotation | reading |
|---|---|---|---|
| collapse (GIST / SIFT) | +37.6 / +14.9 pp @ef=64, but it **replaces the task** (centred-cosine) | **+58.1 / +44.5 pp**, GT untouched (99.87–100 % overlap) | **rotation wins** — stronger *and* it changes nothing but the code |
| usable (GloVe) | +3.3 pp alone; ceiling **93.32 %** with weighted navigation | −0.6 pp alone; **88.45 %** with weighted navigation (54.06 % @ef=64) | centring is better at the ceiling, rotation is better at low `ef`; a wash in practice |
| competitive (Cohere) | −1.2 pp (neutral) | **−4.8 pp** | centring, or leave it alone |

So the ordering is not "one dominates": **for a dead sign plane, rotate**; **for a live sign plane, do not
rotate**. Both choices are made by the same free statistic, so a deployer does not have to guess. What remains
open is the *learned*-transform direction (L12): we tested one seeded **random** rotation, not OPQ-style
learned ones, so 60.22 % / 60.24 % should be read as a **lower bound** on what a transform-side repair can do.

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

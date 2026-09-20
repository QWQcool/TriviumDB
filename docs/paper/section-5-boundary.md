# 5. Applicability Is Not Competitiveness

> **Draft** 2026-09-20 ｜ all competitor arms measured on the same machine, same data, same ground truth
> as the QuIVer arm they are compared against; every QuIVer point is a multi-arm run in one process.

## 5.1 The question a deployer actually asks

Table 11 and Figure 3 of the paper present a four-tier "applicability gradient" — *collapse* (< 15 % R@10),
*usable* (32–42 %), *moderate* (71–78 %), *competitive* (> 88 %) — keyed to **absolute Recall@10 at ef = 64**.
The tier names, however, invite a deployment reading ("moderate", "competitive") that absolute recall alone
cannot support. A deployer's question is:

> at the recall level where I need to operate, is this index faster than the alternatives — or is it at
> least able to reach that recall level at all?

We answer that question for each tier by measuring the same base/query set with four independent CPU
implementations.

## 5.2 Method: a criterion that does not depend on QPS

For each dataset we compare QuIVer's **ceiling** — R@10 at the largest search beam we sweep (ef_s = 1024) —
against each baseline's **lowest operating point** (ef = 64).

If the ceiling is *below* the baseline's lowest point, the two recall-vs-QPS curves **cannot intersect**: at
every recall the baseline reaches, it exists; at every recall QuIVer reaches, it is slower *or* less accurate.
The verdict is then independent of any throughput measurement, which matters because our machine cannot
exercise the AVX-512 path QuIVer is built around (§4.2). Competitors: hnswlib and FAISS-HNSW (graph), USearch
(graph), FAISS-IVF-Flat (inverted file), plus an exact scan.

## 5.3 Result: three of the four tiers are dominated

| Tier (paper) | Representative | QuIVer ceiling (ef_s = 1024) | Strongest baseline at ef = 64 | Curves intersect? |
|---|---|---|---|---|
| **competitive** (> 88 %) | Cohere-1M (768-d) | 99.78 % | hnswlib **99.84 %** @ 741 MT-QPS | **yes** — QuIVer **4.6–5.0×** faster at matched recall |
| **moderate** (71–78 %) | Wolt-CLIP-1M (512-d) | **86.81 %** | hnswlib **87.86 %** @ 19,606 MT-QPS | **no** — ceiling below the baseline's *lowest* point |
| **usable** (32–42 %) | GloVe-100 (100-d) | **71.69 %** | hnswlib **82.05 %** @ 36,047 MT-QPS | **no** |
| **collapse** (< 15 %) | SIFT-128 (128-d) | **47.21 %** | hnswlib **97.46 %** @ 45,118 MT-QPS | **no** |
| collapse | GIST-960 (960-d) | 4.38 % | *not measured* (expected dominated) | — |
| collapse | Random-Sphere (768-d) | 6.46 % | *not measured* (expected dominated) | — |

Only the top tier is winnable. In the other three measured tiers the gap is not a matter of tuning the search
beam: QuIVer cannot reach the recall region where the baselines start, and the deficit grows with dataset
difficulty (0.3 pp on Wolt-CLIP, 10.4 pp on GloVe-100, 50 pp on SIFT-128).

**Caveat on Wolt-CLIP.** That dataset is tie-limited: an exact float32 scan reproduces only **90.09 %** of the
shipped ground truth (see §5.4), so both methods are compressed against the same ceiling and the margin
between them is small in absolute terms. The domination verdict does not depend on it (86.81 % < 87.86 % is a
comparison of the same GT), but the *ranking* is what matters here, not the absolute distance from 100 %.

## 5.4 A protocol-level caveat worth carrying forward: the tie floor

The exact scan is a required control, and it is not always 100 %:

| dataset | exact scan R@10 | implication |
|---|---|---|
| Cohere-1M, GloVe-100, GloVe-100 (centered) | **100.00 %** | GT self-consistent |
| GIST-960 (centered) | 99.93 % | fine |
| SIFT-128 | 99.94 % | fine |
| **Wolt-CLIP-1M** | **90.09 %** | ~10 pp of the GT is tie-degenerate ⇒ recall values for this dataset must never be compared across datasets |

## 5.5 Implication

The deployable region of BQ-native graph indexing is **narrower than the published applicability gradient
suggests**: the paper's "moderate" and "usable" tiers describe *absolute* recall, while as a deployment
proposition they are dominated by a baseline that was already available.

This is the question §6–§8 take up: the tiers are not negotiated — the two lower ones are *mechanistically*
explainable (§6), and §7–§8 ask whether the boundary can be moved rather than merely described.

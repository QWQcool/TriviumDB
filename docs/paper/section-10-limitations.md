# 10. Limitations

All of the following are stated in the body text, not hidden in an appendix.

## 10.1 Platform and protocol

| # | Limitation | Mitigation / why the conclusion survives |
|---|---|---|
| **L1** | **Single machine, no AVX-512** (Intel i9-14900K; `Avx512F = false`) — the VPOPCNTDQ path QuIVer is designed around is never exercised | Recall-level conclusions are machine-independent. For speed we report the same-recall ratio, and note that our **absolute MT-QPS is already 1.1–2.4× the paper's** (32 vs 16 threads), i.e. we are *not* measuring on a weakened platform. We do not assert the direction in which the ratio would move on Zen4. |
| **L2** | **Metric deviation**: the published SIFT/GIST rows are *Euclidean*, while the repository's `prepare_all.py` normalises and recomputes GT by cosine, so our SIFT/GIST rows are cosine tasks | Disclosed in §4.2; our numbers are comparable to the paper's *pipeline*, not to the public Euclidean leaderboards. All our *comparisons* put both arms on the same task, so the deviation cancels. |
| **L3** | **Centring changes the similarity function**: every "after" number in §8.2–§8.4 is Recall@10 on the *centred-cosine* task, not an improvement on the original task | Stated at the head of §8. Centring is also known post-processing (all-but-the-top family); we claim triage + quantification, not novelty of the transform. **§8.6 covers this caveat by reporting a task-preserving alternative (seeded rotation), which on the collapse tier is both stronger and leaves the GT untouched (99.87–100 % overlap).** |
| **L4** | The separability column (~5 % calibre uncertainty from `cos_std`) appears in the gate's development tables | It is **not** used as a criterion in the final chain (§7.3), only reported for completeness. |

## 10.2 The reproduction has one unresolved row, one tie floor

| # | Limitation |
|---|---|
| **L5** | **RedCaps-1M (77.08 % vs 78.41 %)**: the sampling protocol (which 1 M slice; whether self-matches are excluded) is unstated in the paper, and the four plausible readings span **7.4 pp**. We report the reading that is closest to the paper and flag the row as partially reproduced. |
| **L6** | **Wolt-CLIP has a tie floor**: `faiss_exact` itself scores **90.09 %** on this 1 M set, so the achievable ceiling is ~90 %. The "intersecting curves" verdict in §8.4 is therefore partly caused by ties, and this dataset's recall must not be compared with other datasets' (Cohere / GloVe / SIFT have `faiss_exact` ≥ 99.9 %). |

## 10.3 Experimental scope

| # | Limitation |
|---|---|
| **L7** | **Single M (32), single `ef_c` (128), single build per arm.** Graph construction is concurrent and not bit-reproducible; we measured the spread over 3 independent builds on 5 representatives: **≤ 0.27 pp** at `ef=64`. Any graph-structure quantity (fidelity, CSR-derived) is a 256-node single-sample estimate. |
| **L8** | **Our own two single-scalar predictors failed** (§7.4). Reported as negative results; the delivered chain is triage + a necessary condition, and explicitly abstains on competitiveness. |
| **L9** | ~~Memory footprint not reproduced~~ → **reproduced (§11.3a)**: the paper's "≈4.7× less hot memory / < 1.3 GB per 1 M" is confirmed at **1:4.73** and **675 MiB per 1 M × 768** (hnswlib 3,193 MiB, FAISS-HNSW 3,189 MiB, IVF-Flat 2,949 MiB). Remaining caveat: we measured the **index bytes**, not peak RSS, and not the per-query hot-set growth. |
| **L10** | **MSMARCO-5M scalability (Table 12) is out of scope** — a 5 M-scale run is beyond this study's budget, so the paper's scaling claim is neither confirmed nor contradicted here. |
| **L11** | **The multi-signal (TSNG) path was not A/B-tested under the navigation-metric switch** (§8.3 covers the main path only). |
| **L12** | **Only a *random* (seeded) orthogonal transform was tested** (§8.6): we did not compare against learned rotations (OPQ-style) or other orthogonal transforms, and we do not claim rotation is optimal — only that it dominates centring on the collapse tier (60.22 % vs 39.74 % on GIST-960) while preserving the task. The row is therefore a *lower* bound on what a transform-side repair can achieve. |

## 10.4 Statistical conventions used throughout

* Recall values are single-run unless labelled; the G-det spread measured over 3 builds is ≤ 0.27 pp, so
  differences below ~0.3 pp are not interpreted.
* Probe values (§7) always come with their sample size and the query-subset spread (4–7 pp); a single-run
  probe value is never quoted alone.
* With the navigation switch **off**, frozen recall values reproduce within ≤ 0.17 pp
  (Cohere 97.52 / GIST-960 2.79 / GloVe-100 45.60), which is the regression guard for all `src/` work in §8.3.

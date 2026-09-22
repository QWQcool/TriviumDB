# 3. Methodology

## 3.1 Harness and equivalence

All index-side numbers come from two benches we added on top of the authors' released code:

* `benches/bench_t2_b2_partitioned.rs` — the measurement arm. It supports a **single-arm mode** (one index,
  recall + MT-QPS + build wall-clock) and an ablation mode (several arms in one process). Both modes go through
  the library's public search path; we verified equivalence against the repository's own evaluation entry point
  on shared configurations before using either. All arms of a comparison run in **one process** with the same
  build flags, so cross-arm differences are not confounded by rebuild or run-to-run variance.
* `benches/bench_t2_build_recon.rs` — exports the L0 adjacency as CSR for the graph-fidelity measurements (§6.3).

For every graph arm we additionally build the competitor indexes on the *same* base and query set in the same
machine (hnswlib, FAISS-HNSW, USearch, IVF-Flat) and record exact search (`faiss_exact`) as the ceiling probe.

## 3.2 Metrics

* **R@10** — Recall@10 against the **exact float32 top-10 of the same base and query set** (recomputed by us
  under the same similarity function as the arm under test). We report it at `ef_s ∈ {64, 128, 256, 512, 1024}`.
* **MT-QPS** — multi-threaded throughput at 32 threads (and a 16-thread parity run, matching the paper's
  thread count, to check that the same-recall speed ratio is thread-count independent).
* **Build wall-clock** — reported because it is one of the costs of the repair path.
* **`faiss_exact`** — used as a *tie floor* instrument, not as a baseline: if exact search cannot reach 100 %
  on a dataset (Wolt-CLIP: 90.09 %), the dataset has many exact ties and its recall must not be compared
  across datasets (L6).

## 3.3 Configuration

`m = 32`, `ef_c = 128`, `α = 1.2` (the paper's configuration throughout), `--features ablation`,
`RUSTFLAGS="-C target-cpu=native"`, release profile with LTO (inherited from `[profile.release]`), Windows 11,
Intel i9-14900K (24 C/32 T, 63.7 GB, **no AVX-512**).

## 3.4 Protocol deviations (disclosed, and why they do not affect comparisons)

1. **Similarity function.** The public SIFT-128/GIST-960 benchmarks are Euclidean; the repository's own
   `prepare_all.py` L2-normalises those vectors and **recomputes** ground truth by cosine. We follow the
   repository, so our SIFT/GIST rows are cosine tasks. Every *comparison* we report (tier × competitor,
   before/after repair, metric A/B) puts both sides on the **same** task, so the deviation cancels; only
   absolute cross-paper values are affected (L2).
2. **Platform.** No AVX-512, 32 threads. Recall-level conclusions are platform-independent; for speed we
   report same-recall ratios, and we note that our absolute MT-QPS already exceeds the paper's (1.1–2.4×),
   so we are not measuring on a weakened platform (L1).

## 3.5 Reproducibility and noise floor

Graph construction is concurrent, so the L0 edge set is not bit-reproducible. We built and measured five tier
representatives **three times each**; the spread of R@10 @ef=64 is **≤ 0.27 pp** (Cohere 0.13, GloVe-100 0.27,
SIFT-128 0.07, GIST-960 0.06, Wolt-CLIP 0.07). We therefore (a) treat differences below ~0.3 pp as
unresolved, and (b) mark any graph-structure quantity as a single-sample estimate. For the arms where a
`src/` change is evaluated (§8.3) we use **frozen recall values as a regression guard**: with the switch off,
the frozen values reproduce within ≤ 0.17 pp.

## 3.6 Index-free instruments

The gate (§7) and the probe analysis use quantities that need no index:

* `sign_info = mean_j H(p_j)` with `p_j` the fraction of negative coordinates in dimension `j`, `H` the binary
  entropy in bits (§6.2);
* `‖μ‖` — norm of the mean of the **normalised** training vectors (with the `≤ 1` sanity guard of §8.1);
* `probe10` — overlap of the code's top-10 with the exact float32 top-10 (the paper's literal instrument);
* `probe_ef` — take the code's top-128 candidates, re-rank them in float32, take the top-10, and measure
  overlap with the exact top-10 (the instrument that matches how a graph search actually behaves, §7.2c).
  Both probes are computed under **both** BQ metrics and we report the weaker one.

## 3.7 How a competitiveness verdict is reached

We avoid QPS-dependent arguments where possible. A tier is **dominated** if QuIVer's recall *ceiling*
(its best point over the whole `ef_s` sweep, including the pipeline of §8) lies **below** the competitor's
*lowest* operating point on the same task — in that case the curves cannot intersect, and no throughput
measurement can rescue the tier. Otherwise we report the same-recall throughput ratio and call the outcome
**parity** or **intersecting**.

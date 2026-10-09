# 11. Artifacts and Reproduction

> Every number in §4–§9 was produced by the code below on the machine described in §4.2, with
> `RUSTFLAGS="-C target-cpu=native"` and `--features ablation`. The **raw stdout logs** those runs produced
> are shipped in `results/logs/` (290 files, one README mapping prefixes to sections), so a clone of the
> artifact repository is sufficient to check any number quoted above.

## 11.1 Index-side harness (Rust bench, no library changes except the §8.3 switch)

| Artifact | Purpose |
|---|---|
| `benches/bench_t2_b2_partitioned.rs` | the main arm: partitioned BQ search, single-arm mode (recall + MT-QPS + build time), frozen-value guard (`T2_FROZEN_RECALL`) |
| `benches/bench_t2_build_recon.rs` | exports the L0 CSR for graph-fidelity measurement (§6.3) |
| `src/index/bq.rs`, `src/index/quiver.rs`, `src/tsng.rs` | the only library change in this work: `TRIVIUM_NAV_WEIGHTED` (default **off** ⇒ behaviour bit-identical; regression guard as above). Shipped as `patches/f1-nav-weighted.patch` for upstream review |

## 11.2 Data preparation and analysis scripts (Python; `src/` untouched)

| Script | Produces |
|---|---|
| `scripts/prepare_all.py` | the 12 benchmarking datasets (HF/ann-benchmarks sources), normalised + cosine GT |
| `scripts/research/gist960_collapse_prepare.py` | centred variants of any dataset (`--center <prefix>:<dim>`), with the `‖μ‖ ≤ 1` guard of §8.1 |
| `scripts/research/bq2_code_ceiling.py` | the analytic code-only ceiling; `verify_identities()` asserts analytic == bitwise against `src/index/bq.rs` |
| `scripts/research/deployability_gate.py` | the 22-arm gate table of §7.3 (`sign_info`, `‖μ‖`, `probe10`, `probe_ef`, verdict) |
| `scripts/research/compat_probe_scaling.py` | sample-size / query-subset sensitivity of the published probe (§7.2) |
| `scripts/research/graph_neighbor_quality.py` | `L0 ∩ {cos, weighted, cheap}_top64` (§6.3) |
| `scripts/research/baseline_competitors.py` | hnswlib / FAISS-HNSW / USearch / IVF-Flat / `faiss_exact` curves on the same task (§5, §8.4); `BL_SKIP` can drop an arm |
| `scripts/research/ivf_recall_diagnostic.py` | the wrapper/parameter audit of §5.6(b): does `nprobe` reach the wrapped base, what does `k_factor` actually do, where does the exact arm saturate |
| `scripts/research/gt_metric_consistency_probe.py` | the GT/vector metric check of §5.6(b): which exact search reproduces the shipped ground truth |
| `scripts/research/faiss_refine_mechanics_probe.py` | the synthetic mechanics probe of §5.6(b): refine metric, default `k_factor`, monotonicity on a self-consistent task |

## 11.3 Where each table comes from

| Paper table | Source of record |
|---|---|
| §4.3 (12 rows) | `results/t2/*/` per-dataset bench logs; frozen values in `docs/research/HANDOFF.md` |
| §5.3 (tier × competitor map) | `results/baseline/competitors_*.json` |
| §6.3 (graph fidelity) | `results/t2/gist960_collapse/graph_quality_*.json` (9 files; fields `overlap_cos_pct` / `overlap_w_pct` / `overlap_c_pct`) |
| §7.2–7.3 (gate + probe sensitivity) | `results/t2/deployability_gate.json`, `results/t2/p2_probe_scaling.json` |
| §8.2–8.3 (centre + navigation A/B) | `results/t2/gist960_collapse/*.json` |
| §8.4 (7-arm map) | `results/baseline/competitors_*c.json` |
| §8.6 (rotation) | derived `*r_*.f32/i32` sets (`gist960r` / `sift128r` / `glove100r` / `coherer`, produced by `gist960_collapse_prepare.py --rotate`, with the GT-invariance check) + `results/logs/p4a_*.log`; diagnosis in `docs/research/p4a-rotation-vs-centering.md` |
| §10-L9 (memory) | `results/t2/memory_footprint_cohere.json` (script `scripts/research/memory_index_footprint.py`; log `results/logs/p4b_memory_cohere.log`) |

### 11.3a Memory footprint (1 M × 768, M = 32)

| Implementation | index bytes | B/vector | vs QuIVer |
|---|---|---|---|
| **QuIVer (2-bit BQ)** | **675 MiB** | 707.8 | 1.00× (paper claims < 1.3 GB / 1 M: confirmed) |
| hnswlib | 3,193 MiB | 3,348.2 | **4.73×** (paper claims 4.7×: confirmed) |
| FAISS-HNSW | 3,189 MiB | 3,344.1 | 4.72× |
| FAISS IVF-Flat (nlist ≈ 4 k) | 2,949 MiB | 3,092.3 | 4.37× |
| **Bare IVF-PQ** (nlist = 1,024, m = 96, **no rerank**) | **92 MiB** | 96.5 | 0.14× — but its recall caps at **62.6 %** |
| **OPQ+IVF-PQ+Refine** (PQ codes + f32 rerank copy) | ≈ **3.16 GiB** (92 MiB + 3,072 MiB) | 3,312 | 4.8× — needed to reach 99.8 % |

⇒ The quantizer comparison sharpens the memory claim: **on PQ, cheap memory and high recall are mutually
exclusive** (bare PQ is 92 MiB at 62.6 %; the refined pipeline is 3.16 GiB at 99.8 %). Only the BQ-native
index gives 675 MiB **and** 99.8 % at the same time (§5.6 / §11.3b).

Measured as index bytes (bench-reported `Hot` for QuIVer; `save_index` size for hnswlib; `serialize_index`
length for FAISS), not peak RSS. The 2-bit code accounts for ~183 MiB of QuIVer's 675 MiB
(`0.25 B/dim × 768 × 1 M`); the rest is graph + bookkeeping, and the per-dimension increment across our
128/256/512/768-dim arms (522 → 553 → 614 → 675 MiB, ≈ 0.25 B/dim) matches 2 bits per dimension exactly.
The repair arms (`c` / `r`) keep the same footprint (720 MiB on `gist960` and `gist960r` alike).

## 11.4 One-command reproduction of the central claim

```bash
# 1. build
RUSTFLAGS="-C target-cpu=native" cargo build --release --features ablation

# 2. dataset + centred variant (GIST-960 as the example)
python scripts/prepare_all.py gist960
python scripts/research/gist960_collapse_prepare.py --center gist960:960

# 3. before / after (single arm, includes the frozen-value guard)
T2_PREFIX=gist960  T2_DIM=960 T2_FROZEN_RECALL=2.79 cargo bench --features ablation --bench bench_t2_b2_partitioned
T2_PREFIX=gist960c T2_DIM=960 cargo bench --features ablation --bench bench_t2_b2_partitioned

# 4. the gate (seconds, no index)
python scripts/research/deployability_gate.py
```

Expected: GIST-960 `R@10 @ef=64` ≈ **2.1 %** before and ≈ **39.7 %** after centring (the paper's row is 2.01 %);
the gate reports `sign_info = 0.000` for `gist960` and 0.981 for `gist960c`.

## 11.5 Upstream material (parallel track)

| Artifact | Content |
|---|---|
| `docs/research/upstream-issues.md` | the full audit of the upstream reports (Chinese), including the one we retracted ourselves |
| `docs/research/upstream-issue-draft.md` | the paste-ready **English** version of those reports (five issues; not yet filed) |
| `patches/f1-nav-weighted.patch` | the §8.3 switch as a reviewable patch (default off) |
| `docs/research/*.md` | the full audit trail: every claim, its evidence, and the conclusions we retracted (three of our own) |

## 11.6 Artifacts added after the first draft (second repair, quantizer arm, external validity)

All library changes remain **default-off and bit-identical when unset**; `src/` now carries two such switches
(`TRIVIUM_NAV_WEIGHTED` from §8.3, `TRIVIUM_SIGN_ROTATE` from §8.6), plus 2 new unit tests (152 library tests
pass with both off and on).

| § | Claim | Script | Product |
|---|---|---|---|
| 8.6 (rotation, data side) | rotation preserves the task (GT overlap 99.87–100 %) and beats centring on the collapse tier | `scripts/research/gist960_collapse_prepare.py --rotate/--rotate-center` | `*r_train.f32` / `*rc_train.f32` + `results/logs/p4a_*.log` |
| 8.6 (rotation, engine side) | the same repair as one env var on the original files/GT | `src/index/bq.rs` (`TRIVIUM_SIGN_ROTATE`) + `bench_t2_b2_partitioned` | `results/logs/p5_*.log` |
| 5.6 / 8.7 (quantizers) | PQ does not collapse where the 2-bit code does (six cells); QuIVer is 3.7× faster at ≥ 99 % on Cohere | `scripts/research/pq_matched_recall.py`, `benches/bench_baselines.py` (mode A/B) | `results/t2/pq_matched_recall_{cohere,sift128c,wolt_clipc}.json` (from `results/logs/p7_pq_*.log`), `results/baseline/competitors_cohere.json` |
| 5.6(b) (RaBitQ same-family + the normalisation trap) | the raw-vector inversion, the parameter audit (`k_factor`), the GT-metric check, and the corrected (normalised) pair | `scripts/research/bench_rabitq_refine.py` (`RA_CONTROL`, `RA_NORMALIZE`), `ivf_recall_diagnostic.py`, `gt_metric_consistency_probe.py`, `faiss_refine_mechanics_probe.py` | `results/t2/{rabitq_refine,ivfflat_control}_cohere.json` (raw-metric; kept as the trap record), `{rabitq_refine,ivfflat_control}_norm_cohere.json` (of record), `ivf_recall_diagnostic_cohere.json`, `gt_metric_consistency_cohere.json`, `faiss_refine_mechanics_probe.json`, `rabitq_refine_gist960c.json` |
| 6.4(ii) (second witness) | every competitor collapses on Gaussian-960 (hnswlib / FAISS-HNSW / USearch / IVF-Flat) | `scripts/research/baseline_competitors.py` (`BL_SKIP` optional) | `results/baseline/competitors_gauss960.json` |
| 8.6 (engine-side `rc`) | both switches reproduce the data-side `rc` arm on `gist960c` (80.12 / 97.13) | `bench_t2_b2_partitioned` + `TRIVIUM_SIGN_ROTATE` + `TRIVIUM_NAV_WEIGHTED` | `results/logs/p8_10_engine_rc.log` (retry product, after the queue's first attempt failed) |
| P8 queue | the ten-step unattended batch behind the rows above | `scripts/research/p8_queue.py`, `scripts/research/p8_collect_numbers.py` | `results/t2/p8_queue_summary.json` + `results/logs/p8_*.log` (step-10 retry note: `docs/research/p8-queue-report.md` §4-D5) |
| 6.5 (bit budget) | 2-bit allocation vs 4-bit ceiling on the four collapse datasets | `scripts/research/bit_budget_probe.py` | `results/t2/bit_budget_*.json` |
| 7.3 (prospective validation) | nav-metric rule held out on 6 arms: 6/6 | `scripts/research/nav_rule_validation.py` | `results/t2/nav_rule_validation.json` |
| 9.5 (external validity) | seven VIBE benchmarks; `coco_nomic` is a new catastrophe | `scripts/research/download_vibe_parallel.py`, `scripts/research/convert_hdf5_to_f32.py` | `results/logs/p6_vibe_*.log` + gate rows in `results/t2/deployability_gate.json` |
| 3.5 / 10.3 (noise floor) | 3 builds × 5 datasets ⇒ spread ≤ 0.25 pp | `bench_t2_b2_partitioned` re-runs | `results/logs/p7q_*_seed{1,2,3}.log`, `results/t2/p7_stagec_report.json` |
| 7.3 (probe K = 5) | K = 3 → K = 5 changes no verdict, drift ≤ 1.7 pp | `scripts/research/deployability_gate.py` (K = 5), `scripts/research/p7_k5_vs_k3.py` | `results/t2/deployability_gate.json`, `results/t2/p7_k5_vs_k3.json` |
| 11.3a (memory) | QuIVer 675 MiB vs refined PQ ≈ 3.16 GiB vs hnswlib 3.19 GiB | `scripts/research/memory_footprint.py` | `results/t2/memory_footprint_cohere.json` |

Reproducing §8.6's engine-side switch end to end:

```bash
TRIVIUM_SIGN_ROTATE=20260923 T2_PREFIX=sift128 T2_DIM=128 \
  cargo bench --features ablation --bench bench_t2_b2_partitioned   # 15.77 % -> 62.66 % @ef=64
```


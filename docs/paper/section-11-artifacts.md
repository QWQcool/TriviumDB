# 11. Artifacts and Reproduction

> Every number in §4–§9 was produced by the code below on the machine described in §4.2, with
> `RUSTFLAGS="-C target-cpu=native"` and `--features ablation`.

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
| `scripts/research/baseline_competitors.py` | hnswlib / FAISS-HNSW / USearch / IVF-Flat / `faiss_exact` curves on the same task (§5, §8.4) |

## 11.3 Where each table comes from

| Paper table | Source of record |
|---|---|
| §4.3 (12 rows) | `results/t2/*/` per-dataset bench logs; frozen values in `docs/research/HANDOFF.md` |
| §5.3 (tier × competitor map) | `results/baseline/competitors_*.json` |
| §6.3 (graph fidelity) | `results/t2/gist960_collapse/graph_quality_*.json`（9 个文件，字段 `overlap_cos_pct` / `overlap_w_pct` / `overlap_c_pct`） |
| §7.2–7.3 (gate + probe sensitivity) | `results/t2/deployability_gate.json`, `results/t2/p2_probe_scaling.json` |
| §8.2–8.3 (centre + navigation A/B) | `results/t2/gist960_collapse/*.json` |
| §8.4 (7-arm map) | `results/baseline/competitors_*c.json` |
| §8.6 (rotation) | `*r_*.f32/i32` 派生集（`gist960r`/`sift128r`/`glove100r`/`coherer`，由 `gist960_collapse_prepare.py --rotate` 生成，含 GT 不变性校验）+ `.tmp/p4a_*.log`；诊断见 `docs/research/p4a-rotation-vs-centering.md` |

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
| `docs/research/upstream-issues.md` | four paste-ready issues: RedCaps sampling protocol, the L0 navigation-metric mismatch, the probe's specification gaps, and two defaults/doc fixes |
| `patches/f1-nav-weighted.patch` | the §8.3 switch as a reviewable patch (default off) |
| `docs/research/*.md` | the full audit trail: every claim, its evidence, and the conclusions we retracted (three of our own) |

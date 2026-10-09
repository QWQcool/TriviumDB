# Raw logs cited by the paper

These 277 files are the **raw stdout logs** that `docs/paper/section-*.md` cites (§11.3, §11.6). They were
copied here from the local `.tmp/` scratch directory — which is `.gitignore`d (`*.tmp`) and therefore
*not* available to anyone who clones this repository — so that **every number in the paper resolves to a
file inside this repository**.

| prefix | what it is | paper section |
|---|---|---|
| `p4a_*` | rotation vs centring arms (data-side) | §8.6 |
| `p4b_memory_*` | memory-footprint measurement | §10-L9, §11.3a |
| `p5_*` | engine-side rotation switch | §8.6 |
| `p6_vibe_*` | VIBE extension rows | §9.5 |
| `p7_pq_*` | quantizer tier-jump runs (PQ/OPQ) | §5.6(a), §8.7 |
| `p7q_*_seed{1,2,3}` | 3-build noise floor | §3.5, §10.3 |
| `p8_*` | the ten-step P8 queue (+ its step-10 retry) | §5.6(b), §6.4, §8.6; write-up in `docs/research/p8-queue-report.md` |
| `bench_*`, `f1_*`, `u19_*`, `b2_*` … | earlier rounds kept for completeness | various |

The scripts that produced these logs are listed in §11.2 / §11.6 of the paper; most can be re-run
end-to-end after the datasets are prepared (see `docs/research/env-recovery.md`).

Not shipped here, by design: the ~2.8 GB of regenerable intermediates that live in the local `.tmp/`
(`l0_csr_*.bin` from `benches/bench_t2_build_recon.rs`) and the ~112 GB of dataset vectors
(`*.f32` / `*.i32`, `.gitignore`d; regenerate with `scripts/prepare_all.py` and the download scripts).

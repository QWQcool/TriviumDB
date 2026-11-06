# TriviumDB v0.9.0 ANN replay: evidence and unresolved gate

This package preserves the complete available records for the independent ANN replay started on 2026-11-05 at source commit `7edf8ceacd85cd71944a3471ac05df377995a172`. **The overall replay did not pass.** Its `selection.json` has `cohere-1m/triviumdb` unresolved: all three complete attempts exceeded the protocol's QPS variability threshold at one or more search settings. These failed attempts remain in `attempts/`; there is no approved complete comparison for that group. Other groups passing their individual checks does not make the overall replay a pass.

## What is preserved

- `attempts/` contains each group attempt, individual runs, CPU/memory admission checks, raw measurements, and supervision records, including all failed attempts.
- `accepted/` contains the artifacts selected by the recorded policy for groups that passed. The policy selects the first complete passing attempt in chronological order, with a fixed maximum number of attempts. **Selection based on observed variability can introduce selection bias**; consult every attempt and do not present only the chosen results as the entire experiment.
- `selection.json` and `selection.jsonl` record decisions and their supporting paths. `manifest.json` records settings, software fingerprints, timing boundaries, and constraints. `scripts/` preserves byte-identical Python runner snapshots with a `.snapshot` suffix. They are archival evidence and need their original filenames and workspace layout if reproduced.
- `input_hashes_before.json`, `input_hashes_after_preflight.json`, and `input_hashes_after.json` bind the recorded train, tiled query, and ground-truth inputs to before preflight, after preflight, and after measurement. Before/after content hashes and recorded modification times agree. These are boundary checks: changes made and reverted between snapshots are not excluded. `groundtruth-check.log` is a path-redacted copy; it reports the sampled preflight, not an exhaustive check of every query.

Each group attempt uses three independently built indexes per engine; each index has one complete tiled query batch at each recorded ef. The baseline NPZ files retain per-query returned labels and hit counts; the original TriviumDB harness retains batch-level QPS and recall only, not individual return IDs or per-query latencies. The query set was tiled; its length is not a count of independent queries. These distinctions are material to any claim of raw-query completeness.

The timing boundaries also differ: the TriviumDB benchmark's measured search includes ground-truth hit counting, while the baseline QPS timing excludes recall calculation. TriviumDB `hot_bytes` and baseline formula estimates are not the same memory metric and cannot support an exact memory-savings multiple. Interpolation at target recall does not authorize extrapolation for a dataset that did not reach the target.

## Related test results

This ANN replay is separate from the [P1–P6 replay and review](../replay-review-20261105/README.md). That package records failures of the unmodified P1 assertion, the release fault-suite compilation, and the RSS soak check (including a separate diagnostic rerun). Patched P1 and debug fault-suite results are separately qualified there. The soak findings are working-set observations and do not by themselves establish a memory-leak root cause. None of these failures may be described as an overall passed test suite.

## Privacy, exact bytes, and hashes

[FILE-MANIFEST.json](FILE-MANIFEST.json) records SHA-256 of the private source bytes and the published bytes for every copied file and identifies path-redacted copies. Personal profile and workspace absolute paths were replaced with placeholders in text copies; all benchmark values, failed attempts, and binary NPZ files remain present. Original private files remain untouched on the benchmark host. The package does not reproduce datasets or private unredacted logs.

Hashes already embedded in original experiment metadata—including `selection.json`, `groundtruth-check.meta.json`, `groundtruth-check.identity.json`, and the path-dependent library fingerprint—refer to original source bytes or original path strings. Where a referenced text file or path was redacted, compare its original hash and published hash using FILE-MANIFEST instead of expecting the original digest to match the public copy. Unredacted files, the NPZ files and exact copied scripts have identical source and published hashes. The `.gitattributes` file prevents Git newline conversion from changing evidence bytes. FILE-MANIFEST excludes itself, this README, and `.gitattributes`.

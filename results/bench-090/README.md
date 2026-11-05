# TriviumDB 0.9.0 ANN benchmark evidence

This directory contains the available evidence for a single-machine benchmark of TriviumDB `v0.9.0` at commit `7edf8ce`, compared with hnswlib and FAISS-HNSW. The results describe these datasets, settings and runs; they are not a general ranking of the engines. Publishing the evidence makes it available for inspection, not independently reproduced or validated.

## What is included

- [`official/summary.json`](official/summary.json) contains the combined curves, interpolated QPS, build times and reported memory values. [`official/summary.md`](official/summary.md) and [`official/summary.csv`](official/summary.csv) present the same aggregate results in readable and tabular form.
- [`official/raw/`](official/raw/) contains the available benchmark JSON and metadata. TriviumDB has individual run files; baseline files contain aggregated query measurements, not separately preserved samples for each query repetition.
- [`REPORT.md`](REPORT.md) is the original report, retained as a historical record. Its earlier publication claims and blanket shorthand are not the authority for release copy; use the measurement qualifications in this README and the source data instead.
- [`scripts/bench090/PROTOCOL.md`](../../scripts/bench090/PROTOCOL.md) records the intended method and known limitations. [`official/RERUNS.md`](official/RERUNS.md) records the subsequent handling of other benchmark and test failures.

The original local source files are retained. Original execution logs are not included in this public evidence package. In particular, an independent ground-truth check log and the individual baseline query samples have not been located in the available evidence, so readers cannot verify those checks or baseline run-to-run variability from this package alone. Dataset files are not included. A later [sampled ground-truth recheck](verification/ground-truth-recheck-2026-11-05.redacted.txt) passed for all four datasets, using 16 queries per dataset. This is a path-redacted derived record of a new check; it does not establish the identity of files used in the historical runs.

## ANN comparison

The three reported embedding datasets contain `384d / 1M`, `768d / 1M` and `1536d / 990K` vectors. The recorded machine was an Intel i9-14900K with 64 GB RAM on Windows 11. All engines used 16 threads; HNSW used `M=32`, `ef_construction=128`, and TriviumDB used `m=32`, `ef_c=128`. The metric is cosine recall at 10.

Query throughput at `R@10 = 90%` is estimated by linear interpolation along the recall axis using the measured curve; it is not the peak QPS at an arbitrarily selected search parameter. Queries were repeated three times and the per-point median used for the reported curve. TriviumDB rebuilt its index for each of its three runs; each hnswlib and FAISS baseline built its index once and repeated queries on that index. Consequently, baseline build times are single-build observations, not three-build medians.

The query workload was tiled to 20,000 entries to lengthen the timing window; this does not mean 20,000 unique queries. The historical report describes a shared machine with approximately 19% background CPU load. The retained evidence does not establish whether the protocol's pre-run CPU-load condition was met for every run. These measurements therefore should not be represented as isolated-machine results.

The TriviumDB memory figure is `hot_bytes`, excluding OS page cache and mmap residency; the baseline figures are formula estimates. These measure different things and support an order-of-magnitude comparison only, not a precise claim that one engine uses a particular multiple less total memory.

The summary also records a lower-dimensional boundary dataset for which TriviumDB did not reach the target recall in the tested search range. It must not be presented as an advantage or extrapolated to the target recall.

## Other test results

The pipeline and fault-test records are separate from the ANN comparison. As described in [`official/RERUNS.md`](official/RERUNS.md), the pipeline rerun used a modified assertion in an isolated worktree to compare result content while allowing provenance differences. The fault-suite rerun used a debug build and excluded `fault_allocator` after a release/LTO compiler crash. Those results do not establish that the original unmodified pipeline assertion or the excluded allocator test passed.

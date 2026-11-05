# TriviumDB v0.9.0 P1–P6 replay: evidence and outstanding failures

This directory preserves a **review package**, not a passed release gate or a new ANN benchmark. The tested source revision was `7edf8ceacd85cd71944a3471ac05df377995a172`. The replay kept each command, status, pre-start resource observations and available logs or reports in [p1p6/run.json](p1p6/run.json). Pre-start checks do not demonstrate uninterrupted isolation throughout each run.

## Results requiring attention

- **P1 original assertion: failed.** The unmodified benchmark exited with an assertion failure at both dataset sizes; see [20K log](p1p6/logs/p1_clean_20k.log) and [200K log](p1p6/logs/p1_clean_200k.log). The independently repeated runs with the [historical patch](p1p6/pipeline-gate-historical.patch) exited successfully and produced [20K](p1p6/reports/p1_patched_20k.json) and [200K](p1p6/reports/p1_patched_200k.json) reports, each listing 16 passed combinations. The patch compares hashes of selected row fields (`id`, similarity and property score), not complete `NodeSet` equality. Its success does not make the original assertion pass or establish equality of every field.
- **Release fault suite: failed to compile.** Rustc crashed with an access violation while compiling `fault_io` in the [release/LTO run](p1p6/logs/p4_fault_release_all.log). It does not establish a test pass or the cause of the compiler crash.
- **Debug fault checks: limited passes.** The [debug suite without allocator](p1p6/logs/p4_fault_debug_without_allocator.log) reports 102 passed and one ignored across the five parent test binaries. The [separate allocator debug run](allocator-debug-extra/fault_allocator_debug.log) reports five passed; its child-process summary is nested in that log and must not be added as another test binary. These debug observations do not replace the failed release suite.
- **Release soak: failed and failed again on diagnostic replay.** The [suite run](p1p6/logs/p5_soak.log) reports one failure and one pass: the five-minute RSS check failed, while the file-size check passed. Its displayed initial/final values were 14/52 MiB. The separately instrumented [single-test diagnostic](soak-diagnosis/test.log) failed the same check with displayed values 13/51 MiB. Displayed values are integer-truncated MiB; the assertion compares raw bytes. Both failure records are retained.
- **RSS diagnosis is not a root-cause finding.** Windows `WorkingSet64` is a working-set observation, not a direct leak measurement. The [sample stream](soak-diagnosis/samples.ndjson) also records private bytes and process identity. Its extra PowerShell observer incurs overhead and changes the observation conditions. The executed collector was not snapshotted or hashed and its local file changed after the process began; see [provenance note](soak-diagnosis/PROVENANCE.md). These observations are diagnostic evidence, not a byte-identically reproducible collector run.

P2, P3 and P6 result and command statuses are in [run.json](p1p6/run.json). P1/P3/query-parallel measurements are single benchmark observations unless the individual report documents otherwise; P2 Criterion output consists of per-case statistical summaries, not independent complete reruns. The concurrency run reports 51 passed. Consult individual logs rather than treating an exit code as a substitute for executed-test counts.

## Files and redaction

- [P1–P6 log and result directory](p1p6/): the serial replay's manifest, all suite logs, newly produced reports, and the historical patch.
- [Separate allocator check](allocator-debug-extra/): its log, pre-start resource observation, and result metadata.
- [Soak diagnosis](soak-diagnosis/): its test log, time series, manifest and provenance note.
- [File manifest](FILE-MANIFEST.json): source and published SHA-256 hashes and whether each file was redacted.

Local usernames and absolute machine paths are replaced with placeholders in the copies; remaining text and numerical measurements are preserved. These are redacted copies, while the original local files remain untouched. Temporary database files from the test runs are not included. File hashes in the manifest cover the individual evidence files, not this README or the manifest itself. No claim is made that this package independently validates the full database or proves the cause of the observed failures.

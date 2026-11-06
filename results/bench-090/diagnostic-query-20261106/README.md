# Query-window variability investigation (diagnostic only)

This package records a **diagnostic investigation**, not a formal benchmark rerun, an accepted result, or evidence that a release gate passed. The full replay's unresolved group and broader testing failures are documented in the [ANN replay evidence](../replay-full-v3-20261105/README.md) and [test review](../replay-review-20261105/README.md). Nothing here changes their status.

## Design and records

The [preregistered design](preregistration.json) uses the sequence **A, B, B, A, A, B**. Each of the six processes independently built one index: three independent indexes for condition A and three for condition B. For each index, the recorded ef sequence is repeated on that index; the first occurrence of each ef is identified as warmup and the records include analyses with and without it.

Condition A uses a 20,000-entry tiled query set. Condition B uses 80,000 entries formed by four byte-exact repetitions of A; it is not 80,000 independent queries. The large locally generated query and ground-truth files are intentionally not published because their distribution rights have not been established. Their names, sizes, and hashes are retained in [diagnostic_inputs.json](diagnostic_inputs.json), [diagnostic_inputs_after.json](diagnostic_inputs_after.json), and the per-run metadata. Without the actual input files, a third party cannot directly re-run or independently hash-check them from this package alone.

Each `run-*` directory retains the original benchmark JSON, configuration, pre-start resource gate, process and supervision records, per-run review, stdout events and log, telemetry, and before/after sensor data. [summary.json](summary.json) preserves the comparisons. These are observed values under the specified conditions; they are not a claim of performance for a different workload or system.

## Interpretive limits

A and B did **not** query the same built graph: each process built its own index. Index construction, run order, query-window length, cache state, temperature, and other environmental effects can therefore be confounded. The design cannot establish that any one of these caused the observed variability; ABBAAB is not a substitute for matched repeated measurements on the same index.

Rust's stored output supplies QPS and per-query-average latency, not a separately stored raw batch elapsed time. The elapsed values in per-run reviews are **estimates derived as query count divided by QPS**, not independently captured raw timings. The original benchmark reports batch aggregates rather than per-query return IDs or per-query latency records.

The optional ACPI thermal-zone readings are raw and unvalidated; they **must not be interpreted as trustworthy CPU package temperatures**. Clock and frequency counters may not represent instantaneous core frequency. One-second total-CPU observations include the benchmark itself, and stdout event arrivals can be buffered; they cannot independently reconstruct precise batch boundaries or background-only load. Monitoring and sampling introduce observation overhead: the recorded wall duration includes intentional sampling waits, and observer CPU includes all Python threads rather than isolating the monitor. These conditions should be considered when interpreting the diagnostic.

The snapshot in [script_snapshot.py.snapshot](script_snapshot.py.snapshot) is a byte-exact copy renamed with `.snapshot` for archival; [code_identity.json](code_identity.json) refers to that published filename and retains the original script hash. The snapshot was taken after Python imported the source, so exact identity with the bytes already loaded at process startup cannot be independently established. It is archival evidence, not an executable entry point.

## File integrity and privacy

[FILE-MANIFEST.json](FILE-MANIFEST.json) lists source and published SHA-256 hashes, path-only redactions, the archival filename change, and excluded generated inputs. Local workspace paths in text copies are replaced with placeholders. [code_identity.json](code_identity.json) has one additional disclosed transformation: its script snapshot filename points to the renamed published copy. No benchmark numbers are intentionally changed. Original local files are retained untouched.

Hashes embedded in original records refer to original source bytes or paths; where a referenced text file was redacted, compare the source and published hashes in FILE-MANIFEST instead of treating the two byte streams as identical. `.gitattributes` disables Git newline conversion so the published bytes remain stable. The manifest excludes itself, this README, and `.gitattributes` from its own hashes.

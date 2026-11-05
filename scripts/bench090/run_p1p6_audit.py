"""Isolated, serial P1-P6 rerun. Old reports and the benchmark worktree stay intact.

Run --list to inspect; --output names a NEW evidence directory. All performance
numbers are provisional until independently checked against the protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cargo_test_audit import parse_cargo_test_summaries

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / ".bench090"
COMMIT = "7edf8ceacd85cd71944a3471ac05df377995a172"
CARGO = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo.exe")

parser = argparse.ArgumentParser()
parser.add_argument("--list", action="store_true", help="show commands without writing or running")
parser.add_argument("--output", help="new evidence directory under results/bench-090")
parser.add_argument("--sample-seconds", type=int, default=5)
parser.add_argument("--poll-seconds", type=int, default=30)
args = parser.parse_args()

steps = [
    {"id": "p1_clean_20k", "cmd": [CARGO, "bench", "--locked", "--bench", "bench_pipeline_gate"], "env": {"TDB_PIPELINE_GATE_NODES": "20000"}, "report": "pipeline-gate.json", "timeout": 2400},
    {"id": "p1_clean_200k", "cmd": [CARGO, "bench", "--locked", "--bench", "bench_pipeline_gate"], "env": {"TDB_PIPELINE_GATE_NODES": "200000"}, "report": "pipeline-gate.json", "timeout": 5400},
    {"id": "p2_indexes_leiden", "cmd": [CARGO, "bench", "--locked", "--bench", "bench_indexes_and_leiden"], "timeout": 2400},
    {"id": "p3_deep_traversal", "cmd": [CARGO, "bench", "--locked", "--bench", "bench_deep_traversal"], "report": "deep-traversal-1000000.json", "timeout": 5400},
    {"id": "p3_graph_parallel", "cmd": [CARGO, "bench", "--locked", "--bench", "bench_graph_parallel"], "report": "graph-parallel.json", "timeout": 3600},
    {"id": "p6_query_parallel", "cmd": [CARGO, "bench", "--locked", "--bench", "bench_query_parallel"], "report": "query-parallel-200000-768.json", "timeout": 3600},
    {"id": "p4_fault_release_all", "cmd": [CARGO, "test", "--release", "--features", "test-hooks", "--test", "fault_io", "--test", "fault_power", "--test", "fault_crash", "--test", "fault_allocator", "--test", "fault_lock", "--test", "fault_hardware", "--", "--test-threads=1"], "timeout": 7200},
    {"id": "p4_fault_debug_without_allocator", "cmd": [CARGO, "test", "--features", "test-hooks", "--test", "fault_io", "--test", "fault_power", "--test", "fault_crash", "--test", "fault_lock", "--test", "fault_hardware", "--", "--test-threads=1"], "timeout": 7200},
    {"id": "p5_soak", "cmd": [CARGO, "test", "--release", "--test", "long_running", "soak", "--", "--ignored", "--nocapture", "--test-threads=1"], "timeout": 3600},
    {"id": "p6_concurrency", "cmd": [CARGO, "test", "--release", "--features", "test-hooks", "--test", "concurrency", "--", "--test-threads=1"], "timeout": 3600},
    {"id": "p1_patched_20k", "patched": True, "cmd": [CARGO, "bench", "--locked", "--bench", "bench_pipeline_gate"], "env": {"TDB_PIPELINE_GATE_NODES": "20000"}, "report": "pipeline-gate.json", "timeout": 2400},
    {"id": "p1_patched_200k", "patched": True, "cmd": [CARGO, "bench", "--locked", "--bench", "bench_pipeline_gate"], "env": {"TDB_PIPELINE_GATE_NODES": "200000"}, "report": "pipeline-gate.json", "timeout": 5400},
]

if args.list:
    print(json.dumps(steps, ensure_ascii=False, indent=2))
    raise SystemExit(0)
if not args.output:
    parser.error("--output is required unless --list is specified")
if args.sample_seconds < 2 or args.poll_seconds < 1:
    parser.error("sample interval must be >=2 seconds and polling >=1 second")

out_root = (ROOT / "results" / "bench-090").resolve()
out = Path(args.output).resolve()
if not out.is_relative_to(out_root) or out == out_root or out.exists():
    parser.error("--output must be a new directory below results/bench-090")
if not Path(CARGO).is_file():
    raise SystemExit(f"cargo not found: {CARGO}")

revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ORIGINAL, capture_output=True, check=True, text=True).stdout.strip()
if revision != COMMIT:
    raise SystemExit("existing benchmark worktree has an unexpected commit; stop")
patch = subprocess.run(["git", "diff", "--binary", "HEAD", "--", "benches/bench_pipeline_gate.rs"], cwd=ORIGINAL, capture_output=True, check=True).stdout
if not patch:
    raise SystemExit("historical pipeline patch is missing; stop without running")

out.mkdir(parents=True)
(out / "logs").mkdir()
(out / "reports").mkdir()
(out / "pipeline-gate-historical.patch").write_bytes(patch)
unique = uuid.uuid4().hex[:12]
worktree = ROOT.parent / ("TriviumDB-p1p6-" + unique)
log = {"state": "preparing", "source_commit": COMMIT, "worktree": str(worktree), "historical_patch": "pipeline-gate-historical.patch", "historical_patch_sha256": hashlib.sha256(patch).hexdigest(), "started_at": datetime.now(timezone.utc).isoformat(), "steps": [], "host": {"platform": platform.platform(), "cpu": platform.processor(), "python": sys.version}}
log["measurement_limitations"] = [
    "P1, P3 and query-parallel are single benchmark observations unless the individual report explicitly documents repeats; they are not three independent reruns.",
    "P2 uses Criterion's per-case statistical estimates; its console output is a summary, not a complete independent-run or per-query sample record.",
    "Ignored and filtered tests are recorded and do not count as executed; a passing selected suite is not evidence that excluded suites passed.",
]
for tool, command in (("cargo", [CARGO, "--version"]), ("rustc", [shutil.which("rustc") or str(Path(CARGO).with_name("rustc.exe")), "--version", "--verbose"])):
    try:
        version = subprocess.run(command, capture_output=True, text=True)
        log["host"][tool] = {"exit_code": version.returncode, "version": version.stdout.strip(), "error": version.stderr.strip()}
    except OSError as exc:
        log["host"][tool] = {"exit_code": None, "version": None, "error": str(exc)}
(out / "run.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
create = subprocess.run(["git", "worktree", "add", "--detach", str(worktree), COMMIT], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(out / "worktree-setup.log").write_bytes(create.stdout)
if create.returncode:
    log["state"] = "worktree-setup-failed"
    (out / "run.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(create.returncode)

environment = os.environ.copy()
environment["PYTHONIOENCODING"] = "utf-8"
# Reuse the installed release toolchain and cache; report files remain relative
# to the new worktree, never the original worktree's target/bench-reports.
environment["CARGO_TARGET_DIR"] = str(ORIGINAL / "target")
log["state"] = "running"
log["environment"] = {name: environment.get(name) for name in ("CARGO_TARGET_DIR", "RAYON_NUM_THREADS", "TRIVIUM_MT_THREADS", "RUSTFLAGS", "RUSTUP_TOOLCHAIN")}
patch_applied = False
for step in steps:
    if step.get("patched") and not patch_applied:
        check = subprocess.run(["git", "apply", "--check", str(out / "pipeline-gate-historical.patch")], cwd=worktree, capture_output=True)
        if check.returncode:
            log["state"] = "patch-check-failed"
            (out / "patch-check.log").write_bytes(check.stdout + check.stderr)
            break
        applied = subprocess.run(["git", "apply", str(out / "pipeline-gate-historical.patch")], cwd=worktree, capture_output=True)
        if applied.returncode:
            log["state"] = "patch-apply-failed"
            (out / "patch-apply.log").write_bytes(applied.stdout + applied.stderr)
            break
        patch_applied = True

    record = {"id": step["id"], "command": step["cmd"], "cwd": str(worktree), "env_overrides": step.get("env", {}), "patched": bool(step.get("patched")), "gate_samples": []}
    log["steps"].append(record)
    while True:
        ps = ("$ErrorActionPreference='Stop'; "
              f"$x=@((Get-Counter '\\Processor(_Total)\\% Processor Time' -SampleInterval 1 -MaxSamples {args.sample_seconds}).CounterSamples | ForEach-Object {{$_.CookedValue}}); "
              "$m=Get-CimInstance Win32_OperatingSystem; "
              "@{cpu_percent=$x; available_memory_bytes=[int64]$m.FreePhysicalMemory*1024; timestamp_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Compress")
        sampled = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        if sampled.returncode:
            record["status"] = "preflight-error"
            record["preflight_error"] = sampled.stderr
            log["state"] = "preflight-error"
            break
        try:
            gate = json.loads(sampled.stdout)
            gate["passed"] = bool(gate["cpu_percent"]) and all(0 <= x < 15 for x in gate["cpu_percent"]) and gate["available_memory_bytes"] >= 8 * (1 << 30)
        except (ValueError, KeyError, TypeError) as exc:
            record["status"] = "preflight-error"
            record["preflight_error"] = str(exc)
            log["state"] = "preflight-error"
            break
        record["gate_samples"].append(gate)
        (out / "run.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{step['id']}] CPU={gate['cpu_percent']} free={gate['available_memory_bytes']} gate={gate['passed']}", flush=True)
        if gate["passed"]:
            break
        time.sleep(args.poll_seconds)
    if log["state"] == "preflight-error":
        break

    step_env = environment.copy()
    step_env.update(step.get("env", {}))
    report = worktree / "target" / "bench-reports" / step.get("report", "__no_report__")
    before = report.stat().st_mtime_ns if report.exists() else None
    record["started_at"] = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    with (out / "logs" / (step["id"] + ".log")).open("wb") as fh:
        try:
            result = subprocess.run(step["cmd"], cwd=worktree, env=step_env, stdout=fh, stderr=subprocess.STDOUT, timeout=step["timeout"])
            record["exit_code"] = result.returncode
            record["status"] = "ok" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            record["exit_code"] = None
            record["status"] = "timeout"
    record["elapsed_seconds"] = time.monotonic() - t0
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    if len(step["cmd"]) >= 2 and step["cmd"][1] == "test":
        expected = [step["cmd"][i + 1] for i, item in enumerate(step["cmd"][:-1]) if item == "--test"]
        raw_test_log = (out / "logs" / (step["id"] + ".log")).read_text(encoding="utf-8", errors="replace")
        record["test_audit"] = parse_cargo_test_summaries(raw_test_log, expected)
        if record["status"] == "ok" and not record["test_audit"]["valid"]:
            record["status"] = "invalid-test-summary"
    if step.get("report") and record["status"] == "ok":
        if not report.is_file() or report.stat().st_mtime_ns == before:
            record["status"] = "missing-fresh-report"
        else:
            dest = out / "reports" / (step["id"] + ".json")
            shutil.copy2(report, dest)
            record["report"] = str(dest.relative_to(out))
    (out / "run.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{step['id']}] {record['status']} ({record['elapsed_seconds']:.1f}s)", flush=True)

if log["state"] == "running":
    log["state"] = "finished"
log["finished_at"] = datetime.now(timezone.utc).isoformat()
(out / "run.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
if log["state"] != "finished" or any(s.get("status") != "ok" for s in log["steps"]):
    raise SystemExit(1)

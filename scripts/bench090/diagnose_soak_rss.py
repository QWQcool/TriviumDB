"""Separately rerun one release soak test and sample the Windows process tree.

Never edits the source or an existing run. This is a diagnostic, not proof of a
root cause. Use --list for a no-write, no-test preview.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from cargo_test_audit import parse_cargo_test_summaries

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REV = "7edf8ceacd85cd71944a3471ac05df377995a172"
CARGO = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo.exe")
TEST = "soak::SOAK_01_连续运行5分钟_RSS增长有界"
COMMAND = [CARGO, "test", "--locked", "--release", "--test", "long_running", TEST, "--", "--ignored", "--exact", "--nocapture", "--test-threads=1"]
WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

parser = argparse.ArgumentParser()
parser.add_argument("--list", action="store_true", help="preview without side effects")
parser.add_argument("--worktree", help="existing worktree at the recorded benchmark revision")
parser.add_argument("--output", help="new evidence directory under results/bench-090")
parser.add_argument("--interval", type=float, default=10, help="target seconds between samples, 5–10")
parser.add_argument("--poll-seconds", type=float, default=30, help="wait between preflight retries")
args = parser.parse_args()
if args.list:
    print(json.dumps({"command": COMMAND, "cpu_gate": "5 successive samples <15%", "min_available_bytes": 8 * (1 << 30), "sampling_interval_seconds": args.interval, "metrics": ["process tree", "WorkingSet64", "PrivateMemorySize64", "process CPU", "system CPU", "available memory", "sampling overhead"]}, ensure_ascii=False, indent=2))
    raise SystemExit(0)
if not args.output or not args.worktree:
    parser.error("--worktree and --output are required unless --list is specified")
if not 5 <= args.interval <= 10 or args.poll_seconds <= 0:
    parser.error("--interval must be between 5 and 10 seconds; polling must be positive")
if sys.platform != "win32":
    raise SystemExit("this collector requires Windows")

worktree = Path(args.worktree).resolve()
base = (ROOT / "results" / "bench-090").resolve()
out = Path(args.output).resolve()
if not out.is_relative_to(base) or out == base or out.exists():
    parser.error("output must be a new directory below results/bench-090")
rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, check=True).stdout.strip()
if rev != DEFAULT_REV:
    raise SystemExit("worktree is not at the expected benchmark revision")
dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "src", "crates", "tests/long_running", "Cargo.toml", "Cargo.lock", "build.rs", ".cargo"], cwd=worktree)
if dirty.returncode != 0:
    raise SystemExit("test or build files differ from the recorded revision")
if not Path(CARGO).is_file():
    raise SystemExit("cargo executable not found")

out.mkdir(parents=True)
temp = out / "temp"
temp.mkdir()
manifest = {
    "state": "waiting-for-resources", "source_commit": rev, "worktree": str(worktree),
    "command": COMMAND, "sample_interval_seconds": args.interval,
    "started_at": datetime.now(timezone.utc).isoformat(), "gate_samples": [],
    "collector_limitations": [
        "Windows Win32_Process parent IDs identify the Cargo descendant tree; PIDs and creation times are recorded to expose possible PID reuse.",
        "WorkingSet64 and PrivateMemorySize64 have different meanings; neither alone establishes a memory leak.",
        "Each process-tree observation starts an extra PowerShell process and samples system CPU for about one second; it can perturb the target and is included in system CPU.",
        "collector_wall_seconds measures the subprocess wall cost, not its CPU usage; total collector CPU and attribution cannot be inferred from that field.",
        "The test itself also invokes PowerShell to sample its working set; additional observation is a diagnostic condition, not identical to the original failed run.",
    ],
}
for tool, command in (("cargo", [CARGO, "--version"]), ("rustc", [shutil.which("rustc") or str(Path(CARGO).with_name("rustc.exe")), "--version", "--verbose"])):
    try:
        version = subprocess.run(command, capture_output=True, text=True)
        manifest[tool] = {"exit_code": version.returncode, "stdout": version.stdout, "stderr": version.stderr}
    except OSError as exc:
        manifest[tool] = {"exit_code": None, "error": str(exc)}
(out / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
gate_ps = ("$ErrorActionPreference='Stop'; "
           "$x=@((Get-Counter '\\Processor(_Total)\\% Processor Time' -SampleInterval 1 -MaxSamples 5).CounterSamples | ForEach-Object {$_.CookedValue}); "
           "$m=Get-CimInstance Win32_OperatingSystem; "
           "@{cpu_percent=$x; available_memory_bytes=[int64]$m.FreePhysicalMemory*1024; timestamp_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Compress")
while True:
    sample = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", gate_ps], capture_output=True, text=True, creationflags=WINDOW_FLAGS)
    if sample.returncode:
        manifest.update({"state": "preflight-error", "error": sample.stderr})
        (out / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(1)
    try:
        gate = json.loads(sample.stdout)
        gate["passed"] = len(gate["cpu_percent"]) == 5 and all(0 <= x < 15 for x in gate["cpu_percent"]) and gate["available_memory_bytes"] >= 8 * (1 << 30)
    except (ValueError, KeyError, TypeError) as exc:
        manifest.update({"state": "preflight-error", "error": str(exc)})
        (out / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(1)
    manifest["gate_samples"].append(gate)
    (out / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"preflight: CPU={gate['cpu_percent']} free={gate['available_memory_bytes']} passed={gate['passed']}", flush=True)
    if gate["passed"]:
        break
    time.sleep(args.poll_seconds)

environment = os.environ.copy()
environment["TEMP"] = str(temp)
environment["TMP"] = str(temp)
environment["PYTHONIOENCODING"] = "utf-8"
environment.pop("TRIVIUM_TEST_QEMU_AARCH64", None)
environment.pop("TRIVIUM_ALLOCATOR_FAILURE_CHILD", None)
manifest["environment"] = {key: environment.get(key) for key in ("TEMP", "TMP", "CARGO_TARGET_DIR", "RAYON_NUM_THREADS", "TRIVIUM_MT_THREADS", "RUSTFLAGS", "RUSTUP_TOOLCHAIN")}
manifest["state"] = "running"
manifest["test_started_at"] = datetime.now(timezone.utc).isoformat()

with (out / "test.log").open("wb") as test_log, (out / "samples.ndjson").open("w", encoding="utf-8") as samples:
    cargo = subprocess.Popen(COMMAND, cwd=worktree, env=environment, stdout=test_log, stderr=subprocess.STDOUT, creationflags=WINDOW_FLAGS)
    manifest["cargo_pid"] = cargo.pid
    (out / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sampling_failures = 0
    sample_costs = []
    observed_test_identities = set()
    test_sample_counts = {}
    previous_cpu = {}
    while cargo.poll() is None:
        cycle_start = time.monotonic()
        cycle_timestamp = datetime.now(timezone.utc).isoformat()
        # Run the query with a literal integer PID; no command or path data from
        # the worktree is interpolated into the PowerShell source.
        tree_ps = r"""
$ErrorActionPreference='Stop'
$rootPid = __ROOT_PID__
$all = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CreationDate)
$ids = [System.Collections.Generic.HashSet[uint32]]::new()
[void]$ids.Add([uint32]$rootPid)
do {
    $changed = $false
    foreach ($p in $all) {
        if ($ids.Contains([uint32]$p.ParentProcessId) -and !$ids.Contains([uint32]$p.ProcessId)) {
            [void]$ids.Add([uint32]$p.ProcessId); $changed = $true
        }
    }
} while ($changed)
$tree = @()
foreach ($p in $all) {
    if ($ids.Contains([uint32]$p.ProcessId)) {
        $q = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $q) {
            $tree += @{pid=[int]$p.ProcessId; parent_pid=[int]$p.ParentProcessId; name=$p.Name;
                       created_at=$p.CreationDate.ToUniversalTime().ToString('o');
                       working_set_bytes=[int64]$q.WorkingSet64; private_bytes=[int64]$q.PrivateMemorySize64;
                       total_cpu_seconds=$q.CPU}
        }
    }
}
$cpu = @(Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 2).CounterSamples[-1].CookedValue
$os = Get-CimInstance Win32_OperatingSystem
@{timestamp_utc=[DateTime]::UtcNow.ToString('o'); system_cpu_percent=$cpu;
  available_memory_bytes=[int64]$os.FreePhysicalMemory*1024; processes=$tree} | ConvertTo-Json -Depth 5 -Compress
""".replace("__ROOT_PID__", str(cargo.pid))
        sampled = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", tree_ps], capture_output=True, text=True, creationflags=WINDOW_FLAGS)
        cost = time.monotonic() - cycle_start
        sample_costs.append(cost)
        try:
            if sampled.returncode:
                raise ValueError(sampled.stderr or "collector subprocess failed")
            payload = json.loads(sampled.stdout)
            for process in payload["processes"]:
                identity = f"{process['pid']}:{process['created_at']}"
                process["is_test_process"] = process["name"].lower().startswith("long_running-") and process["name"].lower().endswith(".exe")
                if process["is_test_process"]:
                    observed_test_identities.add(identity)
                    test_sample_counts[identity] = test_sample_counts.get(identity, 0) + 1
                old = previous_cpu.get(identity)
                cpu = process.get("total_cpu_seconds")
                if old and isinstance(cpu, (int, float)) and cycle_start > old[0] and cpu >= old[1]:
                    # One fully busy logical core is 100%; values can exceed it.
                    process["cpu_percent_one_core"] = 100 * (cpu - old[1]) / (cycle_start - old[0])
                else:
                    process["cpu_percent_one_core"] = None
                if isinstance(cpu, (int, float)):
                    previous_cpu[identity] = (cycle_start, cpu)
            payload["collector_wall_seconds"] = cost
            payload["collector_started_at"] = cycle_timestamp
            payload["collector_finished_at"] = datetime.now(timezone.utc).isoformat()
            samples.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except (ValueError, KeyError, TypeError) as exc:
            sampling_failures += 1
            samples.write(json.dumps({"collector_error": str(exc), "collector_wall_seconds": cost, "timestamp_utc": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
        samples.flush()
        time.sleep(max(0, args.interval - (time.monotonic() - cycle_start)))

manifest["exit_code"] = cargo.returncode
manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
manifest["observed_test_identities"] = sorted(observed_test_identities)
manifest["test_sample_counts"] = test_sample_counts
manifest["sampling"] = {"count": len(sample_costs), "failed": sampling_failures, "mean_collector_wall_seconds": sum(sample_costs) / len(sample_costs) if sample_costs else None, "max_collector_wall_seconds": max(sample_costs) if sample_costs else None}
raw_test_log = (out / "test.log").read_text(encoding="utf-8", errors="replace")
manifest["test_audit"] = parse_cargo_test_summaries(raw_test_log, ["long_running"])
binary = next((b for b in manifest["test_audit"]["binaries"] if b["target"] == "long_running"), None)
final = binary["final"] if binary else None
exactly_one = bool(final) and final["passed"] + final["failed"] == 1
manifest["state"] = "passed" if cargo.returncode == 0 and manifest["test_audit"]["valid"] and exactly_one and max(test_sample_counts.values(), default=0) >= 2 and sampling_failures == 0 else "failed-or-incomplete"
(out / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"diagnostic status: {manifest['state']}; exit={cargo.returncode}; test_processes={len(observed_test_identities)}", flush=True)
raise SystemExit(0 if manifest["state"] == "passed" else 1)

"""Extract Cargo test binary summaries without treating child test output as totals."""

from __future__ import annotations

import re


def parse_cargo_test_summaries(text: str, expected_targets: list[str]) -> dict:
    """Return every summary per binary and validate its final, top-level summary.

    Some fault tests launch the same test executable as a child, and that child
    may print its own test-result line. Cargo emits each top-level binary's
    `Running ...` line once; its last summary before the next binary is the
    enclosing harness's result. Keep earlier child lines but never add them to
    the enclosing count.
    """
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
    running_pattern = re.compile(r"^\s*Running\s+(.+?)\s+\(([^()]*)\)\s*$")
    result_pattern = re.compile(
        r"^\s*test result:\s+(ok|FAILED)\.\s+(\d+) passed;\s+(\d+) failed;\s+"
        r"(\d+) ignored;\s+(\d+) measured;\s+(\d+) filtered out;"
    )
    groups: list[dict] = []
    for line_number, line in enumerate(clean.splitlines(), start=1):
        running = running_pattern.match(line)
        if running:
            exe = re.split(r"[\\/]", running.group(2))[-1]
            targets = [target for target in expected_targets if exe.startswith(target + "-")]
            groups.append({"source": running.group(1), "executable": exe, "target": targets[0] if len(targets) == 1 else None, "line": line_number, "summaries": []})
            continue
        result = result_pattern.match(line)
        if result and groups:
            groups[-1]["summaries"].append({"line": line_number, "result": result.group(1), "passed": int(result.group(2)), "failed": int(result.group(3)), "ignored": int(result.group(4)), "measured": int(result.group(5)), "filtered_out": int(result.group(6))})
    problems: list[str] = []
    for group in groups:
        group["final"] = group["summaries"][-1] if group["summaries"] else None
    for target in expected_targets:
        found = [group for group in groups if group["target"] == target]
        if len(found) != 1:
            problems.append(f"{target}: expected one Cargo test binary, found {len(found)}")
            continue
        final = found[0]["final"]
        if final is None:
            problems.append(f"{target}: no final test summary")
        elif final["passed"] + final["failed"] == 0:
            problems.append(f"{target}: no tests executed; ignored and filtered tests do not count")
        elif final["result"] != "ok" or final["failed"]:
            problems.append(f"{target}: harness reported failure")
    return {"expected_targets": expected_targets, "binaries": groups, "problems": problems, "valid": not problems}

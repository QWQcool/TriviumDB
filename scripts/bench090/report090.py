"""把 results/bench-090/raw 里的原始结果合并成可发布的口径。

规则（与 PROTOCOL.md 一致）：
  * 同一 (数据集, 引擎, ef) 的多次重复取 QPS/延迟中位数，召回取中位数（确定性应完全一致）；
  * "同召回对比"默认取 R@10 = 90% 处线性插值 QPS；到不了 90% 就如实写 unreachable，
    绝不外推，也绝不换一个更低的目标值来凑数；
  * 构建时间、内存按同一次 run 取值（内存是 hot_bytes / estimated，输出里明确标注 kind）。

用法：
  .venv\\Scripts\\python.exe scripts\\bench090\\report090.py --datasets cohere-1m,minilm-384
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows 控制台默认 GBK，会把 † 之类的符号打崩
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
BASE_OUT = ROOT / "results" / "bench-090"

TARGET_RECALL = 0.90
ENGINE_ORDER = ["triviumdb", "hnswlib", "faiss_hnsw"]


def load_runs(raw: Path) -> list[dict]:
    runs = []
    for path in sorted(raw.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        meta_path = path.with_suffix(".meta.json")
        if payload.get("engine") is None and path.name.split("__")[1:2]:
            # TriviumDB 原始 JSON：形状由 benches/bench_cohere1m.rs 决定
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            dataset = meta.get("dataset", payload.get("dataset"))
            points = [
                {
                    "ef": m["ef_search"],
                    "recall_at_10": m["recall_at_10"],
                    "qps": m["qps"],
                    "latency_ms": m["latency_ms"],
                }
                for m in payload.get("measurements", [])
            ]
            runs.append({
                "dataset": dataset,
                "engine": "triviumdb",
                "version": meta.get("engine_version", "0.9.0"),
                "dim": payload.get("dim"),
                "n_train": payload.get("n_train"),
                "n_test": payload.get("n_test"),
                "threads": meta.get("threads"),
                "repeats": meta.get("repeats"),
                "train_limit": meta.get("train_limit"),
                "build_seconds": payload.get("build", {}).get("seconds"),
                "memory_bytes": payload.get("build", {}).get("hot_bytes"),
                "memory_kind": "hot_bytes",
                "points": points,
                "source": path.name,
            })
        else:
            runs.append({
                "dataset": payload.get("dataset"),
                "engine": payload.get("engine"),
                "version": payload.get("engine_version"),
                "dim": payload.get("dim"),
                "n_train": payload.get("n_train"),
                "n_test": payload.get("n_test"),
                "threads": payload.get("threads"),
                "repeats": payload.get("repeats"),
                "train_limit": payload.get("train_limit"),
                "build_seconds": payload.get("build", {}).get("seconds"),
                "memory_bytes": payload.get("memory", {}).get("bytes"),
                "memory_kind": payload.get("memory", {}).get("kind"),
                "points": payload.get("points", []),
                "source": path.name,
            })
    return [r for r in runs if r["dataset"] and r["points"]]


def merge_points(runs: list[dict]) -> list[dict]:
    by_ef: dict[int, list[dict]] = {}
    for run in runs:
        for p in run["points"]:
            by_ef.setdefault(int(p["ef"]), []).append(p)
    merged = []
    for ef in sorted(by_ef):
        group = by_ef[ef]
        merged.append({
            "ef": ef,
            "recall_at_10": statistics.median(p["recall_at_10"] for p in group),
            "recall_min": min(p["recall_at_10"] for p in group),
            "recall_max": max(p["recall_at_10"] for p in group),
            "qps": statistics.median(p["qps"] for p in group),
            "latency_ms": statistics.median(p["latency_ms"] for p in group),
            "samples": len(group),
        })
    return merged


def qps_at_recall(points: list[dict], target: float) -> dict:
    """在 recall-QPS 曲线上按 recall 线性插值，不外推。"""
    if not points:
        return {"reachable": False, "reason": "no points"}
    ordered = sorted(points, key=lambda p: (p["recall_at_10"], p["qps"]))
    dedup: dict[float, dict] = {}
    for p in ordered:
        key = round(p["recall_at_10"], 9)
        prev = dedup.get(key)
        if prev is None or p["qps"] > prev["qps"]:
            dedup[key] = p
    curve = [dedup[k] for k in sorted(dedup)]

    max_recall = curve[-1]["recall_at_10"]
    if max_recall < target:
        return {
            "reachable": False,
            "max_recall": max_recall,
            "max_recall_ef": curve[-1]["ef"],
            "reason": f"本次扫描到的最高召回 {max_recall:.4f} < {target:.2f}（可加大 ef 后重跑）",
        }

    for p in curve:
        if abs(p["recall_at_10"] - target) < 1e-12:
            return {"reachable": True, "qps": p["qps"], "ef_low": p["ef"], "ef_high": p["ef"],
                    "gap": 0.0, "confidence": "exact"}

    for lo, hi in zip(curve, curve[1:]):
        if lo["recall_at_10"] <= target <= hi["recall_at_10"]:
            span = hi["recall_at_10"] - lo["recall_at_10"]
            ratio = 0.0 if span <= 0 else (target - lo["recall_at_10"]) / span
            qps = lo["qps"] + ratio * (hi["qps"] - lo["qps"])
            return {
                "reachable": True,
                "qps": qps,
                "ef_low": lo["ef"],
                "ef_high": hi["ef"],
                "span_recall": span,
                "confidence": "interpolated" if span <= 0.05 else "coarse",
            }
    return {"reachable": False, "reason": "unexpected curve"}


def fmt_int(value) -> str:
    return "-" if value is None else f"{value:,.0f}"


def fmt_mb(value, kind) -> str:
    if value is None:
        return "-"
    return f"{value / (1 << 20):,.0f} MiB" + ("*" if kind in ("estimated", "hot_bytes") else "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", default="")
    parser.add_argument("--target", type=float, default=TARGET_RECALL)
    parser.add_argument("--tag", default="official", help="读取 results/bench-090/<tag>/raw")
    args = parser.parse_args()

    out_dir = BASE_OUT / args.tag
    raw = out_dir / "raw"
    runs = load_runs(raw)
    if not runs:
        print(f"没有找到原始结果：{raw}")
        return 1
    wanted = [x.strip() for x in args.datasets.split(",") if x.strip()]
    if wanted:
        runs = [r for r in runs if r["dataset"] in wanted]

    grouped: dict[str, dict[str, list[dict]]] = {}
    for run in runs:
        grouped.setdefault(run["dataset"], {}).setdefault(run["engine"], []).append(run)

    summary = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_recall": args.target,
        "notes": [
            "QPS/延迟为多次重复的中位数；召回为同组中位数（确定性应一致）",
            "同召回 QPS 为 recall 轴线性插值，不外推；到不了目标召回记 unreachable",
            "triviumdb 内存为 hot_bytes；hnswlib/faiss 为官方估算公式，带 * 标注",
        ],
        "datasets": {},
    }

    lines = ["# TriviumDB 0.9.0 对外口径基准", ""]
    lines.append(f"生成时间：{summary['generated_at']}　目标召回：R@10 = {args.target:.0%}")
    lines.append("")

    for dataset, engines in grouped.items():
        entry = {"engines": {}}
        rows = []
        for engine in ENGINE_ORDER + [e for e in engines if e not in ENGINE_ORDER]:
            if engine not in engines:
                continue
            merged = merge_points(engines[engine])
            ref = engines[engine][0]
            at_target = qps_at_recall(merged, args.target)
            entry["engines"][engine] = {
                "version": ref["version"],
                "dim": ref["dim"],
                "n_train": ref["n_train"],
                "n_test": ref["n_test"],
                "threads": ref["threads"],
                "repeats": ref["repeats"],
                "build_seconds": statistics.median(
                    r["build_seconds"] for r in engines[engine] if r["build_seconds"] is not None
                ) if any(r["build_seconds"] is not None for r in engines[engine]) else None,
                "memory_bytes": ref["memory_bytes"],
                "memory_kind": ref["memory_kind"],
                "points": merged,
                "at_target": at_target,
                "max_recall": max(p["recall_at_10"] for p in merged),
                "max_qps": max(p["qps"] for p in merged),
            }
            rows.append((engine, entry["engines"][engine]))
        if not rows:
            continue

        base_qps = entry["engines"].get("hnswlib", {}).get("at_target", {}).get("qps")
        lines.append(f"## {dataset}　({rows[0][1]['dim']}d, n_train={rows[0][1]['n_train']:,}, "
                     f"{rows[0][1]['threads']} threads, repeats={rows[0][1]['repeats']})")
        lines.append("")
        lines.append("| 引擎 | 版本 | R@10@90% QPS | vs hnswlib | 构建 s | 内存 | 最高召回 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for engine, info in rows:
            at = info["at_target"]
            qps = at.get("qps")
            ratio = (qps / base_qps) if (qps and base_qps) else None
            if not at.get("reachable"):
                qps_cell = "unreachable"
            else:
                qps_cell = fmt_int(qps) + ("†" if at.get("confidence") == "coarse" else "")
            ratio_cell = "-" if ratio is None else f"{ratio:.2f}x"
            build = info["build_seconds"]
            build_cell = "-" if build is None else f"{build:.1f}"
            lines.append(
                f"| {engine} | {info['version'] or '-'} | {qps_cell} | {ratio_cell} | "
                f"{build_cell} | {fmt_mb(info['memory_bytes'], info['memory_kind'])} | "
                f"{info['max_recall'] * 100:.2f}% |"
            )
        lines.append("")
        if any(not info["at_target"].get("reachable") for _, info in rows):
            lines.append("> unreachable = 本次 ef 扫描范围内没到 90% 召回，不是 0，也不能外推。")
            lines.append("")
        if any(info["at_target"].get("confidence") == "coarse" for _, info in rows):
            lines.append("> † = 插值区间 recall 跨度 > 5pp，只能看量级。")
            lines.append("")
        lines.append("> 内存带 * 为估算或 hot_bytes 口径，不同库之间只看量级。")
        lines.append("")
        summary["datasets"][dataset] = entry

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["dataset", "dim", "engine", "version", "ef", "recall_at_10",
                         "qps", "latency_ms", "build_seconds", "memory_bytes", "memory_kind"])
        for dataset, entry in summary["datasets"].items():
            for engine, info in entry["engines"].items():
                for p in info["points"]:
                    writer.writerow([dataset, info["dim"], engine, info["version"], p["ef"],
                                     f"{p['recall_at_10']:.6f}", f"{p['qps']:.3f}",
                                     f"{p['latency_ms']:.6f}",
                                     "" if info["build_seconds"] is None else f"{info['build_seconds']:.3f}",
                                     info["memory_bytes"], info["memory_kind"]])

    print("\n".join(lines))
    print(f"\n已写入: {out_dir / 'summary.json'}\n        {out_dir / 'summary.md'}\n        {out_dir / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

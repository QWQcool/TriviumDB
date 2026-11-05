"""TriviumDB 0.9.0 对外口径基准脚手架。

设计目标（只做三件事）：
  1. check  —— 在跑之前证明数据集、GroundTruth、依赖、工作树都是对的；
  2. tdb    —— 复用 v0.9.0 自带的 benches/bench_cohere1m.rs，不改一行源码；
  3. base   —— 用与官方 benches/bench_baselines.py 完全相同的建图/查询参数
                跑 hnswlib / FAISS-HNSW，但落结构化 JSON（官方脚本只打印表格）。

用法（必须用带 numpy 的解释器，本项目是 .venv）：
  .venv\\Scripts\\python.exe scripts\\bench090\\bench090.py check
  .venv\\Scripts\\python.exe scripts\\bench090\\bench090.py tdb  --datasets cohere-1m
  .venv\\Scripts\\python.exe scripts\\bench090\\bench090.py base --datasets cohere-1m
  .venv\\Scripts\\python.exe scripts\\bench090\\bench090.py plan

口径红线写在 PROTOCOL.md，本文件所有输出都带 provenance，不允许出现"来源不明"的数字。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
WORKTREE = ROOT / ".bench090"
RESULTS = ROOT / "results" / "bench-090"


def raw_dir(tag: str) -> Path:
    return RESULTS / tag / "raw"


def log_dir(tag: str) -> Path:
    return RESULTS / tag / "logs"

K = 10
DEFAULT_EFS = [10, 20, 40, 80, 120, 200, 400, 600, 800]
DEFAULT_M = 32
DEFAULT_EFC = 128
DEFAULT_THREADS = 16
DEFAULT_REPEATS = 3


@dataclass(frozen=True)
class Dataset:
    key: str
    preset: str          # bench_cohere1m.rs 的 TRIVIUM_ANN_NAME 预设名（未知名称会 panic）
    prefix: str          # 磁盘文件名前缀
    dim: int
    note: str

    @property
    def train(self) -> Path:
        return ROOT / f"{self.prefix}_train.f32"

    # factor > 1 时把查询集整行平铺 N 遍：召回不变，但每次计时窗口放大 N 倍，
    # 否则 1000 条查询在 4 万 QPS 下只有 25 ms，OS 抖动直接进结果（实测 CV 10%）。
    def test(self, factor: int = 1) -> Path:
        name = f"{self.prefix}_test.f32" if factor <= 1 else f"{self.prefix}_test_x{factor}.f32"
        return ROOT / name

    def gt(self, factor: int = 1) -> Path:
        name = (f"{self.prefix}_groundtruth.i32" if factor <= 1
                else f"{self.prefix}_groundtruth_x{factor}.i32")
        return ROOT / name


DATASETS: dict[str, Dataset] = {
    "cohere-1m": Dataset(
        "cohere-1m", "cohere-1m", "cohere", 768,
        "768d / 1M，高维主战场，也是旧文的主图",
    ),
    "minilm-384": Dataset(
        "minilm-384", "minilm-384", "minilm", 384,
        "384d / 1M，中维，旧文口径下与 HNSW 基本持平",
    ),
    "dbpedia-1536": Dataset(
        "dbpedia-1536", "dbpedia-1536", "dbpedia_openai", 1536,
        "1536d / 1M，最高维，内存压力最大",
    ),
    "sift128": Dataset(
        "sift128", "cohere-1m", "sift128", 128,
        "128d / 1M，边界对照，用来诚实披露劣势档",
    ),
}


# ────────────────────────────────────────────────────────────────
#  基础工具
# ────────────────────────────────────────────────────────────────

def find_cargo() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    suffix = ".exe" if os.name == "nt" else ""
    cand = Path.home() / ".cargo" / "bin" / f"cargo{suffix}"
    return str(cand) if cand.exists() else None


def run_capture(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    proc = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-25:])
        raise RuntimeError(f"命令失败({proc.returncode}): {' '.join(cmd)}\n--- tail ---\n{tail}")
    return proc.stdout or ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def pkg_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except Exception:
        return None


def host_info(threads: int) -> dict:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_logical": os.cpu_count(),
        "threads_used": threads,
        "python": sys.version.split()[0],
        "numpy": pkg_version("numpy"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def worktree_rev() -> str:
    return run_capture(["git", "rev-parse", "HEAD"], cwd=WORKTREE).strip()


def rustc_version(cargo: str) -> str:
    try:
        return run_capture([cargo, "--version"]).strip()
    except Exception:
        return "unknown"


def n_rows(path: Path, dim: int) -> int:
    size = path.stat().st_size
    if size % (4 * dim):
        raise ValueError(f"{path.name} 大小 {size} 不能被 4*{dim} 整除，维度不匹配")
    return size // (4 * dim)


def factor_for(ds: Dataset, args) -> int:
    """查询集平铺倍数：显式 --factor 优先，否则按 target-queries 自动取整。"""
    if args.factor and args.factor > 0:
        return args.factor
    n = n_rows(ds.test(), ds.dim)
    return max(1, math.ceil(args.target_queries / n))


# ────────────────────────────────────────────────────────────────
#  GroundTruth 自检：这是整条证据链最贵也是最关键的一步
# ────────────────────────────────────────────────────────────────

def l2norm(a):
    import numpy as np
    n = np.linalg.norm(a, axis=1, keepdims=True)
    return a / np.maximum(n, np.float32(1e-12))


def exact_topk(train_path: Path, queries, dim: int, k: int,
               chunk_rows: int = 100_000, limit: int | None = None):
    """分块精确 top-k（cosine），避免一次性吃下 1M×1536 的三份副本。"""
    import numpy as np

    total = n_rows(train_path, dim)
    if limit:
        total = min(total, limit)
    qn = l2norm(queries.astype(np.float32, copy=True))
    nq = qn.shape[0]
    best_s = np.full((nq, k), -np.inf, dtype=np.float32)
    best_i = np.full((nq, k), -1, dtype=np.int64)
    mm = np.memmap(train_path, dtype=np.float32, mode="r").reshape(-1, dim)
    ids = np.arange(total, dtype=np.int64)
    for start in range(0, total, chunk_rows):
        stop = min(start + chunk_rows, total)
        block = l2norm(np.array(mm[start:stop], dtype=np.float32, copy=True))
        sims = qn @ block.T
        cand_s = np.concatenate([best_s, sims], axis=1)
        cand_i = np.concatenate([best_i, np.broadcast_to(ids[start:stop], (nq, stop - start))], axis=1)
        part = np.argpartition(-cand_s, k - 1, axis=1)[:, :k]
        rows = np.arange(nq)[:, None]
        best_s = cand_s[rows, part]
        best_i = cand_i[rows, part]
    order = np.argsort(-best_s, axis=1)
    return np.take_along_axis(best_i, order, axis=1), np.take_along_axis(best_s, order, axis=1)


def preflight(ds: Dataset, n_queries: int = 32, train_limit: int | None = None,
              factor: int = 1) -> dict:
    import numpy as np

    total = n_rows(ds.train, ds.dim)
    if train_limit:
        total = min(total, train_limit)
    q_all = np.fromfile(ds.test(factor), dtype=np.float32).reshape(-1, ds.dim)
    nq = min(n_queries, q_all.shape[0])
    queries = q_all[:nq]

    gt_raw = np.fromfile(ds.gt(factor), dtype=np.int32)
    k_gt = gt_raw.shape[0] // q_all.shape[0]
    gt = gt_raw.reshape(q_all.shape[0], k_gt)[:nq, :K]

    if train_limit and train_limit < n_rows(ds.train, ds.dim):
        # 子集模式：GT 与数据不再是同一全集，一致性比较无意义，明确跳过
        return {"mode": "subset", "queries": nq, "gt_match": None, "tie_gap_median": None}

    ids, scores = exact_topk(ds.train, queries, ds.dim, K + 1)
    match = float(
        statistics.mean(
            len(set(ids[i, :K].tolist()) & set(gt[i].tolist())) / K for i in range(nq)
        )
    )
    gap = (scores[:, K - 1] - scores[:, K]).astype(float)
    return {
        "mode": "full",
        "queries": nq,
        "gt_match": match,
        "tie_gap_median": float(np.median(gap)),
        "tie_gap_min": float(gap.min()),
    }


# ────────────────────────────────────────────────────────────────
#  tile：把查询集整行平铺，放大计时窗口
# ────────────────────────────────────────────────────────────────

def cmd_tile(args) -> int:
    import numpy as np

    for key in args.datasets:
        ds = DATASETS[key]
        f = factor_for(ds, args)
        if f <= 1:
            print(f"  {key}: 查询集已够大（{n_rows(ds.test(), ds.dim)} 条），不平铺")
            continue
        n_q = n_rows(ds.test(), ds.dim)
        queries = np.fromfile(ds.test(), dtype=np.float32).reshape(n_q, ds.dim)
        np.tile(queries, (f, 1)).tofile(ds.test(f))

        gt = np.fromfile(ds.gt(), dtype=np.int32).reshape(n_q, -1)
        np.tile(gt, (f, 1)).tofile(ds.gt(f))
        print(f"  {key}: {n_q} -> {n_q * f} queries (x{f})  "
              f"k={gt.shape[1]}  {ds.test(f).stat().st_size / (1 << 20):.0f} MiB")
    print("平铺完成：召回期望值不变，计时窗口放大后 OS 抖动被摊薄")
    return 0


# ────────────────────────────────────────────────────────────────
#  check
# ────────────────────────────────────────────────────────────────

def cmd_check(args) -> int:
    ok = True
    print("== 环境 ==")
    if pkg_version("numpy") is None:
        print("  [FAIL] 当前解释器没有 numpy，请用 .venv\\Scripts\\python.exe 运行")
        return 2
    cargo = find_cargo()
    print(f"  python  : {sys.executable} ({sys.version.split()[0]})")
    print(f"  numpy   : {pkg_version('numpy')}")
    print(f"  hnswlib : {pkg_version('hnswlib') or '未安装（基线将跳过）'}")
    print(f"  faiss   : {pkg_version('faiss-cpu') or pkg_version('faiss') or '未安装（基线将跳过）'}")
    print(f"  cargo   : {cargo or '未找到'}")
    print(f"  worktree: {WORKTREE}")
    if not WORKTREE.exists():
        print("  [FAIL] 工作树不存在：git worktree add .bench090 v0.9.0")
        return 2
    rev = worktree_rev()
    tag = run_capture(["git", "describe", "--tags"], cwd=WORKTREE).strip()
    print(f"  version : {tag} @ {rev[:9]}")
    if not tag.startswith("v0.9.0"):
        print(f"  [FAIL] 工作树不是 v0.9.0（实际 {tag}）")
        ok = False

    print("\n== 数据集 ==")
    for key in args.datasets:
        ds = DATASETS[key]
        f = factor_for(ds, args)
        test_path, gt_path = ds.test(f), ds.gt(f)
        if not (ds.train.exists() and test_path.exists() and gt_path.exists()):
            hint = "" if f <= 1 else f"（缺少 x{f} 平铺文件，先跑 tile）"
            print(f"  [FAIL] {key}: 文件缺失 {hint}")
            ok = False
            continue
        n_train = n_rows(ds.train, ds.dim)
        n_test = n_rows(test_path, ds.dim)
        gt_ids = gt_path.stat().st_size // 4
        k_gt = gt_ids // n_test if n_test else 0
        gib = ds.train.stat().st_size / (1 << 30)
        print(f"  {key:14s} dim={ds.dim:<5d} n_train={n_train:<9d} n_test={n_test:<6d} "
              f"k_gt={k_gt:<3d} train={gib:5.2f}GiB  ({ds.note})")
        if gt_ids % n_test:
            print(f"    [FAIL] GT 条数不能被 n_test 整除")
            ok = False
        if k_gt < K:
            print(f"    [FAIL] GT 不足 Top-{K}")
            ok = False

    if args.preflight_queries > 0:
        print(f"\n== GroundTruth 自检（每集 {args.preflight_queries} 条查询，精确 cosine 重算）==")
        for key in args.datasets:
            ds = DATASETS[key]
            f = factor_for(ds, args)
            if not (ds.train.exists() and ds.test(f).exists() and ds.gt(f).exists()):
                continue
            t0 = time.perf_counter()
            res = preflight(ds, args.preflight_queries, factor=f)
            dt = time.perf_counter() - t0
            match = res["gt_match"]
            flag = "OK"
            if match is not None and match < 0.995:
                flag = "FAIL(口径不一致)"
                ok = False
            print(f"  {key:14s} gt_match={match if match is None else f'{match:.4f}'}  "
                  f"tie_gap_median={res['tie_gap_median']}  ({dt:.1f}s) [{flag}]")
            if res["tie_gap_median"] is not None and res["tie_gap_median"] < 1e-6:
                print("    [WARN] 第 10/11 名得分几乎相同，极端情况下召回上限 < 100%（tie floor）")

    print("\n结论:", "可以开跑" if ok else "存在阻塞项，先修")
    return 0 if ok else 1


# ────────────────────────────────────────────────────────────────
#  tdb：驱动 v0.9.0 自带 bench_cohere1m.rs
# ────────────────────────────────────────────────────────────────

def cmd_tdb(args) -> int:
    cargo = find_cargo()
    if not cargo:
        raise SystemExit("未找到 cargo")
    raw_dir(args.tag).mkdir(parents=True, exist_ok=True)
    log_dir(args.tag).mkdir(parents=True, exist_ok=True)
    run_id = f"tdb-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    rev = worktree_rev()

    for key in args.datasets:
        ds = DATASETS[key]
        f = factor_for(ds, args)
        for rep in range(args.repeats):
            stem = f"{key}__triviumdb__r{rep + 1}"
            out_json = raw_dir(args.tag) / f"{stem}.json"
            log_path = log_dir(args.tag) / f"{stem}.log"
            env = os.environ.copy()
            env.update({
                "RAYON_NUM_THREADS": str(args.threads),
                "TRIVIUM_ANN_NAME": ds.preset,
                "TRIVIUM_ANN_DIM": str(ds.dim),
                "TRIVIUM_ANN_TRAIN": str(ds.train),
                "TRIVIUM_ANN_TEST": str(ds.test(f)),
                "TRIVIUM_ANN_GT": str(ds.gt(f)),
                "TRIVIUM_ANN_EF": ",".join(str(x) for x in args.efs),
                "TRIVIUM_ANN_M": str(args.m),
                "TRIVIUM_ANN_EF_CONSTRUCTION": str(args.efc),
                "TRIVIUM_RESULT_PATH": str(out_json),
            })
            if args.train_limit:
                env["TRIVIUM_ANN_TRAIN_LIMIT"] = str(args.train_limit)
            if getattr(args, "rerank", ""):
                env["TRIVIUM_ANN_RERANK"] = args.rerank
            print(f"[tdb] {key} repeat {rep + 1}/{args.repeats} ...", flush=True)
            t0 = time.perf_counter()
            proc = subprocess.run(
                [cargo, "bench", "--locked", "--bench", "bench_cohere1m"],
                cwd=str(WORKTREE), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
            )
            log_path.write_text(proc.stdout or "", encoding="utf-8")
            dt = time.perf_counter() - t0
            if proc.returncode != 0 or not out_json.exists():
                tail = "\n".join((proc.stdout or "").splitlines()[-25:])
                print(f"  [FAIL] rc={proc.returncode}，日志 {log_path}\n{tail}")
                return 1
            sidecar = {
                "engine": "triviumdb",
                "engine_version": "0.9.0",
                "git_rev": rev,
                "dataset": key,
                "dim": ds.dim,
                "threads": args.threads,
                "params": {"m": args.m, "ef_construction": args.efc, "k": K},
                "repeats": args.repeats,
                "repeat_index": rep + 1,
                "train_limit": args.train_limit,
                "test_factor": f,
                "rerank": args.rerank or None,
                "wall_seconds": round(dt, 3),
                "run_id": run_id,
                "host": host_info(args.threads),
            }
            out_json.with_suffix(".meta.json").write_text(
                json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  ok  {dt:.1f}s -> {out_json.name}")
    return 0


# ────────────────────────────────────────────────────────────────
#  base：与官方 bench_baselines.py 同参，但输出 JSON
# ────────────────────────────────────────────────────────────────

def load_dataset(ds: Dataset, train_limit: int | None, factor: int = 1):
    import numpy as np

    total = n_rows(ds.train, ds.dim)
    n_train = min(total, train_limit) if train_limit else total
    train = np.fromfile(ds.train, dtype=np.float32).reshape(-1, ds.dim)[:n_train]
    queries = np.fromfile(ds.test(factor), dtype=np.float32).reshape(-1, ds.dim)
    gt_raw = np.fromfile(ds.gt(factor), dtype=np.int32)
    k_gt = gt_raw.shape[0] // queries.shape[0]
    gt = gt_raw.reshape(queries.shape[0], k_gt)[:, :K]
    gt_mode = "file"
    if n_train < total:
        ids, _ = exact_topk(ds.train, queries, ds.dim, K, limit=n_train)
        gt = ids[:, :K].astype(np.int32)
        gt_mode = "recomputed_subset"
    return train, queries, gt, gt_mode


def _measure(fn, queries, warmup=10, repeats=1):
    """返回 (labels, qps_median, latency_ms_median)。"""
    import numpy as np

    if warmup:
        fn(queries[: min(warmup, len(queries))])
    labels, qps_list, lat_list = None, [], []
    for _ in range(repeats):
        t0 = time.perf_counter()
        labels = fn(queries)
        elapsed = time.perf_counter() - t0
        qps_list.append(len(queries) / elapsed)
        lat_list.append(elapsed / len(queries) * 1000.0)
    return labels, float(statistics.median(qps_list)), float(statistics.median(lat_list))


def bench_hnswlib(train, queries, gt, ds: Dataset, args):
    import hnswlib
    import numpy as np

    idx = hnswlib.Index(space="cosine", dim=ds.dim)
    idx.init_index(max_elements=train.shape[0], ef_construction=args.efc, M=args.m)
    idx.set_num_threads(args.threads)
    t0 = time.perf_counter()
    idx.add_items(train, np.arange(train.shape[0]))
    build_s = time.perf_counter() - t0

    points = []
    for ef in args.efs:
        idx.set_ef(ef)
        idx.set_num_threads(args.threads)
        labels, qps, lat = _measure(
            lambda q: idx.knn_query(q, k=K, num_threads=args.threads)[0],
            queries, repeats=args.repeats,
        )
        recall = float(
            statistics.mean(
                len(set(labels[i].tolist()) & set(gt[i].tolist())) / K for i in range(len(queries))
            )
        )
        points.append({"ef": ef, "recall_at_10": recall, "qps": qps, "latency_ms": lat})
        print(f"    ef={ef:<5d} R@10={recall * 100:6.2f}%  QPS={qps:>10,.0f}")
    return build_s, points


def bench_faiss_hnsw(train, queries, gt, ds: Dataset, args):
    import faiss
    import numpy as np

    # 原地归一化：1536d/990K 再复制一份要 5.7 GiB，实测会把共享机器顶到 bad_alloc
    xb = train
    norms = np.linalg.norm(xb, axis=1, keepdims=True)
    np.maximum(norms, np.float32(1e-12), out=norms)
    xb /= norms
    xq = l2norm(queries)
    faiss.omp_set_num_threads(args.threads)
    idx = faiss.IndexHNSWFlat(ds.dim, args.m, faiss.METRIC_INNER_PRODUCT)
    idx.hnsw.efConstruction = args.efc
    t0 = time.perf_counter()
    idx.add(xb)
    build_s = time.perf_counter() - t0

    points = []
    for ef in args.efs:
        idx.hnsw.efSearch = ef
        faiss.omp_set_num_threads(args.threads)
        labels, qps, lat = _measure(
            lambda q: idx.search(q, K)[1], xq, repeats=args.repeats,
        )
        recall = float(
            statistics.mean(
                len(set(labels[i].tolist()) & set(gt[i].tolist())) / K for i in range(len(queries))
            )
        )
        points.append({"ef": ef, "recall_at_10": recall, "qps": qps, "latency_ms": lat})
        print(f"    ef={ef:<5d} R@10={recall * 100:6.2f}%  QPS={qps:>10,.0f}")
    return build_s, points


BASELINES = {"hnswlib": bench_hnswlib, "faiss_hnsw": bench_faiss_hnsw}


def cmd_base(args) -> int:
    raw_dir(args.tag).mkdir(parents=True, exist_ok=True)
    log_dir(args.tag).mkdir(parents=True, exist_ok=True)

    # 多引擎时每个引擎各起一个子进程：1M×1536 的索引常驻接近 20 GB，
    # 同一进程连续跑两个库会因地址空间碎片 bad_alloc（已实测踩到）。
    if os.environ.get("BENCH090_NO_ISOLATE") != "1" and len(args.engines) > 1:
        rc = 0
        env = os.environ.copy()
        env["BENCH090_NO_ISOLATE"] = "1"
        for name in args.engines:
            child = [
                sys.executable, str(Path(__file__).resolve()), "base",
                "--datasets", ",".join(args.datasets), "--engines", name,
                "--efs", ",".join(str(x) for x in args.efs),
                "--m", str(args.m), "--efc", str(args.efc),
                "--threads", str(args.threads), "--repeats", str(args.repeats),
                "--tag", args.tag, "--train-limit", str(args.train_limit or 0),
            ]
            print(f"[base] ===== engine {name}（独立进程） =====", flush=True)
            rc = subprocess.run(child, env=env).returncode or rc
        return rc

    run_id = f"base-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    for key in args.datasets:
        ds = DATASETS[key]
        f = factor_for(ds, args)
        print(f"[base] {key} dim={ds.dim} queries x{f} loading ...", flush=True)
        train, queries, gt, gt_mode = load_dataset(ds, args.train_limit, f)
        for name in args.engines:
            fn = BASELINES.get(name)
            if fn is None:
                print(f"  [skip] 未知基线 {name}")
                continue
            print(f"  --- {name} ---", flush=True)
            try:
                build_s, points = fn(train, queries, gt, ds, args)
            except ImportError as exc:
                print(f"  [skip] {name} 未安装：{exc}")
                continue
            payload = {
                "schema_version": 2,
                "engine": name,
                "engine_version": pkg_version(name if name != "faiss_hnsw" else "faiss-cpu"),
                "dataset": key,
                "dim": ds.dim,
                "n_train": int(train.shape[0]),
                "n_test": int(queries.shape[0]),
                "metric": "cosine (l2-normalized, inner product)",
                "gt_mode": gt_mode,
                "params": {"M": args.m, "ef_construction": args.efc, "k": K},
                "threads": args.threads,
                "repeats": args.repeats,
                "build": {"seconds": round(build_s, 3)},
                "memory": {
                    "kind": "estimated",
                    "bytes": int(train.shape[0] * (2 * args.m * 4 + ds.dim * 4 + 16)),
                },
                "points": points,
                "train_limit": args.train_limit,
                "test_factor": f,
                "run_id": run_id,
                "host": host_info(args.threads),
            }
            stem = f"{key}__{name}"
            (raw_dir(args.tag) / f"{stem}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  -> {stem}.json")
    return 0


# ────────────────────────────────────────────────────────────────
#  plan：把"每张图对应哪条命令"打印出来，直接贴进 PROTOCOL.md
# ────────────────────────────────────────────────────────────────

def cmd_plan(args) -> int:
    py = r".venv\Scripts\python.exe"
    print("# 0) 环境与口径自检（必须先过）")
    print(f"{py} scripts\\bench090\\bench090.py check --datasets {','.join(args.datasets)}")
    print()
    print("# 1) 主图：recall-QPS 曲线（4 个数据集）")
    print(f"{py} scripts\\bench090\\bench090.py tdb  --datasets {','.join(args.datasets)} --repeats 3")
    print(f"{py} scripts\\bench090\\bench090.py base --datasets {','.join(args.datasets)} "
          f"--engines hnswlib,faiss_hnsw --repeats 3")
    print()
    print("# 2) 副图：构建时间 / 内存（同一次 raw 里已有 build.seconds 与 hot_bytes）")
    print(f"{py} scripts\\bench090\\report090.py --datasets {','.join(args.datasets)}")
    print()
    print("# 3) 冒烟（只验证管线通，不能当结论）")
    print(f"{py} scripts\\bench090\\bench090.py tdb --datasets cohere-1m "
          f"--train-limit 20000 --efs 10,80 --repeats 1 --tag smoke")
    return 0


# ────────────────────────────────────────────────────────────────
#  CLI
# ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TriviumDB 0.9.0 基准脚手架")
    sub = p.add_subparsers(dest="task", required=True)

    def common(sp):
        sp.add_argument("--datasets", default="cohere-1m",
                        help="逗号分隔，可选: " + ", ".join(DATASETS) + "，或 all")
        sp.add_argument("--efs", default=",".join(str(x) for x in DEFAULT_EFS))
        sp.add_argument("--m", type=int, default=DEFAULT_M)
        sp.add_argument("--efc", type=int, default=DEFAULT_EFC)
        sp.add_argument("--threads", type=int, default=DEFAULT_THREADS)
        sp.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
        sp.add_argument("--train-limit", type=int, default=0,
                        help=">0 时只取前 N 条（仅用于冒烟，会重算 GT）")
        sp.add_argument("--tag", default="official",
                        help="结果子目录名；冒烟请用 smoke，避免污染正式结果")
        sp.add_argument("--rerank", default="",
                        help="TriviumDB 专用：精排候选数列表，如 64,128,256；留空=默认 SM 预算")
        sp.add_argument("--factor", type=int, default=0,
                        help="查询集平铺倍数；0=按 target-queries 自动，1=不平铺")
        sp.add_argument("--target-queries", type=int, default=20_000,
                        help="自动平铺的目标查询数（默认 2 万，约 0.5-2 s 计时窗口）")

    sp = sub.add_parser("check")
    common(sp)
    sp.add_argument("--preflight-queries", type=int, default=16,
                    help="每集抽多少条查询重算精确 Top-10 对拍 GT；0 表示跳过（不推荐）")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("tdb")
    common(sp)
    sp.set_defaults(func=cmd_tdb)

    sp = sub.add_parser("base")
    common(sp)
    sp.add_argument("--engines", default="hnswlib,faiss_hnsw")
    sp.set_defaults(func=cmd_base)

    sp = sub.add_parser("tile")
    common(sp)
    sp.set_defaults(func=cmd_tile)

    sp = sub.add_parser("plan")
    common(sp)
    sp.set_defaults(func=cmd_plan)
    return p


def normalize_args(args):
    if args.datasets == "all":
        args.datasets = list(DATASETS)
    else:
        args.datasets = [x.strip() for x in args.datasets.split(",") if x.strip()]
    for key in args.datasets:
        if key not in DATASETS:
            raise SystemExit(f"未知数据集 {key}，可选: {', '.join(DATASETS)}")
    args.efs = [int(x) for x in str(args.efs).split(",") if x.strip()]
    args.train_limit = args.train_limit or None
    if hasattr(args, "engines"):
        args.engines = [x.strip() for x in args.engines.split(",") if x.strip()]
    return args


def main() -> int:
    args = normalize_args(build_parser().parse_args())
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n用户中断")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

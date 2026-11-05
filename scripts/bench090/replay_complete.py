"""Isolated, append-only ANN benchmark replay with independently rebuilt indexes.

This is a new runner: it does not change the historical bench090 scripts or
their results. A formal invocation requires a fresh tag and performs three
independent builds for every dataset and engine. Each build measures one full
query batch at each ef. Smoke mode is explicitly marked and cannot be used for
publication. See --help. This script is intended for the Windows benchmark host.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import bench090 as old
import report090 as report

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'results' / 'bench-090'
EFS = [10, 15, 20, 25, 30, 35, 40, 80, 120, 200, 400, 800]
ENGINES = ['triviumdb', 'hnswlib', 'faiss_hnsw']
EXPECTED_REV = '7edf8ceacd85cd71944a3471ac05df377995a172'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def write_json(path, payload):
    # Exclusive creation preserves failed attempts and prevents stale results.
    with path.open('x', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write('\n')


def append_event(path, event):
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + '\n')
        fh.flush()
        os.fsync(fh.fileno())


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                ('avail_extended', ctypes.c_ulonglong)]


def memory_snapshot():
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return {'available_bytes': status.avail_phys, 'total_bytes': status.total_phys}


def cpu_counters():
    class FileTime(ctypes.Structure):
        _fields_ = [('low', ctypes.c_ulong), ('high', ctypes.c_ulong)]
    idle, kernel, user = FileTime(), FileTime(), FileTime()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError()
    def value(x):
        return (x.high << 32) | x.low
    return value(idle), value(kernel), value(user)


def cpu_percent(seconds=1):
    a = cpu_counters()
    time.sleep(seconds)
    b = cpu_counters()
    idle, kernel, user = [y-x for x, y in zip(a, b)]
    total = kernel + user
    if total <= 0:
        raise RuntimeError('GetSystemTimes returned no elapsed processor time')
    return 100.0 * (1.0 - idle / total)


def hashes(datasets, factors):
    result = {}
    for key in datasets:
        ds = old.DATASETS[key]
        result[key] = {}
        for kind, path in [('train', ds.train), ('queries', ds.test(factors[key])),
                           ('ground_truth', ds.gt(factors[key]))]:
            print(f'[{now()}] hashing {key} {kind} ({path.name})', flush=True)
            result[key][kind] = {'file': path.name, 'bytes': path.stat().st_size,
                                 'sha256': old.sha256_file(path)}
    return result


def sample_monitor(stop, dest, errors):
    # Total system load includes the benchmark itself; this is NOT background load.
    try:
        while not stop.is_set():
            sample = {'at': now(), 'total_cpu_percent': cpu_percent(1), **memory_snapshot()}
            append_event(dest, sample)
            stop.wait(4)
    except Exception as exc:
        errors.append(repr(exc))
        stop.set()


def baseline_worker(config_path):
    import numpy as np
    config = json.loads(config_path.read_text(encoding='utf-8'))
    ds = old.DATASETS[config['dataset']]
    folder = config_path.parent
    events = folder / 'measurements.jsonl'
    train, queries, gt, gt_mode = old.load_dataset(ds, config.get('train_limit'), config['factor'])
    args = config
    if config['engine'] == 'hnswlib':
        import hnswlib
        idx = hnswlib.Index(space='cosine', dim=ds.dim)
        idx.init_index(max_elements=train.shape[0], ef_construction=args['efc'], M=args['m'])
        idx.set_num_threads(args['threads'])
        begin = time.perf_counter()
        idx.add_items(train, np.arange(train.shape[0]))
        build = time.perf_counter() - begin
        def query(ef, array):
            idx.set_ef(ef)
            return idx.knn_query(array, k=old.K, num_threads=args['threads'])[0]
    else:
        import faiss
        norms = np.linalg.norm(train, axis=1, keepdims=True)
        np.maximum(norms, np.float32(1e-12), out=norms)
        train /= norms
        queries = old.l2norm(queries)
        faiss.omp_set_num_threads(args['threads'])
        idx = faiss.IndexHNSWFlat(ds.dim, args['m'], faiss.METRIC_INNER_PRODUCT)
        idx.hnsw.efConstruction = args['efc']
        begin = time.perf_counter()
        idx.add(train)
        build = time.perf_counter() - begin
        def query(ef, array):
            idx.hnsw.efSearch = ef
            return idx.search(array, old.K)[1]
    append_event(events, {'event': 'build', 'at': now(), 'seconds': build})
    points = []
    for ef in args['efs']:
        query(ef, queries[:min(10, len(queries))])
        begin = time.perf_counter()
        labels = query(ef, queries)
        elapsed = time.perf_counter() - begin
        hit_counts = np.fromiter((len(set(labels[i].tolist()) & set(gt[i].tolist()))
                                  for i in range(len(queries))), dtype=np.uint8, count=len(queries))
        recall = int(hit_counts.sum()) / (len(queries) * old.K)
        # Save after stopping the timer. This enables independent recall checks.
        np.savez_compressed(folder / f'query_ef{ef}.npz', labels=labels, hit_counts=hit_counts)
        point = {'ef': ef, 'recall_at_10': float(recall), 'qps': len(queries) / elapsed,
                 'latency_ms': elapsed / len(queries) * 1000.0,
                 'elapsed_seconds': elapsed, 'query_count': len(queries)}
        points.append(point)
        append_event(events, {'event': 'query', 'at': now(), **point})
        print(f"{config['dataset']} {config['engine']} ef={ef} recall={recall:.5f} qps={point['qps']:.2f}", flush=True)
    version = old.pkg_version('hnswlib' if config['engine'] == 'hnswlib' else 'faiss-cpu')
    payload = {'schema_version': 2, 'engine': config['engine'], 'engine_version': version,
               'dataset': config['dataset'], 'dim': ds.dim, 'n_train': int(train.shape[0]),
               'n_test': int(len(queries)), 'metric': 'cosine', 'gt_mode': gt_mode,
               'params': {'M': args['m'], 'ef_construction': args['efc'], 'k': old.K},
               'threads': args['threads'], 'repeats': 1, 'build': {'seconds': build},
               'memory': {'kind': 'estimated', 'bytes': int(len(train) * (2 * args['m'] * 4 + ds.dim * 4 + 16))},
               'points': points, 'train_limit': config.get('train_limit'), 'test_factor': config['factor']}
    write_json(Path(config['raw_path']), payload)


def run_tdb(config):
    ds = old.DATASETS[config['dataset']]
    # Inherited experimental flags can silently change both build and search.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('TRIVIUM_')}
    env.update({'RAYON_NUM_THREADS': str(config['threads']), 'TRIVIUM_MT_THREADS': str(config['threads']),
                'TRIVIUM_ANN_NAME': ds.preset, 'TRIVIUM_ANN_DIM': str(ds.dim),
                'TRIVIUM_ANN_TRAIN': str(ds.train), 'TRIVIUM_ANN_TEST': str(ds.test(config['factor'])),
                'TRIVIUM_ANN_GT': str(ds.gt(config['factor'])),
                'TRIVIUM_ANN_EF': ','.join(map(str, config['efs'])), 'TRIVIUM_ANN_M': str(config['m']),
                'TRIVIUM_ANN_EF_CONSTRUCTION': str(config['efc']), 'TRIVIUM_RESULT_PATH': config['raw_path']})
    if config.get('train_limit'):
        env['TRIVIUM_ANN_TRAIN_LIMIT'] = str(config['train_limit'])
    # Run the exact hashed harness=false binary. This also permits terminating the
    # benchmark itself if the monitor fails, instead of only killing cargo.
    return [config['executable_path']], env, old.WORKTREE


def validate_result(config):
    import math
    ds = old.DATASETS[config['dataset']]
    payload = json.loads(Path(config['raw_path']).read_text(encoding='utf-8'))
    expected_n = old.n_rows(ds.train, ds.dim)
    if config.get('train_limit'):
        expected_n = min(expected_n, config['train_limit'])
    expected_q = old.n_rows(ds.test(config['factor']), ds.dim)
    if payload.get('dim') != ds.dim or payload.get('n_train') != expected_n or payload.get('n_test') != expected_q:
        raise ValueError(f'Unexpected dataset shape in {config["raw_path"]}')
    if config['engine'] == 'triviumdb':
        params = payload['parameters']
        actual = payload['measurements']
        efs = [p['ef_search'] for p in actual]
        if params['m'] != config['m'] or params['ef_construction'] != config['efc']:
            raise ValueError('TriviumDB graph parameters differ from requested config')
        if any(p.get('rerank_limit') is not None for p in actual):
            raise ValueError('Unexpected rerank mode')
    else:
        actual = payload['points']
        efs = [p['ef'] for p in actual]
        if payload['threads'] != config['threads'] or payload['engine'] != config['engine']:
            raise ValueError('Unexpected baseline engine or thread count')
        if payload['params']['M'] != config['m'] or payload['params']['ef_construction'] != config['efc']:
            raise ValueError('Baseline graph parameters differ from requested config')
    if len(efs) != len(config['efs']) or set(efs) != set(config['efs']):
        raise ValueError(f'Unexpected ef set: {efs}')
    for point in actual:
        if not math.isfinite(point['qps']) or point['qps'] <= 0 or not 0 <= point['recall_at_10'] <= 1:
            raise ValueError('Invalid QPS or recall value')
    if not math.isfinite(payload['build']['seconds']) or payload['build']['seconds'] <= 0:
        raise ValueError('Invalid build time')


def check_variability(batch, datasets, efs):
    """Gate all builds and every ef QPS, including unreachable datasets."""
    records = report.load_runs(batch / 'raw')
    outcomes = []
    for dataset in datasets:
        for engine in ENGINES:
            group = [r for r in records if r['dataset'] == dataset and r['engine'] == engine]
            failures = []
            if len(group) != 3:
                outcomes.append({'dataset': dataset, 'engine': engine, 'passed': False,
                                 'reasons': [f'expected 3 independent runs, found {len(group)}']})
                continue
            times = [r['build_seconds'] for r in group]
            dispersion = (max(times) - min(times)) / statistics.median(times)
            if dispersion > 0.10:
                failures.append('build dispersion exceeds 10%')
            merged = report.merge_points(group)
            if any(point['samples'] != 3 for point in merged) or {p['ef'] for p in merged} != set(efs):
                failures.append('one or more ef points missing a sample')
            target = report.qps_at_recall(merged, 0.9)
            per_build_targets = [report.qps_at_recall(r['points'], 0.9) for r in group]
            points = []
            for ef in sorted(efs):
                vals = [p['qps'] for r in group for p in r['points'] if p['ef'] == ef]
                if len(vals) != 3 or statistics.mean(vals) <= 0:
                    failures.append(f'ef={ef} has invalid sample count or QPS')
                    continue
                cv = statistics.stdev(vals) / statistics.mean(vals)
                points.append({'ef': ef, 'qps_samples': vals, 'sample_cv': cv})
                if cv > 0.08:
                    failures.append(f'ef={ef} QPS sample CV exceeds 8%')
            outcomes.append({'dataset': dataset, 'engine': engine, 'passed': not failures,
                             'build_seconds': times, 'build_dispersion': dispersion,
                             'at_target_median_curve': target, 'at_target_per_build': per_build_targets,
                             'ef_points': points, 'reasons': failures})
    result = {'created_at': now(), 'passed': all(x['passed'] for x in outcomes),
              'method': 'build (max-min)/median; QPS sample standard deviation / mean at every ef',
              'groups': outcomes}
    write_json(batch / 'variability_review.json', result)
    return result


def run_one(batch, config, max_wait, smoke):
    folder = batch / 'runs' / f"{config['dataset']}__{config['engine']}__r{config['run']}"
    folder.mkdir(parents=True, exist_ok=False)
    gate_path = folder / 'gate.jsonl'
    required = 3 * old.DATASETS[config['dataset']].train.stat().st_size + 8 * (1 << 30)
    if config.get('train_limit'):
        required = 3 * config['train_limit'] * old.DATASETS[config['dataset']].dim * 4 + 8 * (1 << 30)
    deadline = time.monotonic() + max_wait
    while True:
        samples = [cpu_percent(1) for _ in range(3)]
        memory = memory_snapshot()
        passed = max(samples) < 15.0 and memory['available_bytes'] >= required
        append_event(gate_path, {'at': now(), 'cpu_percent_samples': samples, **memory,
                                 'required_available_bytes': required, 'passed': passed,
                                 'smoke_override': bool(smoke and not passed)})
        if passed or smoke:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f'CPU/memory gate did not pass for {folder.name}; no benchmark launched')
        print(f'[{now()}] gate waiting for {folder.name}: cpu={samples}, available={memory["available_bytes"]}, required={required}', flush=True)
        time.sleep(15)
    raw_path = batch / 'raw' / f"{config['dataset']}__{config['engine']}__r{config['run']}.json"
    config['raw_path'] = str(raw_path)
    config_path = folder / 'config.json'
    write_json(config_path, config)
    if config['engine'] == 'triviumdb':
        cmd, env, cwd = run_tdb(config)
    else:
        cmd = [sys.executable, str(Path(__file__).resolve()), '--worker', str(config_path)]
        env, cwd = os.environ.copy(), ROOT
        env.update({'OMP_NUM_THREADS': str(config['threads']), 'OPENBLAS_NUM_THREADS': str(config['threads']),
                    'MKL_NUM_THREADS': str(config['threads'])})
    stop = threading.Event()
    monitor_errors = []
    monitor = threading.Thread(target=sample_monitor, args=(stop, folder / 'system_load.jsonl', monitor_errors), daemon=True)
    print(f'[{now()}] starting {folder.name}', flush=True)
    started = now()
    timer = time.perf_counter()
    monitor.start()
    try:
        with (folder / 'stdout.log').open('x', encoding='utf-8') as log:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            while proc.poll() is None:
                if monitor_errors:
                    proc.terminate()
                    break
                time.sleep(1)
            proc.wait()
    finally:
        stop.set()
        monitor.join()
    validation_error = None
    if not proc.returncode and raw_path.is_file() and not monitor_errors:
        try:
            validate_result(config)
        except Exception as exc:
            validation_error = repr(exc)
    else:
        validation_error = 'process failed, output absent, or monitoring failed'
    result = {'started_at': started, 'ended_at': now(), 'wall_seconds': time.perf_counter()-timer,
              'exit_code': proc.returncode, 'raw_exists': raw_path.exists(), 'monitor_errors': monitor_errors,
              'validation_passed': validation_error is None, 'validation_error': validation_error}
    write_json(folder / 'result.json', result)
    if validation_error:
        raise RuntimeError(f'worker failed validation: {folder}; {validation_error}')
    if config['engine'] == 'triviumdb':
        write_json(raw_path.with_suffix('.meta.json'), {
            'engine': 'triviumdb', 'engine_version': '0.9.0', 'git_rev': EXPECTED_REV,
            'dataset': config['dataset'], 'dim': old.DATASETS[config['dataset']].dim,
            'threads': config['threads'], 'params': {'m': config['m'], 'ef_construction': config['efc'], 'k': old.K},
            'repeats': 3 if not smoke else 1, 'repeat_index': config['run'],
            'test_factor': config['factor'], 'train_limit': config.get('train_limit')})
    print(f'[{now()}] completed {folder.name}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', help='new result folder name; must not already exist')
    parser.add_argument('--datasets', default=','.join(old.DATASETS))
    parser.add_argument('--max-wait', type=int, default=1800, help='seconds to wait for each CPU/memory gate')
    parser.add_argument('--smoke', action='store_true', help='non-publishable reduced smoke; may bypass gate')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return baseline_worker(args.worker)
    if os.name != 'nt':
        raise RuntimeError('This runner requires Windows CPU and memory accounting')
    if not args.tag or not args.tag.replace('-', '').replace('_', '').isalnum():
        raise ValueError('A fresh, simple --tag is required')
    datasets = [x.strip() for x in args.datasets.split(',') if x.strip()]
    if not datasets or any(x not in old.DATASETS for x in datasets):
        raise ValueError('Unknown or empty dataset list')
    if not args.smoke and set(datasets) != set(old.DATASETS):
        raise ValueError('Formal replay requires all four datasets')
    if old.worktree_rev() != EXPECTED_REV:
        raise RuntimeError('Benchmark worktree is not the expected v0.9.0 commit')
    dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=old.WORKTREE,
                           check=True, capture_output=True, text=True, encoding='utf-8').stdout.splitlines()
    if any(line[3:] != 'benches/bench_pipeline_gate.rs' for line in dirty):
        raise RuntimeError(f'Unexpected tracked modifications in benchmark worktree: {dirty}')
    diff = subprocess.run(['git', 'diff', '--binary', 'HEAD'], cwd=old.WORKTREE,
                          check=True, capture_output=True).stdout
    batch = RESULTS / args.tag
    batch.mkdir(exist_ok=False)
    (batch / 'raw').mkdir()
    build_cmd = [old.find_cargo(), 'bench', '--locked', '--bench', 'bench_cohere1m', '--no-run', '--message-format=json']
    build_result = subprocess.run(build_cmd, cwd=old.WORKTREE, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (batch / 'compile.stdout.log').write_text(build_result.stdout, encoding='utf-8')
    (batch / 'compile.stderr.log').write_text(build_result.stderr, encoding='utf-8')
    if build_result.returncode:
        raise RuntimeError('Benchmark compilation failed; see compile logs')
    artifacts = []
    for line in build_result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get('reason') == 'compiler-artifact' and item.get('target', {}).get('name') == 'bench_cohere1m' and item.get('executable'):
            artifacts.append(Path(item['executable']))
    if len(artifacts) != 1 or not artifacts[0].is_file():
        raise RuntimeError(f'Unable to identify compiled benchmark executable: {artifacts}')
    executable = artifacts[0]
    executable_hash = old.sha256_file(executable)
    factors = {}
    for key in datasets:
        ds = old.DATASETS[key]
        factors[key] = 1 if args.smoke else max(1, -(-20000 // old.n_rows(ds.test(), ds.dim)))
    manifest = {'created_at': now(), 'scope': 'ANN only; P1-P6 excluded', 'smoke': args.smoke,
                'datasets': datasets, 'engines': ENGINES, 'rebuilds_per_engine': 1 if args.smoke else 3,
                'query_batches_per_ef_per_build': 1, 'efs': [10, 40] if args.smoke else EFS,
                'threads': 16, 'm': 32, 'ef_construction': 128, 'factors': factors,
                'benchmark_git_rev': EXPECTED_REV, 'platform': platform.platform(),
                'python': sys.version, 'numpy': old.pkg_version('numpy'),
                'hnswlib': old.pkg_version('hnswlib'), 'faiss': old.pkg_version('faiss-cpu'),
                'benchmark_executable': {'file': executable.name, 'sha256': executable_hash},
                'python_executable_sha256': old.sha256_file(Path(sys.executable)),
                'cargo_executable_sha256': old.sha256_file(Path(old.find_cargo())),
                'runner_sha256': old.sha256_file(Path(__file__)),
                'bench090_script_sha256': old.sha256_file(Path(old.__file__)),
                'report090_script_sha256': old.sha256_file(Path(report.__file__)),
                'bench_source_sha256': old.sha256_file(old.WORKTREE / 'benches' / 'bench_cohere1m.rs'),
                'cargo_lock_sha256': old.sha256_file(old.WORKTREE / 'Cargo.lock'),
                'worktree_tracked_changes': dirty,
                'worktree_diff_sha256': hashlib.sha256(diff).hexdigest(),
                'ground_truth_preflight': 'within this batch, between input hash passes',
                'per_query_artifacts': 'baselines: labels and hit counts; TriviumDB: batch aggregate only',
                'system_load_note': 'During-run CPU is total system CPU including benchmark, not background CPU.',
                'timing_boundary': 'TriviumDB measured search includes GT hit counting; baseline QPS excludes recall computation.',
                'gate_boundary': 'Gate is immediately before starting each benchmark process; data loading precedes index construction.'}
    write_json(batch / 'manifest.json', manifest)
    before = hashes(datasets, factors)
    write_json(batch / 'input_hashes_before.json', before)
    if not args.smoke:
        preflight_cmd = [sys.executable, '-u', str(ROOT / 'scripts' / 'bench090' / 'bench090.py'),
                         'check', '--datasets', ','.join(datasets)]
        started = now()
        with (batch / 'groundtruth-check.log').open('x', encoding='utf-8') as log:
            preflight = subprocess.run(preflight_cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        preflight_log = batch / 'groundtruth-check.log'
        preflight_text = preflight_log.read_text(encoding='utf-8')
        write_json(batch / 'groundtruth-check.meta.json', {'started_at': started, 'ended_at': now(),
                   'exit_code': preflight.returncode, 'sha256': old.sha256_file(preflight_log),
                   'command': 'bench090.py check --datasets ' + ','.join(datasets)})
        checks_ok = all(re.search(r'^\s*' + re.escape(key) + r'\s+gt_match=1\.0000\s+.*\[OK\]',
                                  preflight_text, re.MULTILINE) for key in datasets)
        if preflight.returncode or '[FAIL]' in preflight_text or not checks_ok:
            raise RuntimeError('Ground-truth preflight failed; see archived log')
        after_preflight = hashes(datasets, factors)
        write_json(batch / 'input_hashes_after_preflight.json', after_preflight)
        if before != after_preflight:
            raise RuntimeError('Input files changed during ground-truth preflight')
    for dataset in datasets:
        for rep in range(1, (1 if args.smoke else 3) + 1):
            for engine in ENGINES:
                if old.sha256_file(executable) != executable_hash:
                    raise RuntimeError('Benchmark executable changed during the run')
                config = {'dataset': dataset, 'engine': engine, 'run': rep,
                          'threads': 16, 'm': 32, 'efc': 128, 'factor': factors[dataset],
                          'executable_path': str(executable),
                          'efs': [10, 40] if args.smoke else EFS,
                          'train_limit': 1000 if args.smoke else None}
                run_one(batch, config, args.max_wait, args.smoke)
    after = hashes(datasets, factors)
    write_json(batch / 'input_hashes_after.json', after)
    if before != after:
        raise RuntimeError('Input hashes changed during benchmark; evidence is invalid')
    current_diff = subprocess.run(['git', 'diff', '--binary', 'HEAD'], cwd=old.WORKTREE,
                                  check=True, capture_output=True).stdout
    if (old.sha256_file(executable) != executable_hash or
        old.sha256_file(Path(__file__)) != manifest['runner_sha256'] or
        old.sha256_file(Path(old.__file__)) != manifest['bench090_script_sha256'] or
        old.sha256_file(Path(report.__file__)) != manifest['report090_script_sha256'] or
        hashlib.sha256(current_diff).hexdigest() != manifest['worktree_diff_sha256']):
        raise RuntimeError('Executable, scripts, or benchmark worktree changed during replay')
    review = None if args.smoke else check_variability(batch, datasets, EFS)
    write_json(batch / 'completed.json', {'completed_at': now(), 'inputs_unchanged': True,
                                         'status': 'smoke_only' if args.smoke else 'complete_unreviewed',
                                         'variability_passed': None if review is None else review['passed']})
    if review is not None and not review['passed']:
        raise RuntimeError('Variability review failed; retain all samples and rerun the entire failed groups')
    print(f'[{now()}] complete: {batch}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[ERROR] {exc}', file=sys.stderr, flush=True)
        raise

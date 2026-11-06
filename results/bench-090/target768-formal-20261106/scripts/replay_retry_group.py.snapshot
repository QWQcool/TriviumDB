"""Retry one failed ANN dataset/engine group without modifying its source batch.

Use only after replay_complete.py has finished and written variability_review.json.
Attempts are append-only. For a given group, the FIRST complete attempt passing
all gates is the sole eligible replacement. A passing attempt blocks further
attempts. Never combine individual samples from different attempts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path

import replay_complete as runner


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source_inputs(source):
    before = read_json(source / 'input_hashes_before.json')
    after_preflight = read_json(source / 'input_hashes_after_preflight.json')
    after = read_json(source / 'input_hashes_after.json')
    if before != after_preflight or before != after:
        raise RuntimeError('source batch input hash records do not match')
    preflight = read_json(source / 'groundtruth-check.meta.json')
    if preflight['exit_code'] != 0 or preflight['sha256'] != runner.old.sha256_file(source / 'groundtruth-check.log'):
        raise RuntimeError('source ground-truth preflight record is invalid')
    return before


def verify_runtime(manifest, executable):
    old = runner.old
    rev = old.worktree_rev()
    diff = subprocess.run(['git', 'diff', '--binary', 'HEAD'], cwd=old.WORKTREE,
                          capture_output=True, check=True).stdout
    checks = {
        'benchmark_git_rev': rev == manifest['benchmark_git_rev'],
        'worktree_diff_sha256': hashlib.sha256(diff).hexdigest() == manifest['worktree_diff_sha256'],
        'runner_sha256': old.sha256_file(Path(runner.__file__)) == manifest['runner_sha256'],
        'bench090_script_sha256': old.sha256_file(Path(old.__file__)) == manifest['bench090_script_sha256'],
        'report090_script_sha256': old.sha256_file(Path(runner.report.__file__)) == manifest['report090_script_sha256'],
        'benchmark_executable': old.sha256_file(executable) == manifest['benchmark_executable']['sha256'],
        'python_executable_sha256': old.sha256_file(Path(sys.executable)) == manifest['python_executable_sha256'],
        'cargo_executable_sha256': old.sha256_file(Path(old.find_cargo())) == manifest['cargo_executable_sha256'],
        'bench_source_sha256': old.sha256_file(old.WORKTREE / 'benches' / 'bench_cohere1m.rs') == manifest['bench_source_sha256'],
        'cargo_lock_sha256': old.sha256_file(old.WORKTREE / 'Cargo.lock') == manifest['cargo_lock_sha256'],
        'numpy_version': old.pkg_version('numpy') == manifest['numpy'],
        'hnswlib_version': old.pkg_version('hnswlib') == manifest['hnswlib'],
        'faiss_version': old.pkg_version('faiss-cpu') == manifest['faiss'],
    }
    if not all(checks.values()):
        raise RuntimeError(f'runtime differs from source batch: {checks}')
    return checks


def review_group(batch, dataset, engine, efs):
    runs = [r for r in runner.report.load_runs(batch / 'raw')
            if r['dataset'] == dataset and r['engine'] == engine]
    reasons = []
    if len(runs) != 3:
        return {'passed': False, 'reasons': [f'expected 3 runs; found {len(runs)}']}
    build = [r['build_seconds'] for r in runs]
    dispersion = (max(build) - min(build)) / statistics.median(build)
    if dispersion > 0.10:
        reasons.append('build dispersion exceeds 10%')
    points = []
    for ef in efs:
        samples = [p['qps'] for run in runs for p in run['points'] if p['ef'] == ef]
        if len(samples) != 3 or statistics.mean(samples) <= 0:
            reasons.append(f'ef={ef} has invalid sample count or QPS')
            continue
        cv = statistics.stdev(samples) / statistics.mean(samples)
        points.append({'ef': ef, 'qps_samples': samples, 'sample_cv': cv})
        if cv > 0.08:
            reasons.append(f'ef={ef} QPS sample CV exceeds 8%')
    for run in runs:
        if len(run['points']) != len(efs) or {point['ef'] for point in run['points']} != set(efs):
            reasons.append('missing or duplicate ef point in a run')
    merged = runner.report.merge_points(runs)
    return {'passed': not reasons, 'reasons': reasons, 'build_seconds': build,
            'build_dispersion': dispersion, 'ef_points': points,
            'at_target_median_curve': runner.report.qps_at_recall(merged, 0.9),
            'at_target_per_build': [runner.report.qps_at_recall(r['points'], 0.9) for r in runs],
            'method': 'build (max-min)/median; QPS sample standard deviation / mean at every ef'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='completed original batch tag, not a path')
    parser.add_argument('--dataset', required=True, choices=sorted(runner.old.DATASETS))
    parser.add_argument('--engine', required=True, choices=runner.ENGINES)
    parser.add_argument('--max-wait', type=int, default=1800)
    args = parser.parse_args()
    if not args.source.replace('-', '').replace('_', '').isalnum():
        raise ValueError('source must be a simple batch tag')
    source = runner.RESULTS / args.source
    manifest = read_json(source / 'manifest.json')
    completion = read_json(source / 'completed.json')
    if manifest['smoke'] or completion['status'] != 'complete_unreviewed':
        raise RuntimeError('source must be a completed formal batch')
    source_review = read_json(source / 'variability_review.json')
    groups = [g for g in source_review['groups']
              if g['dataset'] == args.dataset and g['engine'] == args.engine]
    if len(groups) != 1 or groups[0]['passed']:
        raise RuntimeError('source group is missing, ambiguous, or did not fail variability review')
    expected_inputs = source_inputs(source)
    original_config = read_json(source / 'runs' /
                                f'{args.dataset}__triviumdb__r1' / 'config.json')
    executable = Path(original_config['executable_path'])
    verify_runtime(manifest, executable)

    retry_root = runner.RESULTS / 'group-retries'
    retry_root.mkdir(exist_ok=True)
    prefix = f'{args.source}__{args.dataset}__{args.engine}__attempt_'
    attempt = 1
    while (retry_root / f'{prefix}{attempt:03d}').exists():
        prior = retry_root / f'{prefix}{attempt:03d}'
        status = prior / 'status.json'
        if not status.exists():
            raise RuntimeError(f'prior attempt has no final status; inspect interruption: {prior}')
        if read_json(status).get('passed'):
            raise RuntimeError(f'first passing retry already exists and must be used: {prior}')
        attempt += 1
    batch = retry_root / f'{prefix}{attempt:03d}'
    batch.mkdir(exist_ok=False)
    (batch / 'raw').mkdir()
    retry_meta = {'created_at': runner.now(), 'source_tag': args.source, 'dataset': args.dataset,
                  'engine': args.engine, 'attempt': attempt,
                  'selection_policy': 'first complete three-run group passing all gates',
                  'source_manifest_sha256': runner.old.sha256_file(source / 'manifest.json'),
                  'source_review_sha256': runner.old.sha256_file(source / 'variability_review.json'),
                  'source_preflight_sha256': runner.old.sha256_file(source / 'groundtruth-check.log'),
                  'retry_wrapper_sha256': runner.old.sha256_file(Path(__file__)),
                  'runtime_limit': 'baseline package versions are checked, but source manifest did not hash their binary extensions'}
    runner.write_json(batch / 'retry_manifest.json', retry_meta)
    try:
        before = runner.hashes(manifest['datasets'], manifest['factors'])
        runner.write_json(batch / 'input_hashes_before.json', before)
        if before != expected_inputs:
            raise RuntimeError('current inputs differ from source batch')
        for rep in range(1, 4):
            verify_runtime(manifest, executable)
            config = {'dataset': args.dataset, 'engine': args.engine, 'run': rep,
                      'threads': manifest['threads'], 'm': manifest['m'], 'efc': manifest['ef_construction'],
                      'factor': manifest['factors'][args.dataset], 'efs': manifest['efs'],
                      'train_limit': None, 'executable_path': str(executable)}
            runner.run_one(batch, config, args.max_wait, False)
        after = runner.hashes(manifest['datasets'], manifest['factors'])
        runner.write_json(batch / 'input_hashes_after.json', after)
        if after != expected_inputs:
            raise RuntimeError('inputs changed during retry')
        verify_runtime(manifest, executable)
        if runner.old.sha256_file(Path(__file__)) != retry_meta['retry_wrapper_sha256']:
            raise RuntimeError('retry wrapper changed during attempt')
        for name, source_file in [('source_manifest_sha256', source / 'manifest.json'),
                                  ('source_review_sha256', source / 'variability_review.json'),
                                  ('source_preflight_sha256', source / 'groundtruth-check.log')]:
            if runner.old.sha256_file(source_file) != retry_meta[name]:
                raise RuntimeError(f'source evidence changed during attempt: {source_file.name}')
        review = review_group(batch, args.dataset, args.engine, manifest['efs'])
        runner.write_json(batch / 'group_review.json', review)
        runner.write_json(batch / 'status.json', {'finished_at': runner.now(), 'completed': True,
                                                  'passed': review['passed'], 'reasons': review['reasons']})
        if not review['passed']:
            raise RuntimeError('complete retry failed variability review; retain all samples')
        print(f'First passing retry: {batch}', flush=True)
    except BaseException as exc:
        if not (batch / 'status.json').exists():
            runner.write_json(batch / 'status.json', {'finished_at': runner.now(), 'completed': False,
                                                      'passed': False, 'error': repr(exc)})
        raise


if __name__ == '__main__':
    main()

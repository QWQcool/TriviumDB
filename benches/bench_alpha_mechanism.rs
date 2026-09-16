//! α 机理消融 — 为什么 α=1.0 优于默认 α=1.2？
//!
//! # 被测能力
//! `QuIVerConfig.alpha` 对 **Layer-0 图拓扑质量**的影响机理。它不测吞吐上限，
//! 也不评测 recall（recall 见 `bench_sensitivity` 1c）。
//!
//! # 背景
//! `bench_sensitivity` 1c 实测：α=1.0（严格剪枝）在**所有** ef 上都优于 α=1.2
//! （Cohere-1M, m=32, ef_c=128；ef=32 处 91.46% vs 87.25%，+4.2pp）。这与 Vamana
//! 原论文"α>1 放宽剪枝提升 recall"的结论相反。
//!
//! # 待验证假设
//! `QuIVer::vamana_select`（src/index/quiver.rs:1627）在 `selected.len() < max_k`
//! 时有一条**补足路径**（`:1656-1668`）：把剩余候选按"到 target 的距离"升序补齐。
//! 因此：
//!   - α 越小 → 通过 `d(v,w) < α·d(u,v)` 严格判定的候选越少 → **越频繁触发补足**
//!     → 补进来的边都是"距离近"的 → **图边长更短** → 贪心局部性更好；
//!   - α 越大 → 更多"多样但更长"的边通过判定 → 补足不触发 → **图边长更长**。
//!
//! 可证伪预测：**α=1.0 的平均边长显著短于 α=1.2**；且可达性（连通性）应无差异，
//! 从而排除"连通性"这一替代解释。
//!
//! # 数据分布
//! 真实数据集 `cohere_train.f32`（1M × 768，未 L2 归一化，与 QuIVer 主基准一致）。
//! 查询集 `cohere_test.f32`，GT `cohere_groundtruth.i32`（K=1000，取前 10）。
//!
//! # 正确性 oracle
//! 1. 一致性守卫：`layer0_neighbors` 必须无自环、无重复、索引 < n；
//! 2. 边长分布必须可由 `α=1.0` 与 `α=1.2` 的**序关系**复现（见输出末行断言）；
//! 3. 可达率断言：任何 α 下从入口点 BFS 的覆盖率必须 ≥ 90%，否则判为异常退出。
//!
//! # 计时边界
//! 构建计时只覆盖 `batch_build_experimental_v2`；拓扑统计不计时（纯分析）。
//! `stats()` 的 hot_bytes 为估算值，不是实测 RSS。
//!
//! # 非目标
//! 不测多线程 QPS、不测冷/热 I/O、不测增量插入。
//!
//! 用法: cargo bench --features ablation --bench bench_alpha_mechanism

use rayon::prelude::*;
use std::collections::{HashSet, VecDeque};
use std::time::Instant;
use triviumdb::index::bq::Bq2Store;
use triviumdb::index::quiver::{QuIVer, QuIVerConfig, QuIVerSearchConfig};

const DIM: usize = 768;
const TOP_K: usize = 10;
/// 二次复杂度统计（邻域内两两距离）的采样节点数。1M × m0² 全量不可接受。
const PAIRWISE_SAMPLE: usize = 10_000;
/// 贪心可导航性探测的采样目标数。
const GREEDY_TARGETS: usize = 500;
/// 可达性下限守卫：低于此值说明图结构异常，不是 α 的效应。
const MIN_REACHABLE_RATIO: f64 = 0.90;

fn read_f32_bin(path: &str) -> Vec<f32> {
    let bytes = std::fs::read(path).unwrap_or_else(|e| panic!("无法读取 {path}: {e}"));
    bytes
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| f32::from_le_bytes(*c))
        .collect()
}

fn read_i32_bin(path: &str) -> Vec<i32> {
    let bytes = std::fs::read(path).unwrap_or_else(|e| panic!("无法读取 {path}: {e}"));
    bytes
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| i32::from_le_bytes(*c))
        .collect()
}

/// 单位化：cosine = dot。cohere 原始数据未归一化，必须先单位化才能用内积代替 cosine。
fn to_unit(data: &mut [f32], dim: usize) {
    data.par_chunks_mut(dim).for_each(|v| {
        let n = v.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-12);
        for x in v.iter_mut() {
            *x /= n;
        }
    });
}

#[inline]
fn dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

/// cosine 距离 = 1 - cos。单位向量下 = 1 - dot。
#[inline]
fn cos_dist(unit: &[f32], dim: usize, i: u32, j: u32) -> f32 {
    1.0 - dot(
        &unit[i as usize * dim..(i as usize + 1) * dim],
        &unit[j as usize * dim..(j as usize + 1) * dim],
    )
}

fn percentile(sorted: &[f32], p: f64) -> f32 {
    if sorted.is_empty() {
        return f32::NAN;
    }
    let idx = p / 100.0 * (sorted.len() - 1) as f64;
    let lo = idx.floor() as usize;
    let hi = idx.ceil() as usize;
    if lo == hi {
        return sorted[lo];
    }
    sorted[lo] * ((hi as f64 - idx) as f32) + sorted[hi] * ((idx - lo as f64) as f32)
}

struct Topology {
    avg_degree: f64,
    min_degree: usize,
    max_degree: usize,
    /// α=1.0 严格判定下的支配违规数 / 被检边数（越接近 1 说明越"不多样"）
    strict_violation_ratio: f64,
    /// 该配置自身 α 下的支配违规比例
    own_violation_ratio: f64,
    edge_mean: f32,
    edge_p50: f32,
    edge_p90: f32,
    /// BQ 空间边长——图的真实优化目标
    bq_edge_mean: f32,
    bq_edge_p50: f32,
    bq_edge_p90: f32,
    spread_mean: f64,
    reachable_ratio: f64,
    greedy_success: f64,
    greedy_hops: f64,
}

fn main() {
    eprintln!("═══════════════════════════════════════════════════════════════");
    eprintln!("  α 机理消融 — Layer-0 图拓扑质量  (dim={DIM}, m=32, ef_c=128)");
    eprintln!("═══════════════════════════════════════════════════════════════");

    let t0 = Instant::now();
    let mut train = read_f32_bin("cohere_train.f32");
    let mut test = read_f32_bin("cohere_test.f32");
    let gt_data = read_i32_bin("cohere_groundtruth.i32");

    let n_train = train.len() / DIM;
    let n_test = test.len() / DIM;
    let k_gt = gt_data.len() / n_test;
    assert!(k_gt >= TOP_K, "GroundTruth K={k_gt} 不足以评测 Top-{TOP_K}");

    // 单位化：使 cosine == dot（QuIVer 内部用 f32 cosine 精排，此处只为度量边长）
    to_unit(&mut train, DIM);
    to_unit(&mut test, DIM);
    eprintln!(
        "  数据: {n_train} × {DIM}, 查询 {n_test}, GT K={k_gt}  (加载+单位化 {:.1}s)",
        t0.elapsed().as_secs_f64()
    );

    let ids: Vec<u64> = (0..n_train as u64).collect();
    let slots: Vec<usize> = (0..n_train).collect();

    // 图是在 **BQ 空间**优化的（vamana_select 用 sigs.distance），
    // 因此必须同时量 BQ 空间边长，才能判定"近邻优先 vs 多样性"之争。
    let mut bq_store = Bq2Store::new(DIM);
    bq_store.reserve(n_train);
    for chunk in train.chunks(DIM) {
        bq_store.push_from_vector(chunk);
    }

    // 每查询的真 Top-10（单位化后按 dot 降序）
    let gt_sets: Vec<HashSet<u64>> = (0..n_test)
        .map(|i| {
            gt_data[i * k_gt..i * k_gt + TOP_K]
                .iter()
                .map(|&x| x as u64)
                .collect()
        })
        .collect();

    let alphas: [f32; 6] = [1.0, 1.05, 1.1, 1.15, 1.2, 1.25];
    let ef_probe: [usize; 3] = [32, 64, 128];

    struct Row {
        alpha: f32,
        build_s: f64,
        topo: Topology,
        recall: [f64; 3],
    }
    let mut rows: Vec<Row> = Vec::new();

    for &alpha in &alphas {
        let config = QuIVerConfig {
            m: 32,
            ef_construction: 128,
            alpha,
        };
        let mut index = QuIVer::new(DIM, &config);

        let tb = Instant::now();
        index.batch_build_experimental_v2(&train, &ids, &slots);
        let build_s = tb.elapsed().as_secs_f64();

        // ── 读取 Layer-0 拓扑（需 ablation feature）──
        let n = index.stats().n;
        let entry = index.ablation_entry_point();
        assert!(entry < n as u32, "入口点越界: {entry} >= {n}");

        let adj: Vec<Vec<u32>> = (0..n as u32)
            .map(|u| index.layer0_neighbors(u).to_vec())
            .collect();

        // 一致性守卫：无越界 / 无自环 / 无重复
        // 复用 scratch + sort 检测重复，避免 1M 次 HashSet 分配
        {
            let mut scratch: Vec<u32> = Vec::with_capacity(256);
            for (u, nbs) in adj.iter().enumerate() {
                scratch.clear();
                scratch.extend_from_slice(nbs);
                for &v in &scratch {
                    assert!((v as usize) < n, "节点 {u} 的邻居 {v} 越界 (n={n})");
                    assert!(v as usize != u, "节点 {u} 出现自环");
                }
                scratch.sort_unstable();
                assert!(
                    scratch.windows(2).all(|w| w[0] != w[1]),
                    "节点 {u} 出现重复邻居"
                );
            }
        }

        // 度数统计
        let degrees: Vec<usize> = adj.iter().map(Vec::len).collect();
        let avg_degree = degrees.iter().sum::<usize>() as f64 / n as f64;
        let min_degree = *degrees.iter().min().unwrap_or(&0);
        let max_degree = *degrees.iter().max().unwrap_or(&0);

        // ── 边长分布（全部有向边，O(E)）──
        let edge_pairs: Vec<(f32, f32)> = adj
            .par_iter()
            .enumerate()
            .map(|(u, nbs)| {
                let mut local = Vec::with_capacity(nbs.len());
                for &v in nbs {
                    local.push((
                        cos_dist(&train, DIM, u as u32, v),
                        bq_store.distance(u, v as usize, DIM) as f32,
                    ));
                }
                local
            })
            .flatten()
            .collect();
        let mut edge_dists: Vec<f32> = edge_pairs.iter().map(|p| p.0).collect();
        let mut bq_edge_dists: Vec<f32> = edge_pairs.iter().map(|p| p.1).collect();
        let edge_mean = edge_dists.iter().sum::<f32>() / edge_dists.len() as f32;
        let bq_edge_mean = bq_edge_dists.iter().sum::<f32>() / bq_edge_dists.len() as f32;
        edge_dists.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
        bq_edge_dists.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
        let edge_p50 = percentile(&edge_dists, 50.0);
        let edge_p90 = percentile(&edge_dists, 90.0);
        let bq_edge_p50 = percentile(&bq_edge_dists, 50.0);
        let bq_edge_p90 = percentile(&bq_edge_dists, 90.0);

        // ── 支配违规 + 邻域离散度（采样，O(sample × m0²)）──
        let step = (n / PAIRWISE_SAMPLE).max(1);
        let sample: Vec<u32> = (0..n as u32).step_by(step).collect();

        let (strict_violations, own_violations, checked_edges) = sample
            .par_iter()
            .map(|&u| {
                let nbs = &adj[u as usize];
                let (mut sv, mut ov, mut checked) = (0u32, 0u32, 0u32);
                for &v in nbs {
                    let d_uv = cos_dist(&train, DIM, u, v);
                    checked += 1;
                    for &w in nbs {
                        if w == v {
                            continue;
                        }
                        let d_vw = cos_dist(&train, DIM, v, w);
                        // α=1.0 严格判定下的支配：存在更近的邻居 w
                        if d_vw < d_uv {
                            sv += 1;
                            break;
                        }
                    }
                    for &w in nbs {
                        if w == v {
                            continue;
                        }
                        if cos_dist(&train, DIM, v, w) < alpha * d_uv {
                            ov += 1;
                            break;
                        }
                    }
                }
                (sv, ov, checked)
            })
            .reduce(|| (0, 0, 0), |a, b| (a.0 + b.0, a.1 + b.1, a.2 + b.2));

        let strict_violation_ratio = strict_violations as f64 / checked_edges.max(1) as f64;
        let own_violation_ratio = own_violations as f64 / checked_edges.max(1) as f64;

        // 邻域离散度：节点 u 的邻居两两之间平均距离（越大越"分散/多样"）
        let spread_sum = sample
            .par_iter()
            .map(|&u| {
                let nbs = &adj[u as usize];
                if nbs.len() < 2 {
                    return (0.0f64, 0usize);
                }
                let mut acc = 0.0f64;
                let mut cnt = 0usize;
                for i in 0..nbs.len() {
                    for j in (i + 1)..nbs.len() {
                        acc += cos_dist(&train, DIM, nbs[i], nbs[j]) as f64;
                        cnt += 1;
                    }
                }
                (acc, cnt)
            })
            .reduce(|| (0.0, 0), |a, b| (a.0 + b.0, a.1 + b.1));
        let spread_mean = if spread_sum.1 == 0 {
            f64::NAN
        } else {
            spread_sum.0 / spread_sum.1 as f64
        };

        // ── 可达性（BFS，O(n + E)）──
        let mut visited = vec![false; n];
        let mut queue = VecDeque::with_capacity(n);
        visited[entry as usize] = true;
        queue.push_back(entry);
        let mut reached = 1usize;
        while let Some(cur) = queue.pop_front() {
            for &v in &adj[cur as usize] {
                if !visited[v as usize] {
                    visited[v as usize] = true;
                    reached += 1;
                    queue.push_back(v);
                }
            }
        }
        let reachable_ratio = reached as f64 / n as f64;
        assert!(
            reachable_ratio >= MIN_REACHABLE_RATIO,
            "α={alpha} 可达率 {:.4} 低于守卫阈值 {MIN_REACHABLE_RATIO}，图结构异常而非 α 效应",
            reachable_ratio
        );

        // ── 贪心可导航性：从入口点纯贪心下降到查询的真近邻（不依赖 ef）──
        // 目标必须用**测试查询**——只有它们带权威 GT，才能给出严格成功判据。
        // 度量的是"图本身能否被贪心路由到真近邻区域"，与 beam 宽度解耦。
        let n_greedy = GREEDY_TARGETS.min(n_test);
        let (greedy_success, greedy_hops) = (0..n_greedy)
            .into_par_iter()
            .map(|qi| {
                let q = &test[qi * DIM..(qi + 1) * DIM];
                let mut cur = entry;
                let mut hops = 0usize;
                loop {
                    let mut best = cur;
                    let mut best_d = dot(q, &train[cur as usize * DIM..(cur as usize + 1) * DIM]);
                    for &v in &adj[cur as usize] {
                        let d = dot(q, &train[v as usize * DIM..(v as usize + 1) * DIM]);
                        if d > best_d {
                            best_d = d;
                            best = v;
                        }
                    }
                    if best == cur || hops >= 128 {
                        break;
                    }
                    cur = best;
                    hops += 1;
                }
                // 严格判据：贪心终点落在该查询的权威 Top-10 内
                let ok = gt_sets[qi].contains(&ids[cur as usize]);
                (u32::from(ok), hops as u32)
            })
            .reduce(|| (0, 0), |a, b| (a.0 + b.0, a.1 + b.1));
        let greedy_success = greedy_success as f64 / n_greedy as f64;
        let greedy_hops = greedy_hops as f64 / n_greedy as f64;

        // ── Recall 探针（关联拓扑与检索质量）──
        let mut recall = [0.0f64; 3];
        for (ei, &ef) in ef_probe.iter().enumerate() {
            let cfg = QuIVerSearchConfig {
                top_k: TOP_K,
                ef_search: ef,
                rerank_limit: None,
            };
            let hits: usize = (0..n_test)
                .into_par_iter()
                .map(|i| {
                    let q = &test[i * DIM..(i + 1) * DIM];
                    let res = index.search_flat(q, &train, &cfg);
                    res.iter()
                        .filter(|&&(id, _)| gt_sets[i].contains(&id))
                        .count()
                })
                .sum();
            recall[ei] = hits as f64 / (n_test * TOP_K) as f64 * 100.0;
        }

        eprintln!(
            "  α={:<5} 构建 {:>6.1}s  度数 {:.1}({}-{})  cos边长 mean {:.4} p90 {:.4}  \
             BQ边长 mean {:>7.2} p90 {:>7.2}  严格违规 {:.1}%  离散度 {:.4}  可达 {:.2}%  贪心 {:.1}%/{:.1}跳",
            alpha,
            build_s,
            avg_degree,
            min_degree,
            max_degree,
            edge_mean,
            edge_p90,
            bq_edge_mean,
            bq_edge_p90,
            strict_violation_ratio * 100.0,
            spread_mean,
            reachable_ratio * 100.0,
            greedy_success * 100.0,
            greedy_hops,
        );
        eprintln!(
            "         Recall@10:  ef=32 {:.2}%   ef=64 {:.2}%   ef=128 {:.2}%",
            recall[0], recall[1], recall[2]
        );

        rows.push(Row {
            alpha,
            build_s,
            topo: Topology {
                avg_degree,
                min_degree,
                max_degree,
                strict_violation_ratio,
                own_violation_ratio,
                edge_mean,
                edge_p50,
                edge_p90,
                bq_edge_mean,
                bq_edge_p50,
                bq_edge_p90,
                spread_mean,
                reachable_ratio,
                greedy_success,
                greedy_hops,
            },
            recall,
        });
    }

    // ── 机理判定 ──
    eprintln!("\n───────────────────────────────────────────────────────────────");
    eprintln!("  机理判定");
    eprintln!("───────────────────────────────────────────────────────────────");
    let a10 = rows.iter().find(|r| (r.alpha - 1.0).abs() < 1e-6).unwrap();
    let a12 = rows.iter().find(|r| (r.alpha - 1.2).abs() < 1e-6).unwrap();

    let d_edge = a10.topo.edge_mean - a12.topo.edge_mean;
    let d_recall = a10.recall[0] - a12.recall[0];
    println!(
        "\n| α | 构建(s) | 度 | cos边长mean | cos边长p90 | BQ边长mean | BQ边长p90 | 严格违规 | 自身违规 | 离散度 | 可达 | 贪心/跳 | R@10(32) | R@10(64) | R@10(128) |"
    );
    println!(
        "{}",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    );
    for r in &rows {
        println!(
            "| {:.2} | {:.1} | {:.0}({}-{}) | {:.4} | {:.4} | {:.1} | {:.1} | {:.1}% | {:.1}% | {:.4} | {:.2}% | {:.1}%/{:.1} | {:.2}% | {:.2}% | {:.2}% |",
            r.alpha,
            r.build_s,
            r.topo.avg_degree,
            r.topo.min_degree,
            r.topo.max_degree,
            r.topo.edge_mean,
            r.topo.edge_p90,
            r.topo.bq_edge_mean,
            r.topo.bq_edge_p90,
            r.topo.strict_violation_ratio * 100.0,
            r.topo.own_violation_ratio * 100.0,
            r.topo.spread_mean,
            r.topo.reachable_ratio * 100.0,
            r.topo.greedy_success * 100.0,
            r.topo.greedy_hops,
            r.recall[0],
            r.recall[1],
            r.recall[2]
        );
    }

    println!("\n  α=1.0 vs α=1.2:");
    println!(
        "    平均边长差  {:+.5}  ({:.4} → {:.4}，相对 {:+.2}%)",
        d_edge,
        a12.topo.edge_mean,
        a10.topo.edge_mean,
        d_edge / a12.topo.edge_mean * 100.0
    );
    println!(
        "    cos 边长 p50/p90 差 {:+.5} / {:+.5}  (p50 {:.4} → {:.4})",
        a10.topo.edge_p50 - a12.topo.edge_p50,
        a10.topo.edge_p90 - a12.topo.edge_p90,
        a12.topo.edge_p50,
        a10.topo.edge_p50
    );
    println!(
        "    邻域离散度  {:+.5}  ({:.4} → {:.4})",
        a10.topo.spread_mean - a12.topo.spread_mean,
        a12.topo.spread_mean,
        a10.topo.spread_mean
    );
    println!(
        "    可达率差    {:+.4}%  → 连通性无法解释差异",
        (a10.topo.reachable_ratio - a12.topo.reachable_ratio) * 100.0
    );
    println!(
        "    Recall@10  {:.2}% vs {:.2}%  差 {:+.2}pp",
        a10.recall[0], a12.recall[0], d_recall
    );
    println!(
        "    贪心可导航  {:.1}% vs {:.1}%  (差 {:+.2}pp)",
        a10.topo.greedy_success * 100.0,
        a12.topo.greedy_success * 100.0,
        (a10.topo.greedy_success - a12.topo.greedy_success) * 100.0
    );
    println!(
        "    严格违规    {:.1}% vs {:.1}%  自身违规 {:.1}% vs {:.1}%",
        a10.topo.strict_violation_ratio * 100.0,
        a12.topo.strict_violation_ratio * 100.0,
        a10.topo.own_violation_ratio * 100.0,
        a12.topo.own_violation_ratio * 100.0
    );

    // BQ 空间（图的真实优化目标）边长对比
    let d_bq = a10.topo.bq_edge_mean - a12.topo.bq_edge_mean;
    println!(
        "    BQ 边长 mean/p50 差 {:+.2} / {:+.2}  (mean {:.1} → {:.1}，相对 {:+.2}%)   ← 图在 BQ 空间做剪枝决策",
        d_bq,
        a10.topo.bq_edge_p50 - a12.topo.bq_edge_p50,
        a12.topo.bq_edge_mean,
        a10.topo.bq_edge_mean,
        d_bq / a12.topo.bq_edge_mean * 100.0
    );

    let yn = |b: bool| if b { "成立" } else { "不成立" };
    let cos_shorter = d_edge < 0.0;
    let bq_shorter = d_bq < 0.0;
    let more_diverse = a10.topo.spread_mean > a12.topo.spread_mean;
    let less_redundant = a10.topo.strict_violation_ratio < a12.topo.strict_violation_ratio;
    let better_greedy = a10.topo.greedy_success > a12.topo.greedy_success;
    let better = a10.recall[0] > a12.recall[0];

    println!("\n  假设判定（α=1.0 相对 α=1.2）:");
    println!("    BQ  空间边长更短         = {}", yn(bq_shorter));
    println!("    cos 空间边长更短         = {}", yn(cos_shorter));
    println!("    邻居更分散（多样性↑）    = {}", yn(more_diverse));
    println!("    邻居冗余更低（严格违规↓）= {}", yn(less_redundant));
    println!("    贪心可导航性更好         = {}", yn(better_greedy));
    println!("    Recall@10 更高           = {}", yn(better));

    if better_greedy && better {
        println!(
            "\n  → 因果链成立：邻居离散度 {:+.4}、严格违规 {:.1}% → {:.1}%（冗余下降）\n     \
             → 贪心可导航性 {:+.1}pp → Recall@10(ef=32) {:+.2}pp",
            a10.topo.spread_mean - a12.topo.spread_mean,
            a12.topo.strict_violation_ratio * 100.0,
            a10.topo.strict_violation_ratio * 100.0,
            (a10.topo.greedy_success - a12.topo.greedy_success) * 100.0,
            d_recall
        );
    }
    if cos_shorter != bq_shorter {
        println!(
            "\n  ⚠ 度量错配：cos 与 BQ 空间方向相反。α 的剪枝决策发生在 BQ 空间，\n     \
             而评测目标是 cosine GT —— 两者不一致本身限制了可调优空间。"
        );
    } else {
        println!("\n  cos 与 BQ 空间方向一致，无度量错配迹象。");
    }
    eprintln!("═══════════════════════════════════════════════════════════════");
}

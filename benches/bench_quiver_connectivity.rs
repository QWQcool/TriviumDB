//! 入口可达性、独立余弦召回和查询成本的固定种子诊断。
//! 使用 release 构建、单个 Rayon 线程运行；结果不替代真实大规模数据集验收。
use std::collections::VecDeque;
use std::time::Instant;
use triviumdb::index::quiver::{QuIVer, QuIVerConfig, QuIVerSearchConfig};
fn next(seed: &mut u64) -> f32 {
    *seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
    ((*seed >> 32) as u32 as f64 / u32::MAX as f64 * 2. - 1.) as f32
}
fn data(kind: &str, n: usize, dim: usize, query: bool) -> Vec<f32> {
    let mut seed = if query { 918274u64 } else { 918273u64 };
    let mut rows = vec![0.; n * dim];
    for i in 0..n {
        for c in 0..dim {
            rows[i * dim + c] = if kind == "退化" || kind == "低维" {
                let index = if query {
                    (i as f32 + 0.5) * 2048.0 / n as f32
                } else {
                    (i + 1) as f32
                };
                let a = index * 0.013 + if query { 0.003 } else { 0. };
                [a.cos(), a.sin(), 0.25][c % 3]
            } else {
                next(&mut seed)
            };
        }
    }
    if kind == "近重复" {
        for i in 1..64.min(n) {
            for c in 0..dim {
                rows[i * dim + c] = rows[c] + i as f32 * 1e-7 * (c + 1) as f32 / dim as f32;
            }
        }
    }
    if kind == "聚簇" {
        let mut seed = 721u64;
        let centers = (0..16 * dim).map(|_| next(&mut seed)).collect::<Vec<_>>();
        for i in 0..n {
            for c in 0..dim {
                rows[i * dim + c] = centers[(i % 16) * dim + c] + rows[i * dim + c] * 0.015;
            }
        }
    }
    rows
}
fn cosine(a: &[f32], b: &[f32]) -> f64 {
    let mut dot = 0.;
    let mut aa = 0.;
    let mut bb = 0.;
    for (&x, &y) in a.iter().zip(b) {
        let (x, y) = (x as f64, y as f64);
        dot += x * y;
        aa += x * x;
        bb += y * y;
    }
    dot / (aa * bb).sqrt()
}
fn main() {
    let mode = std::env::args()
        .skip(1)
        .find(|argument| !argument.starts_with('-'))
        .unwrap_or_else(|| "当前源码".to_owned());
    for (kind, dim) in [
        ("随机65", 65),
        ("随机768", 768),
        ("随机3072", 3072),
        ("低维", 3),
        ("退化", 768),
        ("近重复", 65),
        ("聚簇", 128),
    ] {
        let n = 2048;
        let nq = 128;
        let base = data(kind, n, dim, false);
        let queries = data(kind, nq, dim, true);
        let ids = (1..=n as u64).collect::<Vec<_>>();
        let slots = (0..n).collect::<Vec<_>>();
        let mut build_times = Vec::new();
        let mut graph = None;
        for _ in 0..3 {
            let mut g = QuIVer::new(dim, &QuIVerConfig::default());
            let start = Instant::now();
            g.batch_build_experimental_v2(&base, &ids, &slots);
            build_times.push(start.elapsed().as_secs_f64());
            graph = Some(g);
        }
        let graph = graph.unwrap();
        assert!(
            graph.default_sm_l2_enabled(),
            "基准必须使用默认 SM-L2 查询路径"
        );
        let mut seen = vec![false; n];
        let mut queue = VecDeque::from([graph.ablation_entry_point()]);
        seen[queue[0] as usize] = true;
        while let Some(u) = queue.pop_front() {
            for &v in graph.layer0_neighbors(u) {
                if !seen[v as usize] {
                    seen[v as usize] = true;
                    queue.push_back(v);
                }
            }
        }
        let mut hash = 14695981039346656037u64;
        for u in 0..n {
            for &v in graph.layer0_neighbors(u as u32) {
                hash ^= v as u64;
                hash = hash.wrapping_mul(1099511628211);
            }
            hash ^= u as u64;
            hash = hash.wrapping_mul(1099511628211);
        }
        let thresholds = queries
            .chunks_exact(dim)
            .map(|query| {
                let mut exact = base
                    .chunks_exact(dim)
                    .map(|row| cosine(query, row))
                    .collect::<Vec<_>>();
                exact.sort_unstable_by(|a, b| b.total_cmp(a));
                exact[9]
            })
            .collect::<Vec<_>>();
        for ef in [32, 64, 128, 256] {
            let config = QuIVerSearchConfig {
                top_k: 10,
                ef_search: ef,
                rerank_limit: Some(64),
            };
            let run = |qi: usize| {
                let q = &queries[qi * dim..(qi + 1) * dim];
                graph.search(
                    q,
                    |slot, buffer| {
                        buffer.clear();
                        buffer.extend_from_slice(&base[slot * dim..(slot + 1) * dim]);
                        true
                    },
                    &config,
                )
            };
            let mut hits = 0;
            for qi in 0..nq {
                let q = &queries[qi * dim..(qi + 1) * dim];
                for (id, _) in run(qi) {
                    if cosine(q, &base[(id as usize - 1) * dim..id as usize * dim]) + 1e-6
                        >= thresholds[qi]
                    {
                        hits += 1;
                    }
                }
            }
            for qi in 0..nq {
                std::hint::black_box(run(qi));
            }
            let mut times = Vec::new();
            let mut throughput = Vec::new();
            for _ in 0..5 {
                let batch = Instant::now();
                for qi in 0..nq {
                    let start = Instant::now();
                    std::hint::black_box(run(qi));
                    times.push(start.elapsed().as_secs_f64() * 1e6);
                }
                throughput.push(nq as f64 / batch.elapsed().as_secs_f64());
            }
            times.sort_unstable_by(f64::total_cmp);
            throughput.sort_unstable_by(f64::total_cmp);
            build_times.sort_unstable_by(f64::total_cmp);
            println!(
                "{}",
                serde_json::json!({"方案":mode,"数据":kind,"维度":dim,"节点数":n,"查询数":nq,"ef":ef,"精排上限":64,"并列容差":1e-6,"可达":seen.iter().filter(|&&v|v).count(),"图哈希":format!("{hash:016x}"),"召回10":hits as f64/(nq*10) as f64,"QPS中位数":throughput[2],"P50微秒":times[times.len()/2],"P95微秒":times[times.len()*95/100],"P99微秒":times[times.len()*99/100],"构图秒中位数":build_times[1],"热内存字节":graph.stats().hot_bytes})
            );
        }
    }
}

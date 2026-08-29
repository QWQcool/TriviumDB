#![allow(non_snake_case)]
//! 非向量路径（文档过滤 / 图遍历）稳定性与规模化性能基线
//!
//! 与既有测试的分工：
//!   - `tql_parser.rs` / `tql_executor.rs` / `tql_dml.rs`：TQL 语法与执行的正确性
//!   - `benches/bench_queries.rs`：5k–10k 规模的 Criterion 性能基准
//!   - 本文件：正确性 + 10k / 100k / 1M 三档规模的延迟采样与尾延迟统计
//!     （avg / p50 / p95 / p99 / p999），填补 10 万级以上非向量查询的基线空白
//!
//! 性能采样默认 `#[ignore]`，避免拖慢常规 CI。需要时执行：
//!
//! ```text
//! cargo test --release --test non_vector_stability -- --ignored --nocapture
//! ```

use std::time::Instant;
use triviumdb::database::{Config, Database, StorageMode};

const DIM: usize = 8;

fn tmp_db(name: &str) -> String {
    let dir = std::env::temp_dir().join("triviumdb_test");
    std::fs::create_dir_all(&dir).ok();
    dir.join(format!("nvs_{}", name))
        .to_string_lossy()
        .to_string()
}

fn cleanup(path: &str) {
    for ext in &["", ".wal", ".vec", ".lock", ".flush_ok"] {
        std::fs::remove_file(format!("{}{}", path, ext)).ok();
    }
}

fn open_rom_db(name: &str) -> (Database<f32>, String) {
    let path = tmp_db(name);
    cleanup(&path);
    let config = Config {
        dim: DIM,
        storage_mode: StorageMode::Rom,
        ..Default::default()
    };
    let db = Database::<f32>::open_with_config(&path, config).unwrap();
    (db, path)
}

fn fill_payload_nodes(db: &mut Database<f32>, count: usize) {
    for i in 0..count {
        let v = [
            (i % 100) as f32 / 50.0 - 1.0,
            (i % 50) as f32 / 25.0 - 1.0,
            (i % 10) as f32 / 5.0 - 1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ];
        let region = match i % 4 {
            0 => "cn",
            1 => "us",
            2 => "jp",
            _ => "eu",
        };
        let payload = serde_json::json!({
            "type": if i % 3 == 0 { "person" } else { "event" },
            "age": (i % 80) as i64 + 1,
            "region": region,
            "idx": i,
            "tags": vec!["a", "b", "c"],
        });
        db.insert(&v, payload).unwrap();
    }
}

fn build_match_graph(db: &mut Database<f32>, mid_count: usize, leaves_per_mid: usize) {
    let root = db
        .insert(
            &[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            serde_json::json!({"type": "root"}),
        )
        .unwrap();
    let mut mids = Vec::with_capacity(mid_count);
    for i in 0..mid_count {
        let v = [
            0.5,
            i as f32 / mid_count.max(1) as f32,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ];
        let mid = db
            .insert(&v, serde_json::json!({"type": "mid", "idx": i}))
            .unwrap();
        db.link(root, mid, "NEXT", 1.0).unwrap();
        mids.push(mid);
    }
    for (i, mid) in mids.iter().enumerate() {
        for j in 0..leaves_per_mid {
            let leaf_idx = i * leaves_per_mid + j;
            let v = [
                0.0,
                i as f32 / mid_count.max(1) as f32,
                j as f32 / leaves_per_mid.max(1) as f32,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ];
            let leaf = db
                .insert(&v, serde_json::json!({"type": "leaf", "idx": leaf_idx}))
                .unwrap();
            db.link(*mid, leaf, "NEXT", 1.0).unwrap();
        }
    }
}

fn percentile(samples: &[std::time::Duration], p: f64) -> std::time::Duration {
    if samples.is_empty() {
        return std::time::Duration::ZERO;
    }
    let idx = ((samples.len() as f64 - 1.0) * p / 100.0).round() as usize;
    samples[idx]
}

fn bench_find_scale(name: &str, count: usize, iters: usize) {
    let (mut db, path) = open_rom_db(name);
    fill_payload_nodes(&mut db, count);
    db.flush().unwrap();

    let queries = [
        r#"FIND {type: "person"} RETURN * LIMIT 100"#,
        r#"FIND {region: "cn", age: {$gte: 30}} RETURN * LIMIT 100"#,
        r#"FIND {$or: [{type: "event"}, {age: {$lt: 10}}]} RETURN * LIMIT 100"#,
    ];

    for q in queries {
        for _ in 0..3 {
            let _ = db.tql(q).unwrap();
        }
        let mut samples = Vec::with_capacity(iters);
        for _ in 0..iters {
            let start = Instant::now();
            let rows = db.tql(q).unwrap();
            samples.push(start.elapsed());
            assert!(!rows.is_empty());
        }
        samples.sort_unstable();
        let total = samples
            .iter()
            .copied()
            .fold(std::time::Duration::ZERO, |a, b| a + b);
        let avg = total / samples.len() as u32;
        eprintln!(
            "FIND_{} query={} avg={:?} p50={:?} p95={:?} p99={:?} p999={:?} qps={:.0}",
            count,
            q,
            avg,
            percentile(&samples, 50.0),
            percentile(&samples, 95.0),
            percentile(&samples, 99.0),
            percentile(&samples, 99.9),
            samples.len() as f64 / total.as_secs_f64()
        );
    }

    drop(db);
    cleanup(&path);
}

fn bench_match_scale(name: &str, mid_count: usize, leaves_per_mid: usize, iters: usize) {
    let (mut db, path) = open_rom_db(name);
    build_match_graph(&mut db, mid_count, leaves_per_mid);
    db.flush().unwrap();

    let q1 = r#"MATCH (a {type: "root"})-[:NEXT]->(b) RETURN b LIMIT 100"#;
    let q2 = r#"MATCH (a {type: "root"})-[:NEXT]->(b)-[:NEXT]->(c) RETURN c LIMIT 100"#;

    for q in [q1, q2] {
        for _ in 0..2 {
            let _ = db.tql(q).unwrap();
        }
        let mut samples = Vec::with_capacity(iters);
        for _ in 0..iters {
            let start = Instant::now();
            let rows = db.tql(q).unwrap();
            samples.push(start.elapsed());
            assert!(!rows.is_empty());
        }
        samples.sort_unstable();
        let total = samples
            .iter()
            .copied()
            .fold(std::time::Duration::ZERO, |a, b| a + b);
        let avg = total / samples.len() as u32;
        eprintln!(
            "MATCH_{} query={} avg={:?} p50={:?} p95={:?} p99={:?} p999={:?} qps={:.0}",
            leaves_per_mid * mid_count,
            q,
            avg,
            percentile(&samples, 50.0),
            percentile(&samples, 95.0),
            percentile(&samples, 99.0),
            percentile(&samples, 99.9),
            samples.len() as f64 / total.as_secs_f64()
        );
    }

    drop(db);
    cleanup(&path);
}


#[test]
fn NVS_文档过滤_小规模正确性() {
    let (mut db, path) = open_rom_db("find_small");
    fill_payload_nodes(&mut db, 1_000);
    db.flush().unwrap();

    // 等值过滤
    let persons = db.tql(r#"FIND {type: "person"} RETURN *"#).unwrap();
    let persons_expected = (0..1000).filter(|i| i % 3 == 0).count();
    assert_eq!(persons.len(), persons_expected);

    // 范围 + 逻辑组合
    let rows = db
        .tql(r#"FIND {$and: [{type: "event"}, {age: {$gte: 20, $lt: 40}}]} RETURN *"#)
        .unwrap();
    let expected = (0..1000)
        .filter(|i| i % 3 != 0 && (i % 80 + 1) >= 20 && (i % 80 + 1) < 40)
        .count();
    assert_eq!(rows.len(), expected);

    // 排序分页
    let page = db
        .tql(r#"FIND {type: "person"} RETURN * ORDER BY _.idx DESC LIMIT 5"#)
        .unwrap();
    assert_eq!(page.len(), 5);
    let max_idx = page
        .iter()
        .map(|r| r["_"].payload["idx"].as_i64().unwrap())
        .max()
        .unwrap();
    assert!(max_idx < 1000);

    drop(db);
    cleanup(&path);
    eprintln!("NVS_FIND_SMALL_OK");
}

#[test]
fn NVS_图遍历_小规模正确性() {
    let (mut db, path) = open_rom_db("match_small");
    // 构造 3 层星型图：0 -> 1..=50 -> 51..=1000
    let root = db
        .insert(&[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], serde_json::json!({"type": "root"}))
        .unwrap();
    let mut mids = Vec::new();
    for i in 1..=50 {
        let v = [
            0.5,
            i as f32 / 50.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ];
        let mid = db
            .insert(&v, serde_json::json!({"type": "mid", "idx": i}))
            .unwrap();
        db.link(root, mid, "NEXT", 1.0).unwrap();
        mids.push(mid);
    }
    for (i, mid) in mids.iter().enumerate() {
        for j in 0..20 {
            let idx = i * 20 + j;
            if idx >= 950 {
                break;
            }
            let v = [
                0.0,
                idx as f32 / 1000.0,
                0.2,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ];
            let leaf = db
                .insert(&v, serde_json::json!({"type": "leaf", "idx": idx}))
                .unwrap();
            db.link(*mid, leaf, "NEXT", 1.0).unwrap();
        }
    }
    db.flush().unwrap();

    // 两跳路径数量 = 中间节点数 * 20（950 个叶子）
    let rows = db
        .tql(r#"MATCH (a {type: "root"})-[:NEXT]->(b)-[:NEXT]->(c) RETURN c"#)
        .unwrap();
    assert_eq!(rows.len(), 950);

    // 可变长路径 1..2 跳至少返回 root + mids + leaves
    let rows = db
        .tql(r#"MATCH (a {type: "root"})-[:NEXT*1..2]->(b) RETURN b"#)
        .unwrap();
    assert!(rows.len() >= 1000, "expected >=1000, got {}", rows.len());

    drop(db);
    cleanup(&path);
    eprintln!("NVS_MATCH_SMALL_OK");
}

#[test]
#[ignore]
fn NVS_文档过滤_10k性能采样() {
    bench_find_scale("find_10k", 10_000, 50);
}

#[test]
#[ignore]
fn NVS_图遍历_10k性能采样() {
    bench_match_scale("match_10k", 100, 100, 20);
}

#[test]
#[ignore]
fn NVS_文档过滤_100k性能采样() {
    bench_find_scale("find_100k", 100_000, 20);
}

#[test]
#[ignore]
fn NVS_文档过滤_1M性能采样() {
    bench_find_scale("find_1m", 1_000_000, 10);
}

#[test]
#[ignore]
fn NVS_图遍历_100k性能采样() {
    bench_match_scale("match_100k", 100, 1_000, 10);
}

#[test]
#[ignore]
fn NVS_图遍历_1M性能采样() {
    bench_match_scale("match_1m", 1_000, 1_000, 5);
}


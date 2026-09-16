//! T2 摸底 —— QuIVer 图**构建成本**基线（为 PiPNN 分区式构建做改造前量化）
//!
//! # 为什么需要这个基准
//! L1 冻结基线只记录了**总量**（`build.seconds = 34.43`，29,043 vec/s），
//! 既没有阶段分解，也**完全没有增量插入数据**（`incremental_batch_percent: 100`）。
//! 而 `bootstrap-report.md` R4 指出：`insert` 走**急式反向重剪**（每条反向边跑一次完整
//! `vamana_select`，单次 `O(m0³·C)`），批量路径却是**惰性剪枝** + `final_prune`。
//! 这个不对称正是 PiPNN 分区的潜在靶点，但**从未被测量过**。
//!
//! # 本基准产出四组数据
//! | 段 | 内容 | 为什么要 |
//! |---|---|---|
//! | **A** | 批量建图墙钟 + 五段式 CPU 分解 | 用 `TRIVIUM_BUILD_PROFILE=1` 打开仓库自带的
//!         `BuildProfile`（`quiver.rs:285`），定位 34s 花在哪 |
//! | **B** | 惰性 vs 急式反向剪枝 A/B | `TRIVIUM_EAGER_PRUNE=1` 是仓库自带开关
//!         （`quiver.rs:2379`），直接隔离"剪枝时机"的代价 |
//! | **C** | **增量 `insert` 延迟**（均值/中位/p99）+ 与批量每向量成本的倍差 | 补上 L1 的空白；
//!         判定 R4 的 `O(m0³·C)` 在实测中的量级 |
//! | **D** | L0 邻接导出为 CSR 二进制 | 供 Python 做**分区质量预实验**（跨分区边率 / GT 同分区率）|
//!
//! # 安全边界
//! - 不修改 `src/`；只读调用 + 写 `.tmp/` 下的导出文件
//! - **阶段 B 需要外部设置环境变量**（`std::env::set_var` 在 Rust 2024 是 `unsafe`，
//!   且与并发读 env 不兼容），故本基准只**读取并标注**当前模式，A/B 由外层跑两次完成
//!
//! # 守卫
//! 1. **可复现冻结基线**：默认模式下 1M 建图的 vec/s 必须落在冻结值 29,043 的 ±8% 内，
//!    否则导出的图不是冻结基线那张图，后续分区结论不可用
//! 2. **导出完整性**：CSR `offsets` 单调不减、`adj` 无自环、`entry` 在范围内、
//!    边总数与 `offsets[n]` 一致
//!
//! # 环境变量
//! - `T2_N`    建图规模（默认 1000000）
//! - `T2_INS`  增量插入计时样本数（默认 200）
//! - `T2_DUMP` 导出路径（默认 `.tmp/l0_csr.bin`）
//! - `TRIVIUM_BUILD_PROFILE=1` 打开仓库自带建图探针
//!
//! 用法:
//! ```text
//! # 默认（惰性剪枝）
//! cargo bench --features ablation --bench bench_t2_build_recon
//! # 急式剪枝对照
//! $env:TRIVIUM_EAGER_PRUNE="1"; cargo bench --features ablation --bench bench_t2_build_recon
//! ```

use std::io::Write;
use std::time::Instant;
use triviumdb::index::quiver::{QuIVer, QuIVerConfig};

const DIM: usize = 768;
/// `m = 32` → `m0 = 2m = 64`（`quiver.rs:1000`）。仅用于写入导出头。
const M0: usize = 64;

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn read_f32_bin(path: &str) -> Vec<f32> {
    let b = std::fs::read(path).unwrap_or_else(|e| panic!("无法读取 {path}: {e}"));
    b.as_chunks::<4>()
        .0
        .iter()
        .map(|c| f32::from_le_bytes(*c))
        .collect()
}

fn l2_normalize(data: &mut [f32]) {
    use rayon::prelude::*;
    let n = data.len() / DIM;
    let norms: Vec<f32> = (0..n)
        .into_par_iter()
        .map(|i| {
            data[i * DIM..(i + 1) * DIM]
                .iter()
                .map(|x| x * x)
                .sum::<f32>()
                .sqrt()
        })
        .collect();
    let data_ptr = data.as_mut_ptr() as usize;
    (0..n).into_par_iter().for_each(|i| {
        // SAFETY: 各线程只写自己那一段，区间互不重叠
        let seg =
            unsafe { std::slice::from_raw_parts_mut((data_ptr as *mut f32).add(i * DIM), DIM) };
        let inv = 1.0 / norms[i].max(1e-12);
        for x in seg.iter_mut() {
            *x *= inv;
        }
    });
}

fn main() {
    // 让仓库自带的 BuildProfile（tracing::info!）能真正输出
    let _ = tracing_subscriber::fmt()
        .with_env_filter("info")
        .with_writer(std::io::stderr)
        .try_init();

    let n_target = env_usize("T2_N", 1_000_000);
    let n_ins = env_usize("T2_INS", 200);
    let dump_path = std::env::var("T2_DUMP").unwrap_or_else(|_| ".tmp/l0_csr.bin".into());
    let eager = std::env::var("TRIVIUM_EAGER_PRUNE").as_deref() == Ok("1");

    eprintln!("═══════════════════════════════════════════════════════════════════");
    eprintln!("  T2 摸底 — QuIVer 图构建成本基线");
    eprintln!(
        "  规模 N={n_target}  增量样本={n_ins}  反向剪枝模式={}",
        if eager {
            "eager 急式 (TRIVIUM_EAGER_PRUNE=1)"
        } else {
            "lazy 惰性 (默认)"
        }
    );
    eprintln!("═══════════════════════════════════════════════════════════════════");

    let t0 = Instant::now();
    let mut train = read_f32_bin("cohere_train.f32");
    let n_all = train.len() / DIM;
    assert!(n_target <= n_all, "T2_N={n_target} 超出数据量 {n_all}");
    l2_normalize(&mut train);
    eprintln!(
        "  数据 {n_all} × {DIM}，归一化 + 加载 {:.2}s",
        t0.elapsed().as_secs_f64()
    );

    // ── 阶段 A/B：批量建图（阶段分解由仓库自带 BuildProfile 输出）──
    let config = QuIVerConfig {
        m: 32,
        ef_construction: 128,
        alpha: 1.2,
    };
    let mut index = QuIVer::new(DIM, &config);
    let ids: Vec<u64> = (0..n_target as u64).collect();
    let slots: Vec<usize> = (0..n_target).collect();

    let build_data = &train[..n_target * DIM];
    let tb = Instant::now();
    index.batch_build_experimental_v2(build_data, &ids, &slots);
    let build_s = tb.elapsed().as_secs_f64();
    let vps = n_target as f64 / build_s;
    let st = index.stats();
    eprintln!("\n  ── 阶段 A/B: 批量建图 ──");
    eprintln!(
        "  墙钟 {build_s:.2}s  {vps:.0} vec/s  Hot {} MiB",
        st.hot_bytes / 1024 / 1024
    );

    // 守卫 1：可复现冻结基线（仅默认规模 + 惰性模式下检查）
    const FROZEN_VPS: f64 = 29_043.0;
    if n_target == 1_000_000 && !eager {
        let dev = (vps - FROZEN_VPS).abs() / FROZEN_VPS * 100.0;
        eprintln!(
            "  守卫1 可复现冻结基线: {vps:.0} vs {FROZEN_VPS:.0} vec/s（偏差 {dev:.1}%）{}",
            if dev <= 8.0 { "PASS" } else { "FAIL" }
        );
        assert!(dev <= 8.0, "守卫1 失败: 建图性能偏离冻结基线 {dev:.1}%");
    } else {
        eprintln!("  守卫1 跳过（仅默认规模 1M + 惰性模式检查）");
    }

    // ── 阶段 C：增量 insert 延迟 ──
    eprintln!("\n  ── 阶段 C: 增量 insert 延迟（N={n_target}）──");
    let n_ins = n_ins.min(n_all - n_target);
    if n_ins == 0 {
        eprintln!("  无可用增量样本，跳过");
    } else {
        let mut lcg = 0x2545_F491_4F6C_DD1Du64;
        let mut lat_us: Vec<f64> = Vec::with_capacity(n_ins);
        for k in 0..n_ins {
            let gi = n_target + k;
            let v = &train[gi * DIM..(gi + 1) * DIM];
            let t = Instant::now();
            index.insert(v, gi as u64, gi, &mut lcg);
            lat_us.push(t.elapsed().as_secs_f64() * 1e6);
        }
        lat_us.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let mean = lat_us.iter().sum::<f64>() / lat_us.len() as f64;
        let med = lat_us[lat_us.len() / 2];
        let p99 = lat_us[(lat_us.len() as f64 * 0.99) as usize % lat_us.len()];
        let min = lat_us[0];
        let max = lat_us[lat_us.len() - 1];
        let batch_us_per_vec = 1e6 / vps;
        eprintln!(
            "  insert 延迟 (μs): 中位 {med:.1}  均值 {mean:.1}  p99 {p99:.1}  范围 [{min:.1}, {max:.1}]"
        );
        eprintln!(
            "  批量每向量 {batch_us_per_vec:.1} μs → **增量/批量 = {:.0}×**",
            med / batch_us_per_vec
        );
        eprintln!(
            "  外推：若全量 1M 用 insert 建成，约需 {:.0} 分钟（单线程）",
            med * n_target as f64 / 1e6 / 60.0
        );
        println!("\n### T2 阶段 C: 增量 insert 延迟（N={n_target}, 样本 {n_ins}）\n");
        println!("| 指标 | 值 |");
        println!("|---|---|");
        println!(
            "| 反向剪枝模式 | {} |",
            if eager { "eager" } else { "lazy" }
        );
        println!("| 中位延迟 | {med:.1} μs |");
        println!("| 均值延迟 | {mean:.1} μs |");
        println!("| p99 延迟 | {p99:.1} μs |");
        println!("| 批量每向量 | {batch_us_per_vec:.1} μs |");
        println!("| **增量/批量倍差** | **{:.0}×** |", med / batch_us_per_vec);
    }

    // ── 阶段 D：导出 L0 CSR 供分区质量预实验 ──
    eprintln!("\n  ── 阶段 D: 导出 L0 CSR ──");
    let final_stats = index.stats();
    let n_final = final_stats.n;
    let mut offsets: Vec<u32> = Vec::with_capacity(n_final + 1);
    let mut adj: Vec<u32> = Vec::new();
    let mut self_loops = 0usize;
    offsets.push(0);
    for v in 0..n_final as u32 {
        for &nb in index.layer0_neighbors(v) {
            if nb == v {
                self_loops += 1;
            }
            adj.push(nb);
        }
        offsets.push(adj.len() as u32);
    }
    let entry = index.ablation_entry_point();

    // 守卫 2：导出完整性
    let monotone = offsets.windows(2).all(|w| w[0] <= w[1]);
    let in_range = adj.iter().all(|&x| (x as usize) < n_final);
    assert!(monotone, "守卫2 失败: CSR offsets 非单调");
    assert!(in_range, "守卫2 失败: 邻居索引越界");
    assert_eq!(self_loops, 0, "守卫2 失败: 存在 {self_loops} 个自环");
    assert!((entry as usize) < n_final, "守卫2 失败: entry 越界");
    eprintln!(
        "  守卫2 导出完整性 PASS: n={n_final} 边={} 平均度 {:.1}（stats: {:.1}）自环 0 entry={entry}",
        adj.len(),
        adj.len() as f64 / n_final as f64,
        final_stats.avg_degree_l0
    );

    if let Some(dir) = std::path::Path::new(&dump_path).parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    {
        let mut f = std::fs::File::create(&dump_path)
            .unwrap_or_else(|e| panic!("无法创建 {dump_path}: {e}"));
        f.write_all(b"T2CS").unwrap();
        f.write_all(&(n_final as u32).to_le_bytes()).unwrap();
        f.write_all(&(M0 as u32).to_le_bytes()).unwrap();
        f.write_all(&entry.to_le_bytes()).unwrap();
        f.write_all(&(adj.len() as u64).to_le_bytes()).unwrap();
        for o in &offsets {
            f.write_all(&o.to_le_bytes()).unwrap();
        }
        for a in &adj {
            f.write_all(&a.to_le_bytes()).unwrap();
        }
    }
    let mb = (24 + offsets.len() * 4 + adj.len() * 4) as f64 / 1e6;
    eprintln!("  已导出 {dump_path}  ({mb:.0} MB)");

    eprintln!("\n═══════════════════════════════════════════════════════════════════");
}

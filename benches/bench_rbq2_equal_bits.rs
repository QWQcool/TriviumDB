//! RaBitQ vs BQ2 — **等比特公平对照** + 误差界统计（T1 基准修正）
//!
//! # 为什么需要这个基准
//! 原 `bench_rbq2_precision.rs` 有三处硬伤使结论不可用（详见
//! `docs/research/l1-baseline.md` §6）：
//!   1. **位预算不对等**：BQ2 是 2 bit/维，RaBitQ 只给 1 bit/维。
//!      `bench_encoding_ablation` 实测 1-bit→2-bit 值 +8.7pp Recall@10，
//!      所以"BQ2 胜 RaBitQ"首先是比特多的结果。
//!   2. **数据未 L2 归一化**：`prepare_all.py` 的 `hf_bin` 路径不做归一化
//!      （`scripts/prepare_all.py:303-328`），而该基准直接用原始数据。
//!   3. **RaBitQ 逐向量因子与尺度不变度量错配**：原式
//!      `f_rescale = -‖x‖²/(0.5‖x‖₁)` 把模长注射进 cosine 排序，
//!      把 asym 从 53.30% 压到 23.35%（已逐位复现）。
//!
//! # 本基准的修正
//!   - **统一 L2 归一化**后再编码（cosine 是尺度不变的，归一化是前提）；
//!   - **按比特预算分组对比**：1 bit 组 vs 2 bit 组，组内才是公平比较；
//!   - **正确的 RaBitQ 估计量**（详见下文推导）；
//!   - 新增**误差界统计**：RaBitQ 的真正价值不是更准，而是**有可证明的误差上界**。
//!
//! # 正确的 RaBitQ 估计量推导（单位向量）
//! 设 `x_u = x/‖x‖`（单位），二进制码 `x_b = sign(x_u)/√D`，则 `‖x_b‖ = 1`，
//! `⟨x_b, x_u⟩ = ‖x_u‖₁/√D`。RaBitQ 的最优重建为
//! ```text
//!   x̄ = ⟨x_b, x_u⟩ · x_b / ‖x_b‖²      （x_u 在 x_b 方向上的投影）
//!   ⟨q_u, x̄⟩ = (‖x_u‖₁ / D) · Σᵢ q_u[i]·sign(x_u[i])
//! ```
//! 其误差由 Cauchy–Schwarz 给出**可计算的闭式上界**：
//! ```text
//!   |⟨q_u, x̄⟩ − ⟨q_u, x_u⟩| ≤ ‖q_u‖·‖x_u − x̄‖ = ε(x)
//!   ε(x)² = ‖x_u‖² − ⟨x_u, x̄⟩ = 1 − ‖x_u‖₁² / D
//! ```
//! `ε(x)` 是**每向量一个标量**，可与估计值一同传播 —— 这正是
//! `src/tsng.rs` 的 `TsngSearchMetrics` 目前完全缺失的"导航可靠性"量。
//!
//! # 数据分布
//! `cohere_train.f32` / `cohere_test.f32`（真实数据集），**本基准内部做 L2 归一化**。
//!
//! # 正确性 oracle
//! 1. 归一化守卫：单位化后每行 L2 范数 ∈ [1−1e-4, 1+1e-4]；
//! 2. 误差界有效性：`|est − true| ≤ ε(x) + 1e-4` 必须对**全部**被检样本成立，
//!    任何违例即判为估计量实现错误（不是数据问题）；
//! 3. 安全剪枝零假阴性：被 `est+ε < LB_k` 剪掉的候选**不得**出现在真实 Top-K 中。
//!
//! # 计时边界
//! 只测"编码耗时"与"单次距离/估计耗时"（ns/call）。端到端 QPS 不在本基准范围
//! （见 `bench_encoding_ablation` Phase 2）。
//!
//! # 非目标
//! 不做图索引、不做大规模可扩展性、不替代 `bench_encoding_ablation`。
//!
//! 用法: cargo bench --bench bench_rbq2_equal_bits

use rayon::prelude::*;
use std::collections::HashSet;
use std::time::Instant;

const DIM: usize = 768;
/// 训练集规模：与原 rbq2 基准对齐，便于直接对拍。
const N_TRAIN: usize = 100_000;
const N_QUERIES: usize = 200;
const KS: [usize; 4] = [1, 10, 100, 500];

// ══════════════════════════════════════════════════════════════════
//  旋转器 —— 逐位复刻原基准的 FhtKacRotator（已证为正交变换）
//  范数与内积精确保持，见 docs/research/l1-baseline.md §6.4
// ══════════════════════════════════════════════════════════════════

struct FhtKacRotator {
    flips: [Vec<u8>; 4],
    trunc_dim: usize,
    padded_dim: usize,
    fac: f32,
}

impl FhtKacRotator {
    fn new(dim: usize, seed: u64) -> Self {
        let padded_dim = (dim + 63) & !63;
        let log2 = (usize::BITS - 1) - dim.leading_zeros();
        let trunc_dim = 1usize << log2;
        let fac = 1.0 / (trunc_dim as f32).sqrt();
        let mut state = seed;
        let bytes_per_flip = padded_dim / 8;
        let mut flips = [
            vec![0u8; bytes_per_flip],
            vec![0u8; bytes_per_flip],
            vec![0u8; bytes_per_flip],
            vec![0u8; bytes_per_flip],
        ];
        for flip in &mut flips {
            for byte in flip.iter_mut() {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                *byte = state as u8;
            }
        }
        Self {
            flips,
            trunc_dim,
            padded_dim,
            fac,
        }
    }

    fn rotate(&self, src: &[f32]) -> Vec<f32> {
        let mut data = vec![0.0f32; self.padded_dim];
        let copy_len = src.len().min(self.padded_dim);
        data[..copy_len].copy_from_slice(&src[..copy_len]);
        let start = self.padded_dim - self.trunc_dim;

        if self.trunc_dim == self.padded_dim {
            for round in 0..4 {
                flip_sign(&self.flips[round], &mut data);
                fht_in_place(&mut data[..self.trunc_dim]);
                vec_rescale(&mut data[..self.trunc_dim], self.fac);
            }
        } else {
            flip_sign(&self.flips[0], &mut data);
            fht_in_place(&mut data[..self.trunc_dim]);
            vec_rescale(&mut data[..self.trunc_dim], self.fac);
            kacs_walk(&mut data);

            flip_sign(&self.flips[1], &mut data);
            fht_in_place(&mut data[start..start + self.trunc_dim]);
            vec_rescale(&mut data[start..start + self.trunc_dim], self.fac);
            kacs_walk(&mut data);

            flip_sign(&self.flips[2], &mut data);
            fht_in_place(&mut data[..self.trunc_dim]);
            vec_rescale(&mut data[..self.trunc_dim], self.fac);
            kacs_walk(&mut data);

            flip_sign(&self.flips[3], &mut data);
            fht_in_place(&mut data[start..start + self.trunc_dim]);
            vec_rescale(&mut data[start..start + self.trunc_dim], self.fac);
            kacs_walk(&mut data);

            vec_rescale(&mut data, 0.25);
        }
        data
    }
}

fn flip_sign(flip: &[u8], data: &mut [f32]) {
    for (byte_idx, &byte) in flip.iter().enumerate() {
        if byte == 0 {
            continue;
        }
        for bit in 0..8 {
            let i = byte_idx * 8 + bit;
            if i < data.len() && (byte >> bit) & 1 != 0 {
                data[i] = -data[i];
            }
        }
    }
}

fn fht_in_place(x: &mut [f32]) {
    let n = x.len();
    let mut h = 1;
    while h < n {
        for i in (0..n).step_by(h * 2) {
            for j in i..i + h {
                let a = x[j];
                let b = x[j + h];
                x[j] = a + b;
                x[j + h] = a - b;
            }
        }
        h *= 2;
    }
}

fn vec_rescale(data: &mut [f32], fac: f32) {
    for v in data.iter_mut() {
        *v *= fac;
    }
}

fn kacs_walk(data: &mut [f32]) {
    let half = data.len() / 2;
    for i in 0..half {
        let a = data[i];
        let b = data[i + half];
        data[i] = a + b;
        data[i + half] = a - b;
    }
}

// ══════════════════════════════════════════════════════════════════
//  1 bit/dim 组
// ══════════════════════════════════════════════════════════════════

/// 无旋转 1-bit：仅符号位。Hamming 距离可用 popcount 加速。
struct Sign1 {
    bits: Vec<u64>,
}

fn encode_sign1(x: &[f32]) -> Sign1 {
    let chunks = x.len().div_ceil(64);
    let mut bits = vec![0u64; chunks];
    for (i, &v) in x.iter().enumerate() {
        if v > 0.0 {
            bits[i / 64] |= 1u64 << (i % 64);
        }
    }
    Sign1 { bits }
}

fn hamming(a: &Sign1, b: &Sign1) -> u32 {
    a.bits
        .iter()
        .zip(b.bits.iter())
        .map(|(x, y)| (x ^ y).count_ones())
        .sum()
}

// ══════════════════════════════════════════════════════════════════
//  RaBitQ 1-bit（旋转后）—— 正确的非对称估计量 + 误差界
// ══════════════════════════════════════════════════════════════════

struct RaBitQ1 {
    bits: Vec<u64>,
    /// ‖x_u‖₁ / D —— 正确的 RaBitQ 逐向量因子（归一化数据上）
    factor: f32,
    /// ε(x) = sqrt(1 − ‖x_u‖₁²/D) —— 可证明的误差上界
    epsilon: f32,
}

fn encode_rabitq1(x_rotated: &[f32], dim: usize) -> RaBitQ1 {
    let chunks = dim.div_ceil(64);
    let mut bits = vec![0u64; chunks];
    let mut l1 = 0.0f32;
    for i in 0..dim {
        let v = x_rotated[i];
        if v > 0.0 {
            bits[i / 64] |= 1u64 << (i % 64);
        }
        l1 += v.abs();
    }
    let factor = l1 / dim as f32;
    let epsilon = (1.0 - (l1 * l1) / dim as f32).max(0.0).sqrt();
    RaBitQ1 {
        bits,
        factor,
        epsilon,
    }
}

/// 单位向量上的 RaBitQ 非对称估计：`⟨q_u, x̄⟩ = factor · Σ q_i·sign(x_i)`。
///
/// 若 q 未归一化（如原始查询），结果整体乘 `‖q‖`，等价于按 `‖q‖` 缩放；
/// 同一查询内排序不变。返回**未加 ‖q‖ 因子**的值。
fn rabitq1_estimate(q_rot: &[f32], db: &RaBitQ1, dim: usize) -> f32 {
    let mut acc = 0.0f32;
    for i in 0..dim {
        // sign(x_i) ∈ {+1, −1}，由 bit 给出
        let s = if (db.bits[i / 64] >> (i % 64)) & 1 == 1 {
            1.0f32
        } else {
            -1.0f32
        };
        acc += q_rot[i] * s;
    }
    db.factor * acc
}

/// 对称 1-bit（对照）：Hamming on sign(旋转后)
fn rabitq1_sym(q_rot: &[f32], db: &RaBitQ1, dim: usize) -> u32 {
    let mut d = 0u32;
    for i in 0..dim {
        let qb = q_rot[i] > 0.0;
        let xb = (db.bits[i / 64] >> (i % 64)) & 1 == 1;
        if qb != xb {
            d += 1;
        }
    }
    d
}

// ══════════════════════════════════════════════════════════════════
//  2 bit/dim 组
// ══════════════════════════════════════════════════════════════════

struct Bq2 {
    pos: Vec<u64>,
    strong: Vec<u64>,
}

fn encode_bq2(x: &[f32]) -> Bq2 {
    let dim = x.len();
    let chunks = dim.div_ceil(64);
    let alpha = x.iter().map(|v| v.abs()).sum::<f32>() / dim as f32;
    let mut pos = vec![0u64; chunks];
    let mut strong = vec![0u64; chunks];
    for (i, &v) in x.iter().enumerate() {
        if v > 0.0 {
            pos[i / 64] |= 1u64 << (i % 64);
        }
        if v.abs() > alpha {
            strong[i / 64] |= 1u64 << (i % 64);
        }
    }
    Bq2 { pos, strong }
}

/// 2-bit 加权点积（越大越近）。权重 4/2/1。
fn bq2_dot(a: &Bq2, b: &Bq2, dim: usize) -> i32 {
    let chunks = dim.div_ceil(64);
    let valid_last = if dim.is_multiple_of(64) {
        !0u64
    } else {
        (1u64 << (dim % 64)) - 1
    };
    let mut dot = 0i32;
    for i in 0..chunks {
        let mask = if i == chunks - 1 { valid_last } else { !0u64 };
        let same = !(a.pos[i] ^ b.pos[i]) & mask;
        let diff = (a.pos[i] ^ b.pos[i]) & mask;
        let both_s = a.strong[i] & b.strong[i] & mask;
        let one_s = (a.strong[i] ^ b.strong[i]) & mask;
        let both_w = !(a.strong[i] | b.strong[i]) & mask;
        dot += 4 * (same & both_s).count_ones() as i32;
        dot -= 4 * (diff & both_s).count_ones() as i32;
        dot += 2 * (same & one_s).count_ones() as i32;
        dot -= 2 * (diff & one_s).count_ones() as i32;
        dot += (same & both_w).count_ones() as i32;
        dot -= (diff & both_w).count_ones() as i32;
    }
    dot
}

/// 2-bit 标量量化（对照）：每 2 bit 表示一个区间索引，L1 距离。
struct Sq2 {
    codes: Vec<u8>,
}

fn encode_sq2(x: &[f32], lo: f32, hi: f32) -> Sq2 {
    let span = (hi - lo).max(1e-12);
    let codes = x
        .iter()
        .map(|&v| (((v - lo) / span * 4.0).floor().clamp(0.0, 3.0)) as u8)
        .collect();
    Sq2 { codes }
}

fn sq2_l1(a: &Sq2, b: &Sq2) -> u32 {
    a.codes
        .iter()
        .zip(b.codes.iter())
        .map(|(x, y)| x.abs_diff(*y) as u32)
        .sum()
}

// ══════════════════════════════════════════════════════════════════
//  工具
// ══════════════════════════════════════════════════════════════════

fn read_f32_bin(path: &str) -> Vec<f32> {
    let bytes = std::fs::read(path).unwrap_or_else(|e| panic!("无法读取 {path}: {e}"));
    bytes
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| f32::from_le_bytes(*c))
        .collect()
}

/// 就地 L2 归一化。返回归一化前的范数（用于守卫断言）。
fn l2_normalize(data: &mut [f32], dim: usize) -> Vec<f32> {
    let n = data.len() / dim;
    let norms: Vec<f32> = (0..n)
        .into_par_iter()
        .map(|i| {
            let seg = &data[i * dim..(i + 1) * dim];
            seg.iter().map(|x| x * x).sum::<f32>().sqrt()
        })
        .collect();
    data.par_chunks_mut(dim)
        .zip(norms.par_iter())
        .for_each(|(seg, &nrm)| {
            let inv = 1.0 / nrm.max(1e-12);
            for x in seg.iter_mut() {
                *x *= inv;
            }
        });
    norms
}

fn topk_desc(scores: &[f32], k: usize) -> Vec<usize> {
    let mut v: Vec<(usize, f32)> = scores.iter().enumerate().map(|(i, &s)| (i, s)).collect();
    v.sort_unstable_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then(a.0.cmp(&b.0)));
    v.truncate(k);
    v.into_iter().map(|(i, _)| i).collect()
}

fn topk_asc_f32(scores: &[f32], k: usize) -> Vec<usize> {
    let mut v: Vec<(usize, f32)> = scores.iter().enumerate().map(|(i, &s)| (i, s)).collect();
    v.sort_unstable_by(|a, b| a.1.partial_cmp(&b.1).unwrap().then(a.0.cmp(&b.0)));
    v.truncate(k);
    v.into_iter().map(|(i, _)| i).collect()
}

fn overlap(a: &[usize], b: &[usize]) -> usize {
    let set: HashSet<usize> = a.iter().copied().collect();
    b.iter().filter(|x| set.contains(x)).count()
}

fn mean_of(v: &[f64]) -> f64 {
    if v.is_empty() {
        0.0
    } else {
        v.iter().sum::<f64>() / v.len() as f64
    }
}

// ══════════════════════════════════════════════════════════════════

fn main() {
    eprintln!("═══════════════════════════════════════════════════════════════════");
    eprintln!("  RaBitQ vs BQ2 — 等比特公平对照 + 误差界统计（T1 基准修正）");
    eprintln!("═══════════════════════════════════════════════════════════════════");

    let t0 = Instant::now();
    let mut train = read_f32_bin("cohere_train.f32");
    let mut test = read_f32_bin("cohere_test.f32");
    let n_train_total = train.len() / DIM;
    let n_test_total = test.len() / DIM;
    train.truncate(N_TRAIN.min(n_train_total) * DIM);
    test.truncate(N_QUERIES.min(n_test_total) * DIM);
    let n_train = train.len() / DIM;
    let n_q = test.len() / DIM;

    // ── 修正 2：统一 L2 归一化（原基准缺失）──
    let train_norms_before = l2_normalize(&mut train, DIM);
    let _ = l2_normalize(&mut test, DIM);

    // 守卫 1：归一化后范数必须为 1
    for (i, seg) in train.chunks(DIM).enumerate() {
        let nrm = seg.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!(
            (nrm - 1.0).abs() < 1e-4,
            "归一化守卫失败: 第 {i} 行范数 {nrm} 偏离 1"
        );
    }
    let raw_norm_cv = {
        let m = mean_of(
            &train_norms_before
                .iter()
                .map(|&x| x as f64)
                .collect::<Vec<_>>(),
        );
        let sd = (mean_of(
            &train_norms_before
                .iter()
                .map(|&x| (x as f64 - m).powi(2))
                .collect::<Vec<_>>(),
        ))
        .sqrt();
        sd / m
    };
    eprintln!(
        "  修正2 归一化: 训练 {n_train} × {DIM}, 查询 {n_q}；归一化前 ‖x‖ 变异系数 = {raw_norm_cv:.4}"
    );
    eprintln!("  加载+归一化耗时 {:.2}s", t0.elapsed().as_secs_f64());

    // ── 旋转 ──
    let rotator = FhtKacRotator::new(DIM, 42);
    let padded = rotator.padded_dim;
    let t_rot = Instant::now();
    let train_rot: Vec<Vec<f32>> = train.par_chunks(DIM).map(|v| rotator.rotate(v)).collect();
    let q_rot: Vec<Vec<f32>> = test.par_chunks(DIM).map(|v| rotator.rotate(v)).collect();
    eprintln!(
        "  旋转耗时 {:.2}s (padded_dim={padded}, trunc_dim={})",
        t_rot.elapsed().as_secs_f64(),
        rotator.trunc_dim
    );

    // ── 真值：归一化后的 cosine（= 内积）──
    let gt_sets: Vec<Vec<usize>> = (0..n_q)
        .into_par_iter()
        .map(|qi| {
            let q = &test[qi * DIM..(qi + 1) * DIM];
            let scores: Vec<f32> = (0..n_train)
                .map(|i| {
                    q.iter()
                        .zip(&train[i * DIM..(i + 1) * DIM])
                        .map(|(a, b)| a * b)
                        .sum::<f32>()
                })
                .collect();
            topk_desc(&scores, *KS.iter().max().unwrap())
        })
        .collect();

    // ── 编码 ──
    let t_enc = Instant::now();
    // 1 bit 组
    let sign1_db: Vec<Sign1> = train.par_chunks(DIM).map(encode_sign1).collect();
    let rbq1_db: Vec<RaBitQ1> = train_rot
        .par_iter()
        .map(|v| encode_rabitq1(v, padded))
        .collect();
    // 2 bit 组
    let bq2_db: Vec<Bq2> = train.par_chunks(DIM).map(encode_bq2).collect();
    let bq2_db_rot: Vec<Bq2> = train_rot.par_iter().map(|v| encode_bq2(v)).collect();
    let (sq_lo, sq_hi) = {
        let lo = train_rot.iter().flatten().copied().fold(f32::MAX, f32::min);
        let hi = train_rot.iter().flatten().copied().fold(f32::MIN, f32::max);
        (lo, hi)
    };
    let sq2_db: Vec<Sq2> = train_rot
        .par_iter()
        .map(|v| encode_sq2(v, sq_lo, sq_hi))
        .collect();
    eprintln!("  编码耗时 {:.2}s", t_enc.elapsed().as_secs_f64());

    // ── 误差界统计（RaBitQ 的真正价值）──
    let (eps_min, eps_mean, eps_max, fac_mean, fac_cv) = {
        let eps: Vec<f32> = rbq1_db.iter().map(|d| d.epsilon).collect();
        let eps_mean = eps.iter().sum::<f32>() / eps.len() as f32;
        let eps_max = eps.iter().copied().fold(0.0f32, f32::max);
        let eps_min = eps.iter().copied().fold(f32::MAX, f32::min);
        let fac: Vec<f32> = rbq1_db.iter().map(|d| d.factor).collect();
        let fac_mean = fac.iter().sum::<f32>() / fac.len() as f32;
        let m = fac_mean as f64;
        let sd =
            (fac.iter().map(|&v| (v as f64 - m).powi(2)).sum::<f64>() / fac.len() as f64).sqrt();
        (eps_min, eps_mean, eps_max, fac_mean, sd / m)
    };
    eprintln!("\n  ── RaBitQ 误差上界 ε(x) = sqrt(1 − ‖x_u‖₁²/D) ──");
    eprintln!("     ε(x): min={eps_min:.4} mean={eps_mean:.4} max={eps_max:.4}");
    eprintln!("     逐向量因子 ‖x_u‖₁/D: mean={fac_mean:.6} 变异系数={fac_cv:.4}");
    eprintln!(
        "     （归一化后因子仅 {:.2}% 漂移；原基准的 4.4% 漂移主要来自未归一化）",
        fac_cv * 100.0
    );

    // ── 守卫 2 + 守卫 3：误差界有效性 & 安全剪枝 ──
    let k_check = 10usize;
    let (violations, checked, prune_ratio, prune_fn) = (0..n_q)
        .into_par_iter()
        .map(|qi| {
            let q = &test[qi * DIM..(qi + 1) * DIM];
            let qr = &q_rot[qi];
            let est: Vec<f32> = rbq1_db
                .iter()
                .map(|d| rabitq1_estimate(qr, d, padded))
                .collect();
            let truth: Vec<f32> = (0..n_train)
                .map(|i| {
                    q.iter()
                        .zip(&train[i * DIM..(i + 1) * DIM])
                        .map(|(a, b)| a * b)
                        .sum::<f32>()
                })
                .collect();

            // 守卫 2：|est − true| ≤ ε + tol  （注意 est 少乘了 ‖q‖=1 因子，两者单位一致）
            let mut viol = 0usize;
            for i in 0..n_train {
                if (est[i] - truth[i]).abs() > rbq1_db[i].epsilon + 1e-4 {
                    viol += 1;
                }
            }

            // 守卫 3：安全剪枝。LB = min over true top-k of (est − ε)
            let gt = &gt_sets[qi];
            let lb = gt
                .iter()
                .map(|&i| est[i] - rbq1_db[i].epsilon)
                .fold(f32::MAX, f32::min);
            let pruned: HashSet<usize> = (0..n_train)
                .filter(|&i| est[i] + rbq1_db[i].epsilon < lb)
                .collect();
            let fn_count = gt.iter().filter(|i| pruned.contains(i)).count();
            (
                viol,
                n_train,
                pruned.len() as f64 / n_train as f64,
                fn_count,
            )
        })
        .reduce(
            || (0usize, 0usize, 0.0f64, 0usize),
            |a, b| (a.0 + b.0, a.1 + b.1, a.2 + b.2, a.3 + b.3),
        );

    eprintln!("\n  ── 正确性守卫 ──");
    eprintln!(
        "     误差界违例: {violations} / {checked} 对  ({})",
        if violations == 0 { "PASS" } else { "FAIL" }
    );
    eprintln!(
        "     安全剪枝: 平均剪掉 {:.2}% 候选，真实 Top-{k_check} 假阴性 {prune_fn} 个  ({})",
        prune_ratio / n_q as f64 * 100.0,
        if prune_fn == 0 { "PASS" } else { "FAIL" }
    );
    assert_eq!(violations, 0, "误差界不成立 —— 估计量实现有误");
    assert_eq!(prune_fn, 0, "安全剪枝出现假阴性 —— 界推导有误");

    // ── Part A：等比特公平对照 ──
    eprintln!("\n═══════════════════════════════════════════════════════════════════");
    eprintln!("  Part A — 等比特公平对照（全部在 L2 归一化数据上）");
    eprintln!("═══════════════════════════════════════════════════════════════════");

    const V_NAMES: [&str; 6] = [
        "① 无旋转 1-bit sign",
        "② RaBitQ 1-bit 对称",
        "③ RaBitQ 1-bit 非对称(修正)",
        "④ BQ2 2-bit (= QuIVer 默认)",
        "⑤ BQ2 2-bit + 旋转",
        "⑥ 2-bit SQ + 旋转",
    ];
    const V_BITS: [usize; 6] = [1, 1, 1, 2, 2, 2];
    const V_ROT: [bool; 6] = [false, true, true, false, true, true];

    let max_k = *KS.iter().max().unwrap();
    let mut results = [[0.0f64; 4]; 6];
    let mut ns_per_call = [0.0f64; 6];

    for vi in 0..6 {
        let t_var = Instant::now();
        // 逐查询只算一遍完整代价向量，再派生各 K 的 top-K（避免 4 倍重复计算）
        let per_query: Vec<Vec<usize>> = (0..n_q)
            .into_par_iter()
            .map(|qi| {
                let q = &test[qi * DIM..(qi + 1) * DIM];
                let qr = &q_rot[qi];
                // 统一为"代价"语义：越小越近
                let costs: Vec<f32> = match vi {
                    0 => {
                        let s = encode_sign1(q);
                        sign1_db.iter().map(|d| hamming(&s, d) as f32).collect()
                    }
                    1 => rbq1_db
                        .iter()
                        .map(|d| rabitq1_sym(qr, d, padded) as f32)
                        .collect(),
                    2 => rbq1_db
                        .iter()
                        .map(|d| -rabitq1_estimate(qr, d, padded))
                        .collect(),
                    3 => {
                        let b = encode_bq2(q);
                        bq2_db.iter().map(|d| -bq2_dot(&b, d, DIM) as f32).collect()
                    }
                    4 => {
                        let b = encode_bq2(qr);
                        bq2_db_rot
                            .iter()
                            .map(|d| -bq2_dot(&b, d, padded) as f32)
                            .collect()
                    }
                    _ => {
                        let s = encode_sq2(qr, sq_lo, sq_hi);
                        sq2_db.iter().map(|d| sq2_l1(&s, d) as f32).collect()
                    }
                };
                topk_asc_f32(&costs, max_k)
            })
            .collect();
        let elapsed = t_var.elapsed().as_secs_f64();
        ns_per_call[vi] = elapsed / (n_q * n_train) as f64 * 1e9;

        for (ki, &k) in KS.iter().enumerate() {
            let hits: usize = (0..n_q)
                .map(|qi| overlap(&per_query[qi][..k], &gt_sets[qi][..k]))
                .sum();
            results[vi][ki] = hits as f64 / (n_q * k) as f64 * 100.0;
        }
        eprintln!(
            "  {} 完成 ({:.1}s, {:.1} ns/call)  K=10 {:.2}%",
            V_NAMES[vi], elapsed, ns_per_call[vi], results[vi][1]
        );
    }

    println!("\n### Part A — 等比特公平对照（L2 归一化后）\n");
    println!("| 方案 | bit/维 | 旋转 | K=1 | K=10 | K=100 | K=500 | ns/call |");
    println!("|---|---|---|---|---|---|---|---|");
    for vi in 0..6 {
        println!(
            "| {} | {} | {} | {:.2}% | {:.2}% | {:.2}% | {:.2}% | {:.1} |",
            V_NAMES[vi],
            V_BITS[vi],
            if V_ROT[vi] { "有" } else { "无" },
            results[vi][0],
            results[vi][1],
            results[vi][2],
            results[vi][3],
            ns_per_call[vi]
        );
    }

    println!("\n### 组内对照 —— 同比特预算下『旋转』的净贡献（K=10）\n");
    println!("| bit/维 | 无旋转 | 有旋转 | 旋转净增益 |");
    println!("|---|---|---|---|");
    println!(
        "| 1 | ① {:.2}% | ③ {:.2}% | **{:+.2}pp** |",
        results[0][1],
        results[2][1],
        results[2][1] - results[0][1]
    );
    println!(
        "| 2 | ④ {:.2}% | ⑤ {:.2}% | **{:+.2}pp** |",
        results[3][1],
        results[4][1],
        results[4][1] - results[3][1]
    );

    println!("\n### 误差界统计（T1 新命题的基础）\n");
    println!("| 量 | 值 |");
    println!("|---|---|");
    println!("| ε(x) 上界 min / mean / max | {eps_min:.4} / {eps_mean:.4} / {eps_max:.4} |");
    println!("| 逐向量因子 ‖x_u‖₁/D 变异系数 | {fac_cv:.4} |");
    println!(
        "| 误差界违例 | {violations} / {checked}（{}） |",
        if violations == 0 { "PASS" } else { "FAIL" }
    );
    println!(
        "| 安全剪枝潜力 | 平均剪掉 {:.2}% 候选，Top-{k_check} 假阴性 {prune_fn}（{}） |",
        prune_ratio / n_q as f64 * 100.0,
        if prune_fn == 0 { "PASS" } else { "FAIL" }
    );

    eprintln!(
        "\n  误差界: ε mean={eps_mean:.4}; 安全剪枝潜力 {:.2}%",
        prune_ratio / n_q as f64 * 100.0
    );
    eprintln!("═══════════════════════════════════════════════════════════════════");
}

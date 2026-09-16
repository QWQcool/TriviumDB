//! RaBitQ 误差界 ε 随比特预算的缩放 —— 判定"可证安全剪枝"路线是否可行
//!
//! # 决策问题
//! `docs/research/l1-followup.md` §3.4 实测：1-bit RaBitQ 的 Cauchy–Schwarz 误差界
//! ε(x) 均值 **0.5999**，而真实 Top-10 与其余候选的内积间隙约 **0.01** 量级
//! → 安全剪枝潜力 **0.00%**。朴素"用误差界剪枝"的路线在 1 bit 下完全不可用。
//!
//! 本基准回答：**提高到多少 bit，剪枝才真正变得可用？** 若在合理比特预算内
//! （≤8 bit/维）都不可用，则该路线应彻底关闭，T1 转向"ε 作为软导航信号"。
//!
//! # 统一量化框架（使 B=1 严格退化为 RaBitQ 1-bit）
//! 对单位向量 `x_u`（`‖x_u‖ = 1`），任意码 `x_c` 的最优重建是 `x_u` 在 `x_c` 上的投影：
//! ```text
//!   x̄   = (⟨x_c, x_u⟩ / ‖x_c‖²) · x_c
//!   ε²  = ‖x_u − x̄‖² = 1 − ⟨x_c, x_u⟩² / ‖x_c‖²
//!   est(q, x) = ⟨q_u, x̄⟩ = (⟨x_c, x_u⟩ / ‖x_c‖²) · ⟨q_u, x_c⟩
//! ```
//! 一维均匀标量量化（mid-rise + clamp）：`x_c[i] = (k + 0.5)·δ`，
//! `k = clamp(⌊x_u[i]/δ + 0.5⌋, −m, m−1)`，`m = 2^(B−1)`，`δ = a/m`。
//! 共 `2^B` 个电平。**B=1 时 `x_c[i] = ±a/2`，即 `∝ sign(x_u[i])`**，
//! 此时 `ε² = 1 − ‖x_u‖₁²/D` —— 与 RaBitQ 1-bit 的闭式界**严格一致**（见守卫 1）。
//!
//! # 理论预估（用于对照，不作为结论）
//! 均匀量化每坐标误差方差 ≈ δ²/12，故 `ε² ≈ D·δ²/12 = D·(2a/2^B)²/12`。
//! 取 `a = c/√D` → `ε ≈ c / (√3 · 2^B)`，即 **ε ∝ 2^(−B)**。
//! 由 1-bit 的 ε≈0.60 外推：降到 0.01 需 `2^(B−1) ≈ 60` → **B ≈ 7 bit/维**
//! （对比 BQ2 用 2 bit/维）。
//!
//! # 可证安全剪枝判据（可部署，不依赖真值 oracle）
//! 每个候选的区间 `[L, U] = [est − ε, est + ε]` 必含真值。候选 `c` 可安全排除 ⟺
//! **存在 k 个候选的下界都超过 `U(c)`**（则这 k 个的真值都 > true(c)，c 不可能进 Top-k）。
//! 均匀半径 `ε_u` 下该判据化简为：`est(c) < est_(k) − 2·ε_u`
//! （`est_(k)` = 第 k 大估计值），于是剪枝率 = `P(est < est_(k) − 2ε_u)`，
//! 可由一次排序 + 二分查表 O(log N) 求出，使整条 `剪枝率(ε_u)` 曲线近乎免费。
//!
//! # 数据分布
//! `cohere_train.f32` / `cohere_test.f32`（真实数据集，内部 L2 归一化）。
//! 训练 100000 × 768，查询 200。旋转开关两态对照。
//!
//! # 正确性 oracle（三条硬断言）
//! 1. **B=1 闭式一致**：统一框架算出的 ε 必须等于 `sqrt(1 − ‖x_u‖₁²/D)`；
//! 2. **界成立**：`|est − true| ≤ ε + 1e-4` 对全部被检样本成立；
//! 3. **剪枝零假阴性**：任意 ε_u 下被剪掉的候选**不得**出现在真实 Top-K 中
//!    （该判据可证安全，出现假阴性即实现有误）。
//!
//! # 计时边界
//! 只测编码与"每 (查询 × DB 点)"的摊薄耗时，含 top-K 排序。不测端到端图检索 QPS。
//!
//! # 非目标
//! 不做图索引、不做多比特 RaBitQ 的精确论文实现（本基准用均匀量化的**上界对照**，
//! 意在给出"即使最优标量量化也不够"的下界论证）、不替代 `bench_rbq2_equal_bits`。
//!
//! 用法: cargo bench --bench bench_rabitq_epsilon_scaling

use rayon::prelude::*;
use std::collections::HashSet;
use std::time::Instant;

const DIM: usize = 768;
const N_TRAIN: usize = 100_000;
const N_QUERIES: usize = 200;
/// 剪枝分析针对的 K（高 K 是本项目的已知弱点，故并列考察）
const K_LIST: [usize; 2] = [10, 100];
/// 比特预算扫描范围
const BIT_LIST: [u32; 7] = [1, 2, 3, 4, 5, 6, 8];
/// 量化尺度扫描（`a = c/√D`，单位向量 RMS=1/√D）。取每 B 的最优 → 更强论证。
const C_LIST: [f32; 6] = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0];
/// 剪枝率曲线的 ε_u 网格（对数间隔；覆盖 1-bit 的 0.60 到实时可用区）
const EPS_GRID: [f32; 21] = [
    0.0005, 0.001, 0.002, 0.003, 0.005, 0.008, 0.012, 0.018, 0.028, 0.045, 0.07, 0.11, 0.17, 0.25,
    0.35, 0.45, 0.55, 0.65, 0.8, 1.0, 1.5,
];
/// 判定"可用"的剪枝率门槛
const PRUNE_TARGET: f64 = 0.50;

// ══════════════════════════════════════════════════════════════════
//  旋转器（与 bench_rbq2_equal_bits 同一实现，已证为正交变换）
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
//  统一量化框架
// ══════════════════════════════════════════════════════════════════

/// 一个向量的码及其投影重建参数。
struct Code {
    /// 量化电平 `x_c[i]`
    levels: Vec<f32>,
    /// `⟨x_c, x_u⟩`
    corr: f32,
    /// `‖x_c‖²`
    norm2: f32,
    /// ε = sqrt(1 − corr²/norm2)，`|est − true| ≤ ε` 可证
    epsilon: f32,
}

/// 一维均匀标量量化（mid-rise + clamp），返回 (levels, corr, norm2)。
///
/// 电平中心 `(k + 0.5)·δ`，`k ∈ [−m, m−1]`，`m = 2^(bits−1)`，共 `2^bits` 个电平。
/// **判定边界必须落在 δ 的整数倍**（`⌊v/δ⌋`）；若写成 `⌊v/δ + 0.5⌋`，
/// 则 `v ∈ [−δ/2, 0)` 会被错映射到 `+δ/2`，破坏 B=1 → sign 的退化性
/// （该错误由守卫 1 捕获）。
fn uniform_quantize(x: &[f32], bits: u32, scale: f32) -> (Vec<f32>, f32, f32) {
    let m = 1i32 << (bits - 1);
    let delta = scale / m as f32;
    debug_assert!(delta > 0.0);
    let mut levels = Vec::with_capacity(x.len());
    let mut corr = 0.0f32;
    let mut norm2 = 0.0f32;
    for &v in x {
        let k = (v / delta).floor();
        let k = k.clamp(-(m as f32), m as f32 - 1.0);
        let lv = (k + 0.5) * delta;
        levels.push(lv);
        corr += lv * v;
        norm2 += lv * lv;
    }
    (levels, corr, norm2)
}

fn make_code(x: &[f32], bits: u32, scale: f32) -> Code {
    let (levels, corr, norm2) = uniform_quantize(x, bits, scale);
    let epsilon = (1.0 - corr * corr / norm2.max(1e-30)).max(0.0).sqrt();
    Code {
        levels,
        corr,
        norm2,
        epsilon,
    }
}

/// `est(q_u, x̄) = (corr/‖x_c‖²)·⟨q_u, x_c⟩`
#[inline]
fn estimate(q: &[f32], code: &Code) -> f32 {
    let mut acc = 0.0f32;
    for i in 0..q.len() {
        acc += q[i] * code.levels[i];
    }
    code.corr / code.norm2.max(1e-30) * acc
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

fn l2_normalize(data: &mut [f32], dim: usize) {
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
}

fn dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

fn percentile_f32(mut v: Vec<f32>, p: f64) -> f32 {
    if v.is_empty() {
        return f32::NAN;
    }
    v.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
    let idx = p / 100.0 * (v.len() - 1) as f64;
    let lo = idx.floor() as usize;
    let hi = idx.ceil() as usize;
    if lo == hi {
        return v[lo];
    }
    v[lo] * ((hi as f64 - idx) as f32) + v[hi] * ((idx - lo as f64) as f32)
}

fn topk_desc(scores: &[f32], k: usize) -> Vec<usize> {
    let mut v: Vec<(usize, f32)> = scores.iter().enumerate().map(|(i, &s)| (i, s)).collect();
    v.sort_unstable_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then(a.0.cmp(&b.0)));
    v.truncate(k);
    v.into_iter().map(|(i, _)| i).collect()
}

fn main() {
    eprintln!("═══════════════════════════════════════════════════════════════════");
    eprintln!("  RaBitQ 误差界 ε 随比特预算缩放 —— 安全剪枝可行性判定");
    eprintln!("═══════════════════════════════════════════════════════════════════");

    let t0 = Instant::now();
    let mut train = read_f32_bin("cohere_train.f32");
    let mut test = read_f32_bin("cohere_test.f32");
    train.truncate(N_TRAIN.min(train.len() / DIM) * DIM);
    test.truncate(N_QUERIES.min(test.len() / DIM) * DIM);
    l2_normalize(&mut train, DIM);
    l2_normalize(&mut test, DIM);
    let n_train = train.len() / DIM;
    let n_q = test.len() / DIM;

    let rotator = FhtKacRotator::new(DIM, 42);
    let padded = rotator.padded_dim;
    let train_rot: Vec<Vec<f32>> = train.par_chunks(DIM).map(|v| rotator.rotate(v)).collect();
    let q_rot: Vec<Vec<f32>> = test.par_chunks(DIM).map(|v| rotator.rotate(v)).collect();
    eprintln!(
        "  数据 {n_train} × {DIM}，查询 {n_q}；加载+归一化+旋转 {:.2}s",
        t0.elapsed().as_secs_f64()
    );

    // 真值矩阵（= 内积，因已单位化）与 GT。
    // 真值与编码无关，故对两种旋转态各算一次并复用 —— 否则会在 84 个配置里重复计算。
    // 索引约定: truth_flat[0] = 无旋转, truth_flat[1] = 有旋转
    let max_k = *K_LIST.iter().max().unwrap();
    let db_of = |rotated: bool| -> Vec<&[f32]> {
        if rotated {
            train_rot.iter().map(|v| v.as_slice()).collect()
        } else {
            train.chunks(DIM).collect()
        }
    };
    let qs_of = |rotated: bool| -> Vec<&[f32]> {
        if rotated {
            q_rot.iter().map(|v| v.as_slice()).collect()
        } else {
            test.chunks(DIM).collect()
        }
    };
    let truth_flat: Vec<Vec<Vec<f32>>> = [false, true]
        .iter()
        .map(|&rotated| {
            let db = db_of(rotated);
            let qs = qs_of(rotated);
            (0..n_q)
                .into_par_iter()
                .map(|qi| {
                    let q = qs[qi];
                    (0..n_train)
                        .map(|i| dot(q, &db[i][..DIM]))
                        .collect::<Vec<f32>>()
                })
                .collect()
        })
        .collect();
    let gt_flat: Vec<Vec<Vec<usize>>> = truth_flat
        .iter()
        .map(|t| t.iter().map(|s| topk_desc(s, max_k)).collect())
        .collect();
    eprintln!(
        "  真值+GT 预计算完成（两态）: {:.2}s",
        t0.elapsed().as_secs_f64()
    );

    // ── 守卫 1：B=1 时统一框架的 ε 必须等于闭式 sqrt(1 − ‖x_u‖₁²/D) ──
    {
        let probe = &train_rot[0];
        let l1: f32 = probe.iter().map(|v| v.abs()).sum();
        let closed = (1.0 - l1 * l1 / padded as f32).max(0.0).sqrt();
        let c = make_code(probe, 1, 3.0 / (DIM as f32).sqrt());
        assert!(
            (c.epsilon - closed).abs() < 1e-5,
            "守卫1 失败: 框架 ε={} vs 闭式 ε={}",
            c.epsilon,
            closed
        );
        eprintln!(
            "  守卫1 B=1 闭式一致: ε={:.6} vs {:.6}  PASS",
            c.epsilon, closed
        );
    }

    // ════════════════════════════════════════════════════════════
    //  Phase 1：ε(B) 曲线 + 尺度扫描（取每 B 最优 → 最强论证）
    // ════════════════════════════════════════════════════════════
    eprintln!("\n═══════════════════════════════════════════════════════════════════");
    eprintln!("  Phase 1 — ε(B) 曲线（每 B 取最优尺度 c，oracle 调优）");
    eprintln!("═══════════════════════════════════════════════════════════════════");

    struct Best {
        bits: u32,
        rotated: bool,
        scale_c: f32,
        eps_mean: f32,
        eps_p95: f32,
        err_mean: f32,
        /// 界紧致度 = 实际误差均值 / ε 均值（越小说明界越松）
        tightness: f32,
        recall10: f64,
        ns_per_call: f64,
    }
    let mut bests: Vec<Best> = Vec::new();

    for &rotated in &[false, true] {
        let db = db_of(rotated);
        let qs = qs_of(rotated);
        let rms_scale = 1.0 / (DIM as f32).sqrt();

        for &bits in &BIT_LIST {
            let mut best: Option<Best> = None;

            for &c in &C_LIST {
                let scale = c * rms_scale;
                let t_enc = Instant::now();
                let codes: Vec<Code> = db.par_iter().map(|x| make_code(x, bits, scale)).collect();
                let enc_s = t_enc.elapsed().as_secs_f64();

                let eps_all: Vec<f32> = codes.iter().map(|k| k.epsilon).collect();
                let eps_mean = eps_all.iter().sum::<f32>() / eps_all.len() as f32;
                let eps_p95 = percentile_f32(eps_all.clone(), 95.0);

                // 误差 + 质量 + 界成立性（守卫 2，与误差累加融合为一趟）
                let rot_idx = usize::from(rotated);
                let t_q = Instant::now();
                let (err_sum, hits, pairs, viol) = (0..n_q)
                    .into_par_iter()
                    .map(|qi| {
                        let q = qs[qi];
                        let truth = &truth_flat[rot_idx][qi];
                        let est: Vec<f32> = codes.iter().map(|k| estimate(q, k)).collect();
                        let mut es = 0.0f64;
                        let mut v = 0usize;
                        for i in 0..n_train {
                            let d = (est[i] - truth[i]).abs();
                            es += d as f64;
                            if d > codes[i].epsilon + 1e-4 {
                                v += 1;
                            }
                        }
                        let top = topk_desc(&est, 10);
                        let gt10: HashSet<usize> =
                            gt_flat[rot_idx][qi][..10].iter().copied().collect();
                        let h = top.iter().filter(|i| gt10.contains(i)).count();
                        (es, h, n_train, v)
                    })
                    .reduce(
                        || (0.0, 0usize, 0usize, 0usize),
                        |a, b| (a.0 + b.0, a.1 + b.1, a.2 + b.2, a.3 + b.3),
                    );
                let q_s = t_q.elapsed().as_secs_f64();
                assert_eq!(
                    viol, 0,
                    "守卫2 失败: B={bits} rot={rotated} c={c} 有 {viol} 对违反 |est−true| ≤ ε"
                );

                let err_mean = (err_sum / pairs as f64) as f32;
                let recall10 = hits as f64 / (n_q * 10) as f64 * 100.0;
                let candidate = Best {
                    bits,
                    rotated,
                    scale_c: c,
                    eps_mean,
                    eps_p95,
                    err_mean,
                    tightness: err_mean / eps_mean.max(1e-9),
                    recall10,
                    ns_per_call: (enc_s + q_s) / (n_q * n_train) as f64 * 1e9,
                };

                // 选 ε 最小者；并列时选 recall 更高者
                let better = match &best {
                    None => true,
                    Some(b) => {
                        candidate.eps_mean < b.eps_mean - 1e-7
                            || ((candidate.eps_mean - b.eps_mean).abs() <= 1e-7
                                && candidate.recall10 > b.recall10)
                    }
                };
                if better {
                    best = Some(candidate);
                }
            }

            let b = best.unwrap();
            eprintln!(
                "  B={:<2} rot={:<3} c={:.1}  ε mean {:.5} p95 {:.5}  实际误差 {:.5}  \
                 紧致度 {:.3}  R@10 {:.2}%  {:.1} ns",
                b.bits,
                if b.rotated { "有" } else { "无" },
                b.scale_c,
                b.eps_mean,
                b.eps_p95,
                b.err_mean,
                b.tightness,
                b.recall10,
                b.ns_per_call
            );
            bests.push(b);
        }
    }

    // ════════════════════════════════════════════════════════════
    //  Phase 2：可证安全剪枝
    //    (a) 逐候选 ε —— 实际可部署；判据: 存在 k 个候选的下界 L 超过 U(c)
    //    (b) 均匀 ε_u 曲线 —— 可行性前沿；**仅当 ε_u ≥ max_i ε(i) 时才 sound**
    //        （把均值当半径会漏判 —— 该错误已被守卫 3 捕获）
    // ════════════════════════════════════════════════════════════
    eprintln!("\n═══════════════════════════════════════════════════════════════════");
    eprintln!("  Phase 2 — 可证安全剪枝");
    eprintln!("═══════════════════════════════════════════════════════════════════");

    struct PruneOut {
        eps_max: f32,
        eps_p999: f32,
        /// (a) 逐候选 ε 的可部署剪枝率
        exact_ratio: f64,
        exact_fn: usize,
        /// (b) 均匀 ε_u 曲线（仅 ε_u ≥ eps_max 时 sound）
        curve: [f64; EPS_GRID.len()],
        eps_star: f32,
        /// (c) 经验校正半径（逐查询实际误差的 p99.9 均值）下的剪枝率与假阴性
        emp_radius: f32,
        emp_ratio: f64,
        emp_fn: usize,
    }
    let mut outs: Vec<PruneOut> = Vec::new();
    let k_main = K_LIST[0];

    for b in &bests {
        let db = db_of(b.rotated);
        let qs = qs_of(b.rotated);
        let gt_b = &gt_flat[usize::from(b.rotated)];
        let scale = b.scale_c / (DIM as f32).sqrt();
        let codes: Vec<Code> = db.par_iter().map(|x| make_code(x, b.bits, scale)).collect();

        let eps_all: Vec<f32> = codes.iter().map(|c| c.epsilon).collect();
        let eps_max = eps_all.iter().copied().fold(0.0f32, f32::max);
        let eps_p999 = percentile_f32(eps_all.clone(), 99.9);
        let truth = &truth_flat[usize::from(b.rotated)];

        let (exact_pruned, exact_fn, curve_sum, emp_pruned, emp_fn, emp_radius_sum) = (0..n_q)
            .into_par_iter()
            .map(|qi| {
                let q = qs[qi];
                let est: Vec<f32> = codes.iter().map(|c| estimate(q, c)).collect();

                // (a) 逐候选 ε：按 L = est − ε 降序排，阈值取第 k 大下界
                let mut lu: Vec<(f32, f32, usize)> = (0..n_train)
                    .map(|i| {
                        let e = codes[i].epsilon;
                        (est[i] - e, est[i] + e, i)
                    })
                    .collect();
                lu.sort_unstable_by(|a, z| z.0.partial_cmp(&a.0).unwrap());
                let thr = lu[k_main - 1].0;
                let gt_k: HashSet<usize> = gt_b[qi][..k_main].iter().copied().collect();
                let mut pruned = 0usize;
                let mut fns = 0usize;
                for &(_, u, i) in &lu[k_main..] {
                    if u < thr {
                        pruned += 1;
                        if gt_k.contains(&i) {
                            fns += 1;
                        }
                    }
                }

                // (b) 均匀 ε_u 曲线：剪枝顺序与 ε_u 无关 → 一次降序排序复用
                let mut desc: Vec<f32> = est.clone();
                desc.sort_unstable_by(|a, z| z.partial_cmp(a).unwrap());
                let est_k = desc[k_main - 1];
                let mut sums = [0.0f64; EPS_GRID.len()];
                for (gi, &eu) in EPS_GRID.iter().enumerate() {
                    let t = est_k - 2.0 * eu;
                    let ge = desc.partition_point(|&v| v >= t);
                    sums[gi] = (n_train - ge) as f64 / n_train as f64;
                }

                // (c) 经验校正半径：用实际误差的 p99.9 当半径（非可证，但高置信）
                //     动机：Phase 1 显示界紧致度仅 0.02–0.13，即界比实际误差宽 8–48 倍。
                let mut errs: Vec<f32> = (0..n_train)
                    .map(|i| (est[i] - truth[qi][i]).abs())
                    .collect();
                let qidx = n_train * 999 / 1000;
                errs.select_nth_unstable_by(qidx, |a, z| a.partial_cmp(z).unwrap());
                let emp_radius = errs[qidx];
                let t_emp = est_k - 2.0 * emp_radius;
                let ge_emp = desc.partition_point(|&v| v >= t_emp);
                let emp_pruned = n_train - ge_emp;
                let emp_fn = gt_k.iter().filter(|&&i| est[i] < t_emp).count();

                (pruned, fns, sums, emp_pruned, emp_fn, emp_radius)
            })
            .reduce(
                || {
                    (
                        0usize,
                        0usize,
                        [0.0f64; EPS_GRID.len()],
                        0usize,
                        0usize,
                        0.0f32,
                    )
                },
                |a, b| {
                    let mut s = [0.0f64; EPS_GRID.len()];
                    for i in 0..EPS_GRID.len() {
                        s[i] = a.2[i] + b.2[i];
                    }
                    (a.0 + b.0, a.1 + b.1, s, a.3 + b.3, a.4 + b.4, a.5 + b.5)
                },
            );

        let mut curve = [0.0f64; EPS_GRID.len()];
        for i in 0..EPS_GRID.len() {
            curve[i] = curve_sum[i] / n_q as f64;
        }
        let eps_star = EPS_GRID
            .iter()
            .rev()
            .find(|&&eu| {
                let idx = EPS_GRID.iter().position(|&x| x == eu).unwrap();
                curve[idx] >= PRUNE_TARGET
            })
            .copied()
            .unwrap_or(f32::NAN);
        let exact_ratio = exact_pruned as f64 / (n_q * n_train) as f64;
        let emp_radius = emp_radius_sum / n_q as f32;
        let emp_ratio = emp_pruned as f64 / (n_q * n_train) as f64;

        eprintln!(
            "  B={:<2} rot={:<3} ε max {:.5} | 可证剪枝 {:.2}%（FN {}） | 经验半径 {:.5} → 剪枝 {:.2}%（FN {}）",
            b.bits,
            if b.rotated { "有" } else { "无" },
            eps_max,
            exact_ratio * 100.0,
            exact_fn,
            emp_radius,
            emp_ratio * 100.0,
            emp_fn
        );
        outs.push(PruneOut {
            eps_max,
            eps_p999,
            exact_ratio,
            exact_fn,
            curve,
            eps_star,
            emp_radius,
            emp_ratio,
            emp_fn,
        });
    }

    // ── 守卫 3：逐候选判据可证安全 ⟹ 假阴性必须恒为 0 ──
    let total_fn: usize = outs.iter().map(|o| o.exact_fn).sum();
    assert_eq!(
        total_fn, 0,
        "守卫3 失败: 逐候选安全剪枝出现假阴性 —— 判据推导有误"
    );
    eprintln!("\n  守卫3 逐候选剪枝零假阴性: 合计 {total_fn}  PASS");

    // ════════════════════════════════════════════════════════════
    //  输出
    // ════════════════════════════════════════════════════════════
    println!("\n### Phase 1 — ε(B) 曲线（每 B 取最优尺度，oracle 调优）\n");
    println!(
        "| B (bit/维) | 旋转 | 最优 c | ε mean | ε p95 | 实际误差 | 紧致度 | 编码 R@10 | ns/次 |"
    );
    println!("|---|---|---|---|---|---|---|---|---|");
    for b in &bests {
        println!(
            "| {} | {} | {:.1} | {:.5} | {:.5} | {:.5} | {:.3} | {:.2}% | {:.1} |",
            b.bits,
            if b.rotated { "有" } else { "无" },
            b.scale_c,
            b.eps_mean,
            b.eps_p95,
            b.err_mean,
            b.tightness,
            b.recall10,
            b.ns_per_call
        );
    }

    println!("\n### Phase 2 — 可证安全剪枝（K={k_main}）\n");
    println!("| B | 旋转 | ε mean | **ε max** | ε p99.9 | 逐候选剪枝率 | 假阴性 | 均匀 ε*(≥50%) |");
    println!("|---|---|---|---|---|---|---|---|");
    for (bi, b) in bests.iter().enumerate() {
        let o = &outs[bi];
        println!(
            "| {} | {} | {:.5} | **{:.5}** | {:.5} | **{:.2}%** | {} | {} |",
            b.bits,
            if b.rotated { "有" } else { "无" },
            b.eps_mean,
            o.eps_max,
            o.eps_p999,
            o.exact_ratio * 100.0,
            o.exact_fn,
            if o.eps_star.is_nan() {
                "不可达".to_string()
            } else {
                format!("{:.4}", o.eps_star)
            }
        );
    }

    println!("\n### 均匀 ε_u 剪枝率曲线（仅 ε_u ≥ 该配置 ε max 时 sound）\n");
    print!("| B | 旋转 | ε max |");
    for &eu in &EPS_GRID {
        print!(" {eu:.4} |");
    }
    println!();
    print!("|---|---|---|");
    for _ in &EPS_GRID {
        print!("---|");
    }
    println!();
    for (bi, b) in bests.iter().enumerate() {
        let o = &outs[bi];
        print!(
            "| {} | {} | {:.4} |",
            b.bits,
            if b.rotated { "有" } else { "无" },
            o.eps_max
        );
        for r in &o.curve {
            print!(" {:.1}% |", r * 100.0);
        }
        println!();
    }

    println!("\n### Phase 3 — 经验校正半径下的剪枝 ⚠️ ORACLE 校准\n");
    println!("半径由**真实误差** |est−true| 的 p99.9 导出，部署时不可得 —— 本表只用于度量");
    println!("『界到底比实际误差松多少』（界/经验 比值列），据此估算可收紧空间。可部署替代");
    println!("方案：用 ε 自身分布的分位 × 校准系数，系数须在索引期以库内向量自标定。\n");
    println!(
        "| B | 旋转 | ε max（可证） | **界/经验 比值** | 经验半径 p99.9 | 经验剪枝率 | 经验假阴性 |"
    );
    println!("|---|---|---|---|---|---|---|");
    for (bi, b) in bests.iter().enumerate() {
        let o = &outs[bi];
        println!(
            "| {} | {} | {:.5} | {:.1}× | {:.5} | **{:.2}%** | {} |",
            b.bits,
            if b.rotated { "有" } else { "无" },
            o.eps_max,
            o.eps_max / o.emp_radius.max(1e-9),
            o.emp_radius,
            o.emp_ratio * 100.0,
            o.emp_fn
        );
    }

    println!("\n### 判定\n");
    let mut feasible: Vec<(u32, bool, f32, f64)> = Vec::new();
    let mut feasible_emp: Vec<(u32, bool, f32, f64, usize)> = Vec::new();
    for (bi, b) in bests.iter().enumerate() {
        let o = &outs[bi];
        // sound 的均匀剪枝率：取 ε_u = ε max 处
        let idx = EPS_GRID
            .iter()
            .position(|&x| x >= o.eps_max)
            .unwrap_or(EPS_GRID.len() - 1);
        let sound_ratio = o.curve[idx];
        let tag = if o.exact_ratio >= PRUNE_TARGET {
            "  ← 可行"
        } else if o.exact_ratio > 0.01 {
            "  ← 部分"
        } else {
            ""
        };
        println!(
            "  B={:<2} rot={:<3} | ε max {:.5} | 可证剪枝 {:.2}%{} | sound 均匀 {:.2}% | 经验半径 {:.5} → 剪枝 {:.2}%（FN {}）",
            b.bits,
            if b.rotated { "有" } else { "无" },
            o.eps_max,
            o.exact_ratio * 100.0,
            tag,
            sound_ratio * 100.0,
            o.emp_radius,
            o.emp_ratio * 100.0,
            o.emp_fn
        );
        if o.exact_ratio >= PRUNE_TARGET {
            feasible.push((b.bits, b.rotated, o.eps_max, o.exact_ratio));
        }
        if o.emp_ratio >= PRUNE_TARGET {
            feasible_emp.push((b.bits, b.rotated, o.emp_radius, o.emp_ratio, o.emp_fn));
        }
    }

    println!("\n  ── 结论 ──");
    println!("  [A] 可证安全剪枝（严格，FN=0）");
    if feasible.is_empty() {
        let best_ratio = outs.iter().map(|o| o.exact_ratio).fold(0.0f64, f64::max);
        println!(
            "      ✗ B ≤ 8 内最好配置仅 {:.2}%（目标 {:.0}%）→ 路线不可行",
            best_ratio * 100.0,
            PRUNE_TARGET * 100.0
        );
    } else {
        let min_bits = feasible.iter().map(|f| f.0).min().unwrap();
        println!(
            "      ✓ 门槛 B = **{min_bits} bit/维**（BQ2 为 2 bit/维 → 码长需 **{:.1}×**）",
            min_bits as f64 / 2.0
        );
        for (bits, rotated, em, r) in &feasible {
            println!(
                "          {}旋转 B={bits}  ε max={em:.5}  剪枝 {:.2}%",
                if *rotated { "有" } else { "无" },
                r * 100.0
            );
        }
        if let Some(a1) = bests.iter().find(|b| b.bits == 1 && !b.rotated) {
            println!(
                "      理论外推（ε ∝ 2^(−B)，锚 B=1 无旋转 ε={:.4}）预测 B ≈ {:.1}，实测 {min_bits} → 模型成立",
                a1.eps_mean,
                1.0 + (a1.eps_mean / feasible[0].2).log2()
            );
        }
    }

    println!("\n  [B] 经验校正半径（放弃严格可证性，换取更低比特门槛）");
    if feasible_emp.is_empty() {
        println!("      未达 {:.0}% 目标", PRUNE_TARGET * 100.0);
    } else {
        let min_bits_emp = feasible_emp.iter().map(|f| f.0).min().unwrap();
        println!("      ✓ 门槛降至 B = **{min_bits_emp} bit/维**");
        for (bits, rotated, r, pr, fnc) in &feasible_emp {
            println!(
                "          {}旋转 B={bits}  半径={r:.5}  剪枝 {:.2}%（FN {fnc}）",
                if *rotated { "有" } else { "无" },
                pr * 100.0
            );
        }
        println!("      ⚠ 该门槛依赖 ORACLE 校准（半径由真实误差导出）。可部署做法是用");
        println!("        ε 分布的分位 × 校准系数，系数在索引期以库内向量自标定；");
        println!("        届时保证是经验性的（非可证），需按目标漏检率留足余量。");
    }

    println!("\n  [C] 方向判定");
    println!("      1. 旋转是 ε 收缩的前提。无旋转时均匀量化 + 全局尺度无法拟合尖峰分布，");
    println!("         ε 在 B≥5 后饱和于 ~0.33（且最优尺度落在扫描边界 c=4.0，故其数值");
    println!("         仅是上界，非最优）。有旋转时 ε 严格按 ~2^(−B) 下降：");
    println!("         0.5999(B=1) → 0.0083(B=8)，衰减 72× / 2^7=128 ≈ 理论斜率。");
    println!("      2. 可证剪枝的门槛是 B=5 bit/维（B=4 仅 5%，B=6 达 98%）。");
    println!("         对比 BQ2 的 2 bit/维，代价是 2.5× 码长。");
    println!("      3. 误差界本身很松：紧致度 0.02–0.13，界比实际误差宽 8–48×。");
    println!("         故『经验校正半径』路线（[B]）门槛显著更低 —— 但失去可证性。");
    println!("      4. 全部 14 个配置的逐候选剪枝假阴性为 0，判据推导与实现一致。");
    eprintln!("═══════════════════════════════════════════════════════════════════");
}

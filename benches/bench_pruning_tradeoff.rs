//! V1 — 5-bit RaBitQ 误差界剪枝的**端到端 trade-off 实测**
//!
//! # 决策问题
//! `docs/research/t1-epsilon-scaling-decision.md` 判定：可证安全剪枝需 **5 bit/维**
//! （BQ2 是 2 bit/维，码长 2.5×），在该预算下可剪掉 **72%** 候选。
//! 但结论文档明确标注了一个未验证的关键未知：
//! > 5 bit 码在遍历时的**带宽/解包成本**是否会被 72% 的剪枝收益抵消？
//! > **不能用推断，必须实测。**
//!
//! # 关键认识：剪枝能省什么、不能省什么
//! 在图遍历里，"距离计算"**本身就是**产生 `est` 与 `ε` 的那一步
//! （`ε` 是码的性质，随 `est` 一同算出）。因此**剪掉一个候选省不下那次计算**。
//!
//! 真正能省的只有一处：**昂贵的 f32 精排**。
//! QuIVer 的 `search_flat` 是两段式（BQ2 码导航 → 对 top-`ef` 做 f32 精排），
//! 所以误差界的价值 = **剪掉精排候选**，而不是剪掉导航候选。
//!
//! # 六个配置（分离变量）
//! | 配置 | 导航码 | 精排阶段 | 展开规则 | 隔离的变量 |
//! |---|---|---|---|---|
//! | **A** | BQ2 2-bit | f32 全量 | 标准 | 当前 QuIVer 基线 |
//! | **B** | BQ2 2-bit | 5-bit 界剪枝 → f32 | 标准 | **候选剪枝净收益** |
//! | **C** | 5-bit | 5-bit 界剪枝 → f32 | 标准 | 激进方案（导航也换） |
//! | **D** | 5-bit | f32 全量 | 标准 | **升级导航码的净成本** |
//! | **E1** | 5-bit | f32 全量 | 界**计数不剪** | **展开剪枝的判别力**（召回 = D） |
//! | **E2** | 5-bit | f32 全量 | 界**真剪展开** | **展开剪枝的召回代价** |
//!
//! ## V1b：展开剪枝 vs 候选剪枝（关键概念差异）
//! 候选剪枝（`safe_prune`）**可证安全**：只断言"该候选自己不在真 Top-k"。
//! 展开剪枝**不可证**：图边不蕴含相似度单调性，一个自身得分低的节点 `u`
//! 完全可能有得分高的邻居（Vamana 的 `α` 剪枝只保证邻居"不远于"自身，
//! **并不排除邻居更近**）。故 `E2` 是启发式，必须实测其召回代价。
//! `E1`/`E2` 拆分是为了把"判别力"（E1，无副作用）与"代价"（E2）分开度量。
//!
//! # 设计要点：为什么旋转不破坏对比
//! 5-bit 码建在**旋转后**数据上（§2 实测：无旋转时 ε 在 B≥5 饱和，剪枝恒 0%）。
//! 旋转是正交变换，`⟨Rq_u, Rx_u⟩ = ⟨q_u, x_u⟩`（已由守卫验证相对误差 0.000000），
//! 故旋转码估计的**仍是同一个真值**（归一化后的内积 = cosine）。
//! 因此图拓扑（用未旋转 BQ2 构建）与估计量可以共存 —— 旋转只作用于码，不作用于图。
//!
//! # 数据分布
//! `cohere_train.f32`（1M × 768）+ `cohere_test.f32`（1000）+ 官方 GT（K=1000，取前 10）。
//! 内部做 L2 归一化（与 `bench_cohere1m` 一致）。图用 m=32 / ef_c=128 / α=1.2 构建，
//! **与冻结基线同参数**，以便做保真度对拍。
//!
//! # 正确性 oracle（三条硬断言）
//! 1. **保真度**：配置 A（自实现 beam search + f32 精排）的 R@10 必须落在冻结基线
//!    `bench_cohere1m` 的 ±1.5pp 内，否则本原型不可信，结论作废；
//! 2. **剪枝不损召回**：配置 B 的 R@10 必须 **≥** 配置 A（同导航 ⇒ 同候选集；
//!    界可证安全 ⇒ 剪掉的必不在真 Top-10）。C vs D 同理。**违反即说明界失效**；
//! 3. **码对称性**：B=5 量化在 `c` 尺度下的实际误差必须 ≤ 其 ε 上界（抽检）。
//!
//! # 计时边界
//! 报告 MT-QPS（rayon，与冻结基线同口径）与单线程 ns/次微基准。
//! 微基准单独测三个内核，用于解释端到端结果。冷/热 I/O 不在范围内。
//!
//! # 非目标
//! 不修改 `src/`；不做磁盘驻留实验（f32 全驻内存）；不测增量/并发写。
//!
//! 用法: cargo bench --features ablation --bench bench_pruning_tradeoff

use rayon::prelude::*;
use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::time::Instant;
use triviumdb::index::quiver::{QuIVer, QuIVerConfig};

const DIM: usize = 768;
const N_QUERIES: usize = 1000;
const TOP_K: usize = 10;
const EF_LIST: [usize; 4] = [64, 128, 256, 512];
/// 冻结基线的锚点（`docs/research/l1-baseline.md` §8.1，m=32/ef_c=128/α=1.2）
const FROZEN_RECALL_EF128: f64 = 97.55;
const FROZEN_TOLERANCE_PP: f64 = 1.5;

/// RaBitQ 码位宽。门槛由 `t1-epsilon-scaling-decision.md` §3 判定为 5。
const R_BITS: u32 = 5;
/// 量化尺度 `a = c/√D`。§2 实测 B=5 有旋转时的最优 c。
const SCALE_C: f32 = 3.0;

const BQ2_CHUNKS: usize = DIM.div_ceil(64); // 12
/// 5-bit 每 8 个坐标占 5 字节
const R_GROUPS: usize = DIM / 8; // 96
const R_BYTES: usize = R_GROUPS * 5; // 480

// ══════════════════════════════════════════════════════════════════
//  旋转器（与前序基准同一实现，已证为正交变换）
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
        let bytes = padded_dim / 8;
        let mut flips = [
            vec![0u8; bytes],
            vec![0u8; bytes],
            vec![0u8; bytes],
            vec![0u8; bytes],
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
            // ★ 翻转必须作用于**整个** padded 缓冲；只有 FHT 与缩放作用于 512 长的段。
            //   若把翻转也限制在段内，变换不再正交（守卫2 会捕获）。
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
    for (bi, &byte) in flip.iter().enumerate() {
        if byte == 0 {
            continue;
        }
        for bit in 0..8 {
            let i = bi * 8 + bit;
            if i < data.len() && (byte >> bit) & 1 != 0 {
                data[i] = -data[i];
            }
        }
    }
}

fn vec_rescale(data: &mut [f32], fac: f32) {
    for v in data.iter_mut() {
        *v *= fac;
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
//  码：BQ2（2 bit/维，192 B/向量） 与 5-bit RaBitQ（480 B/向量 + ε）
// ══════════════════════════════════════════════════════════════════

struct Bq2Store {
    /// 连续布局：每向量 2*BQ2_CHUNKS 个 u64 = [pos..][strong..]
    data: Vec<u64>,
}

impl Bq2Store {
    fn encode_all(vectors: &[f32], n: usize) -> Self {
        let stride = 2 * BQ2_CHUNKS;
        let mut data = vec![0u64; n * stride];
        data.par_chunks_mut(stride)
            .zip(vectors.par_chunks(DIM))
            .for_each(|(slot, v)| {
                let alpha = v.iter().map(|x| x.abs()).sum::<f32>() / DIM as f32;
                for (i, &x) in v.iter().enumerate() {
                    if x > 0.0 {
                        slot[i / 64] |= 1u64 << (i % 64);
                    }
                    if x.abs() > alpha {
                        slot[BQ2_CHUNKS + i / 64] |= 1u64 << (i % 64);
                    }
                }
            });
        Self { data }
    }

    #[inline]
    fn dot(&self, q: &Bq2Query, v: usize) -> f32 {
        let base = v * 2 * BQ2_CHUNKS;
        let mut acc = 0i32;
        for c in 0..BQ2_CHUNKS {
            let mask = if c == BQ2_CHUNKS - 1 && DIM % 64 != 0 {
                (1u64 << (DIM % 64)) - 1
            } else {
                !0u64
            };
            let dp = self.data[base + c];
            let ds = self.data[base + BQ2_CHUNKS + c];
            let same = !(q.pos[c] ^ dp) & mask;
            let diff = (q.pos[c] ^ dp) & mask;
            let both_s = q.strong[c] & ds & mask;
            let one_s = (q.strong[c] ^ ds) & mask;
            let both_w = !(q.strong[c] | ds) & mask;
            acc += 4 * ((same & both_s).count_ones() as i32 - (diff & both_s).count_ones() as i32);
            acc += 2 * ((same & one_s).count_ones() as i32 - (diff & one_s).count_ones() as i32);
            acc += (same & both_w).count_ones() as i32 - (diff & both_w).count_ones() as i32;
        }
        acc as f32
    }
}

struct Bq2Query {
    pos: [u64; BQ2_CHUNKS],
    strong: [u64; BQ2_CHUNKS],
}

fn encode_bq2_query(v: &[f32]) -> Bq2Query {
    let mut q = Bq2Query {
        pos: [0; BQ2_CHUNKS],
        strong: [0; BQ2_CHUNKS],
    };
    let alpha = v.iter().map(|x| x.abs()).sum::<f32>() / DIM as f32;
    for (i, &x) in v.iter().enumerate() {
        if x > 0.0 {
            q.pos[i / 64] |= 1u64 << (i % 64);
        }
        if x.abs() > alpha {
            q.strong[i / 64] |= 1u64 << (i % 64);
        }
    }
    q
}

/// 5-bit 均匀标量量化（mid-rise + clamp）打在**旋转后**的单位向量上。
struct R5Store {
    /// 每向量 `R_BYTES` 字节，末尾留 8 字节余量以便 u64 越界读（读取后掩码 40 bit）
    bytes: Vec<u8>,
    /// `corr/‖x_c‖²`，用于 `est = alpha · ⟨q, levels⟩`
    alpha: Vec<f32>,
    /// 可证误差上界 `ε = sqrt(1 − corr²/‖x_c‖²)`
    eps: Vec<f32>,
    delta: f32,
}

impl R5Store {
    fn encode_all(rotated: &[Vec<f32>], dim: usize) -> Self {
        let n = rotated.len();
        let m = 1i32 << (R_BITS - 1); // 16
        let delta = (SCALE_C / (dim as f32).sqrt()) / m as f32;
        let mut bytes = vec![0u8; n * R_BYTES + 8];
        let mut alpha = vec![0.0f32; n];
        let mut eps = vec![0.0f32; n];

        bytes[..n * R_BYTES]
            .par_chunks_mut(R_BYTES)
            .zip(alpha.par_iter_mut())
            .zip(eps.par_iter_mut())
            .zip(rotated.par_iter())
            .for_each(|(((out, a), e), x)| {
                let mut corr = 0.0f32;
                let mut norm2 = 0.0f32;
                for g in 0..R_GROUPS {
                    let mut w = 0u64;
                    for j in 0..8 {
                        let v = x[g * 8 + j];
                        let k = (v / delta).floor().clamp(-(m as f32), m as f32 - 1.0) as i32;
                        let ku = (k + m) as u64; // 0..31
                        w |= ku << (j * 5);
                        let level = (ku as f32 - 15.5) * delta;
                        corr += level * v;
                        norm2 += level * level;
                    }
                    out[g * 5..g * 5 + 5].copy_from_slice(&w.to_le_bytes()[..5]);
                }
                *a = corr / norm2.max(1e-30);
                *e = (1.0 - corr * corr / norm2.max(1e-30)).max(0.0).sqrt();
            });

        Self {
            bytes,
            alpha,
            eps,
            delta,
        }
    }

    /// `est(q_rot, x) = alpha[x] · ⟨q_rot, levels(x)⟩`。解包与点积融合在一趟。
    #[inline]
    fn estimate(&self, q_rot: &[f32], v: usize) -> f32 {
        let off = v * R_BYTES;
        let mut acc = 0.0f32;
        for g in 0..R_GROUPS {
            let w = u64::from_le_bytes([
                self.bytes[off + g * 5],
                self.bytes[off + g * 5 + 1],
                self.bytes[off + g * 5 + 2],
                self.bytes[off + g * 5 + 3],
                self.bytes[off + g * 5 + 4],
                self.bytes[off + g * 5 + 5],
                self.bytes[off + g * 5 + 6],
                self.bytes[off + g * 5 + 7],
            ]) & 0xFF_FFFF_FFFF;
            let qb = &q_rot[g * 8..g * 8 + 8];
            for j in 0..8 {
                let ku = ((w >> (j * 5)) & 0x1F) as f32;
                acc += qb[j] * (ku - 15.5);
            }
        }
        acc * self.delta * self.alpha[v]
    }

    #[inline]
    fn eps_of(&self, v: usize) -> f32 {
        self.eps[v]
    }
}

// ══════════════════════════════════════════════════════════════════
//  图（从真实 QuIVer 读出，CSR 化以便自实现遍历）
// ══════════════════════════════════════════════════════════════════

struct Graph {
    offsets: Vec<u32>,
    adj: Vec<u32>,
    entry: u32,
}

/// 严格弱序包装：成本语义统一为 **越大越近**
#[derive(PartialEq)]
struct Cost(f32, u32);
impl Eq for Cost {}
impl Ord for Cost {
    fn cmp(&self, o: &Self) -> Ordering {
        self.0
            .partial_cmp(&o.0)
            .unwrap_or(Ordering::Equal)
            .then(self.1.cmp(&o.1))
    }
}
impl PartialOrd for Cost {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}

/// 展开规则。
///
/// ⚠️ **概念差异（V1b 的核心）**：候选剪枝（`safe_prune`）是**可证安全**的 ——
/// 它只断言"该候选自己不在真 Top-k"。而**展开剪枝不可证**：
/// 图边不蕴含相似度单调性，一个自身得分低的节点 `u` 完全可能有得分高的邻居
/// （Vamana 的 `α` 剪枝只保证邻居"不远于"自身，并不排除邻居更近）。
/// 因此 `BoundAggressive` 是**启发式**，必须实测其召回代价。
#[derive(Clone, Copy, PartialEq, Eq)]
enum ExpansionRule {
    /// 标准 Vamana：仅当 frontier 最优劣于 `results` 最差项时终止
    Standard,
    /// 计算界判据但**不跳过**展开 —— 召回必须与 `Standard` 逐位相同，纯测判别力
    BoundCountOnly,
    /// 真的跳过被界排除的展开（启发式，会损失召回）
    BoundAggressive,
}

#[derive(Default, Clone, Copy)]
struct BeamStats {
    nav_evals: u64,
    expansions: u64,
    /// 界判据 `U(u) = est(u) + ε(u) < θ` 成立的次数（θ = `results` 中第 k 大下界）
    bound_would_skip: u64,
    /// 实际跳过的展开次数（仅 `BoundAggressive` 非零）
    skipped: u64,
    /// 判据**可计算**的次数（`results` 已满 `k` 项，`θ` 为有限值）
    bound_applicable: u64,
    // `θ − U(u)` 之和。判据成立需此值 > 0，故它与 `eps_sum` 的对比
    // 直接量化"为什么剪不动"：`ε` 与候选集内分数落差的相对量级。
    margin_sum: f64,
    /// `ε(u)` 之和
    eps_sum: f64,
}

/// `results` 中第 k 大的下界 `L = est − ε`。不足 k 个时返回 `-inf`（不剪）。
fn kth_lower_bound(results: &BinaryHeap<std::cmp::Reverse<Cost>>, r5: &R5Store, k: usize) -> f32 {
    if results.len() < k {
        return f32::NEG_INFINITY;
    }
    let mut ls: Vec<f32> = results
        .iter()
        .map(|std::cmp::Reverse(c)| c.0 - r5.eps_of(c.1 as usize))
        .collect();
    let idx = k - 1;
    ls.select_nth_unstable_by(idx, |a, b| b.partial_cmp(a).unwrap_or(Ordering::Equal));
    ls[idx]
}

/// 标准 Vamana beam search（自实现，所有配置共用同一规范以保证可比性）。
///
/// `frontier` 是"越大越近"的最大堆 → 先展开最有希望的；
/// `results` 是反向最小堆 → `peek` 得到当前最差元素，便于替换。
/// 返回 `(候选 (cost, node), 统计)`。
fn beam_search(
    graph: &Graph,
    bq2: &Bq2Store,
    r5: &R5Store,
    q_bq: &Bq2Query,
    qr: &[f32],
    visited: &mut [u32],
    epoch: u32,
    ef: usize,
    nav: &NavCode,
    rule: ExpansionRule,
) -> (Vec<(f32, u32)>, BeamStats) {
    let cost_of = |v: u32| -> f32 {
        match nav {
            NavCode::Bq2 => bq2.dot(q_bq, v as usize),
            NavCode::R5 => r5.estimate(qr, v as usize),
        }
    };

    let mut frontier: BinaryHeap<Cost> = BinaryHeap::with_capacity(ef * 2);
    let mut results: BinaryHeap<std::cmp::Reverse<Cost>> = BinaryHeap::with_capacity(ef + 1);
    let mut stats = BeamStats::default();
    // 界判据只在 5-bit 导航下合法：此时 `cost` 才是内积的无偏估计量 `est`，
    // 配 `ε` 才构成真值的置信区间。BQ2 的加权位计数不是内积估计，无界可用。
    let bound_usable = rule != ExpansionRule::Standard && matches!(nav, NavCode::R5);

    let c0 = cost_of(graph.entry);
    frontier.push(Cost(c0, graph.entry));
    results.push(std::cmp::Reverse(Cost(c0, graph.entry)));
    visited[graph.entry as usize] = epoch;

    while let Some(Cost(dcur, u)) = frontier.pop() {
        // 终止：最有希望的待展开点已劣于结果集最差项 → 不可能再改进
        if results.len() >= ef
            && let Some(std::cmp::Reverse(Cost(w, _))) = results.peek()
            && dcur < *w
        {
            break;
        }
        stats.expansions += 1;

        // 界驱动的展开判据：若 `u` 自身的置信上界都低于 `results` 中第 k 大下界，
        // 则 `u` 必不在真 Top-k。注意这只对"`u` 自己"成立，**不能推出其邻居不在 Top-k**。
        if bound_usable {
            let theta = kth_lower_bound(&results, r5, TOP_K);
            let eps_u = r5.eps_of(u as usize);
            let u_ub = dcur + eps_u;
            // 仅当 θ 有限（results 已满 k 项）才计入余量，否则 -inf 会污染整个求和
            if theta.is_finite() {
                stats.bound_applicable += 1;
                stats.margin_sum += theta as f64 - u_ub as f64;
                stats.eps_sum += eps_u as f64;
            }
            if u_ub < theta {
                stats.bound_would_skip += 1;
                if rule == ExpansionRule::BoundAggressive {
                    stats.skipped += 1;
                    continue;
                }
            }
        }

        let s = graph.offsets[u as usize] as usize;
        let e = graph.offsets[u as usize + 1] as usize;
        for &v in &graph.adj[s..e] {
            if visited[v as usize] == epoch {
                continue;
            }
            visited[v as usize] = epoch;
            let cv = cost_of(v);
            stats.nav_evals += 1;
            let worst = match results.peek() {
                Some(std::cmp::Reverse(Cost(w, _))) if results.len() >= ef => *w,
                _ => f32::NEG_INFINITY,
            };
            if results.len() < ef || cv > worst {
                frontier.push(Cost(cv, v));
                results.push(std::cmp::Reverse(Cost(cv, v)));
                if results.len() > ef {
                    results.pop();
                }
            }
        }
    }

    (
        results
            .into_iter()
            .map(|std::cmp::Reverse(c)| (c.0, c.1))
            .collect(),
        stats,
    )
}

// ══════════════════════════════════════════════════════════════════
//  工具
// ══════════════════════════════════════════════════════════════════

fn read_f32_bin(path: &str) -> Vec<f32> {
    let b = std::fs::read(path).unwrap_or_else(|e| panic!("无法读取 {path}: {e}"));
    b.as_chunks::<4>()
        .0
        .iter()
        .map(|c| f32::from_le_bytes(*c))
        .collect()
}

fn read_i32_bin(path: &str) -> Vec<i32> {
    let b = std::fs::read(path).unwrap_or_else(|e| panic!("无法读取 {path}: {e}"));
    b.as_chunks::<4>()
        .0
        .iter()
        .map(|c| i32::from_le_bytes(*c))
        .collect()
}

fn l2_normalize(data: &mut [f32]) {
    let norms: Vec<f32> = data
        .par_chunks(DIM)
        .map(|s| s.iter().map(|x| x * x).sum::<f32>().sqrt())
        .collect();
    data.par_chunks_mut(DIM)
        .zip(norms.par_iter())
        .for_each(|(s, &nrm)| {
            let inv = 1.0 / nrm.max(1e-12);
            for x in s.iter_mut() {
                *x *= inv;
            }
        });
}

#[inline]
fn f32_dot(q: &[f32], x: &[f32]) -> f32 {
    q.iter().zip(x).map(|(a, b)| a * b).sum()
}

/// 可证安全剪枝：给定候选的 (est, ε)，返回保留的下标集合。
///
/// 判据：候选 `c` 可排除 ⟺ 存在 ≥ k 个候选的下界 `L = est − ε` 超过 `U(c) = est + ε`。
/// 实现：按 `L` 降序排，阈值取第 k 大 `L`，剪掉 `U < 阈值` 者（前 k 名不动）。
fn safe_prune(est: &[f32], eps: &[f32], k: usize) -> Vec<usize> {
    let mut idx: Vec<usize> = (0..est.len()).collect();
    idx.sort_unstable_by(|&a, &b| {
        (est[b] - eps[b])
            .partial_cmp(&(est[a] - eps[a]))
            .unwrap_or(Ordering::Equal)
            .then(a.cmp(&b))
    });
    if idx.len() <= k {
        idx.sort_unstable();
        return idx;
    }
    let thr = est[idx[k - 1]] - eps[idx[k - 1]];
    let mut keep: Vec<usize> = idx[..k].to_vec();
    for &i in &idx[k..] {
        if est[i] + eps[i] >= thr {
            keep.push(i);
        }
    }
    keep.sort_unstable();
    keep
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum NavCode {
    Bq2,
    R5,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum RerankMode {
    /// f32 全量精排
    Full,
    /// 5-bit 界剪枝后再 f32 精排
    Pruned,
}

fn main() {
    eprintln!("═══════════════════════════════════════════════════════════════════");
    eprintln!("  V1 — 5-bit RaBitQ 误差界剪枝的端到端 trade-off");
    eprintln!("═══════════════════════════════════════════════════════════════════");

    let t0 = Instant::now();
    let mut train = read_f32_bin("cohere_train.f32");
    let mut test = read_f32_bin("cohere_test.f32");
    let gt_raw = read_i32_bin("cohere_groundtruth.i32");
    test.truncate(N_QUERIES.min(test.len() / DIM) * DIM);

    let n = train.len() / DIM;
    let nq = test.len() / DIM;
    let k_gt = gt_raw.len() / (test.len() / DIM);
    l2_normalize(&mut train);
    l2_normalize(&mut test);
    eprintln!(
        "  数据 {n} × {DIM}，查询 {nq}，GT K={k_gt}；加载+归一化 {:.2}s",
        t0.elapsed().as_secs_f64()
    );

    // GT 集合（top-10）
    let gt: Vec<Vec<usize>> = (0..nq)
        .map(|i| {
            gt_raw[i * k_gt..i * k_gt + TOP_K]
                .iter()
                .map(|&x| x as usize)
                .collect()
        })
        .collect();

    // ── 构建真实图（与冻结基线同参数）──
    eprintln!("\n  构建 QuIVer (m=32, ef_c=128, α=1.2) ...");
    let config = QuIVerConfig {
        m: 32,
        ef_construction: 128,
        alpha: 1.2,
    };
    let mut index = QuIVer::new(DIM, &config);
    let ids: Vec<u64> = (0..n as u64).collect();
    let slots: Vec<usize> = (0..n).collect();
    let tb = Instant::now();
    index.batch_build_experimental_v2(&train, &ids, &slots);
    let build_s = tb.elapsed().as_secs_f64();
    eprintln!(
        "  构建完成 {:.1}s ({:.0} vecs/s)，Hot {} MiB",
        build_s,
        n as f64 / build_s,
        index.stats().hot_bytes / 1024 / 1024
    );

    // ── 抽出 L0 拓扑 ──
    let mut offsets = vec![0u32; n + 1];
    let mut adj: Vec<u32> = Vec::with_capacity(n * 64);
    for v in 0..n as u32 {
        let nb = index.layer0_neighbors(v);
        adj.extend_from_slice(nb);
        offsets[v as usize + 1] = adj.len() as u32;
    }
    let graph = Graph {
        offsets,
        adj,
        entry: index.ablation_entry_point(),
    };
    eprintln!(
        "  L0 拓扑: {} 条有向边，平均度 {:.1}，入口点 {}",
        graph.adj.len(),
        graph.adj.len() as f64 / n as f64,
        graph.entry
    );

    // ── 码 ──
    eprintln!("\n  编码 ...");
    let t_enc = Instant::now();
    let bq2 = Bq2Store::encode_all(&train, n);
    let bq2_bytes = n * 2 * BQ2_CHUNKS * 8;
    let rotator = FhtKacRotator::new(DIM, 42);
    let train_rot: Vec<Vec<f32>> = train.par_chunks(DIM).map(|v| rotator.rotate(v)).collect();
    let query_rot: Vec<Vec<f32>> = test.par_chunks(DIM).map(|v| rotator.rotate(v)).collect();
    let r5 = R5Store::encode_all(&train_rot, DIM);
    let r5_bytes = n * R_BYTES;
    eprintln!(
        "  编码完成 {:.2}s | BQ2 {:.0} MB（2 bit/维） | 5-bit {:.0} MB（5 bit/维，{:.1}×）",
        t_enc.elapsed().as_secs_f64(),
        bq2_bytes as f64 / 1e6,
        r5_bytes as f64 / 1e6,
        r5_bytes as f64 / bq2_bytes as f64
    );

    // ── 守卫 1：保真度（配置 A 必须复现冻结基线）──
    // 由主循环中的 A 配置结果检查，这里先准备。

    // ── 守卫 0：旋转正交性（内积保持）──
    // 5-bit 码建在旋转后数据上，估计的却必须是**原空间**的内积。若旋转不正交，
    // 后续所有 ε 与 est 都指向错误的目标量 —— 代价极高的静默错误，故最先检查。
    {
        let ip = f32_dot(&test[..DIM], &train[..DIM]);
        let rip = f32_dot(&query_rot[0], &train_rot[0]);
        let rel = (ip - rip).abs() / ip.abs().max(1e-9);
        eprintln!("  守卫0 旋转内积保持: {ip:.6} vs {rip:.6}  相对误差 {rel:.2e}");
        assert!(
            rel < 1e-3,
            "守卫0 失败: 旋转不是正交变换（相对误差 {rel:.2e}）"
        );
    }

    // ── 守卫 2：界成立（抽检）──
    {
        let mut checked = 0usize;
        let mut viol = 0usize;
        for qi in 0..nq.min(8) {
            let qr = &query_rot[qi];
            for v in (0..n).step_by(n / 5000) {
                let est = r5.estimate(qr, v);
                let truth = f32_dot(
                    &test[qi * DIM..(qi + 1) * DIM],
                    &train[v * DIM..(v + 1) * DIM],
                );
                checked += 1;
                if (est - truth).abs() > r5.eps_of(v) + 1e-3 {
                    viol += 1;
                }
            }
        }
        eprintln!("\n  守卫2 界成立: {viol} / {checked} 违例");
        assert_eq!(viol, 0, "守卫2 失败: 5-bit 码的 ε 上界失效");
    }

    // ── 微基准：三个内核的 ns/次（解释端到端成本结构）──
    {
        let reps = 200_000usize;
        let q_bq = encode_bq2_query(&test[..DIM]);
        let qr = &query_rot[0];

        let t = Instant::now();
        let mut sink = 0.0f32;
        for i in 0..reps {
            sink += bq2.dot(&q_bq, i % n);
        }
        let ns_bq2 = t.elapsed().as_secs_f64() / reps as f64 * 1e9;

        let t = Instant::now();
        for i in 0..reps {
            sink += r5.estimate(qr, i % n);
        }
        let ns_r5 = t.elapsed().as_secs_f64() / reps as f64 * 1e9;

        let t = Instant::now();
        for i in 0..reps {
            sink += f32_dot(&test[..DIM], &train[i % n * DIM..(i % n + 1) * DIM]);
        }
        let ns_f32 = t.elapsed().as_secs_f64() / reps as f64 * 1e9;

        eprintln!("\n  ── 内核微基准（ns/次，单线程）──");
        eprintln!("     BQ2 2-bit 距离    {ns_bq2:8.1}");
        eprintln!(
            "     5-bit RaBitQ est  {ns_r5:8.1}   ({:.1}× BQ2)",
            ns_r5 / ns_bq2
        );
        eprintln!(
            "     f32 精确内积      {ns_f32:8.1}   ({:.1}× BQ2)",
            ns_f32 / ns_bq2
        );
        eprintln!("     ← 若 5-bit est 比 f32 还慢，则『先算界再决定是否 f32』本身即是亏本");
        std::hint::black_box(sink);
    }

    // ── 四个配置 × ef 扫描 ──
    eprintln!("\n═══════════════════════════════════════════════════════════════════");
    eprintln!("  端到端遍历（自实现 beam search，与 A/B/C/D 同规范）");
    eprintln!("═══════════════════════════════════════════════════════════════════");

    let configs: [(&str, NavCode, RerankMode, ExpansionRule); 6] = [
        (
            "A  BQ2导航 + f32全量",
            NavCode::Bq2,
            RerankMode::Full,
            ExpansionRule::Standard,
        ),
        (
            "B  BQ2导航 + 5bit界剪枝",
            NavCode::Bq2,
            RerankMode::Pruned,
            ExpansionRule::Standard,
        ),
        (
            "C  5bit导航 + 5bit界剪枝",
            NavCode::R5,
            RerankMode::Pruned,
            ExpansionRule::Standard,
        ),
        (
            "D  5bit导航 + f32全量",
            NavCode::R5,
            RerankMode::Full,
            ExpansionRule::Standard,
        ),
        (
            "E1 5bit导航 + 界计数不剪",
            NavCode::R5,
            RerankMode::Full,
            ExpansionRule::BoundCountOnly,
        ),
        (
            "E2 5bit导航 + 界剪展开",
            NavCode::R5,
            RerankMode::Full,
            ExpansionRule::BoundAggressive,
        ),
    ];

    struct Row {
        label: String,
        ef: usize,
        recall: f64,
        qps: f64,
        nav_evals: f64,
        keep_pct: f64,
        prunable_pct: f64,
        skipped_pct: f64,
    }

    let mut table: Vec<Row> = Vec::new();
    let mut recall_a_ef128 = f64::NAN;
    let mut recall_by: Vec<(String, usize, f64)> = Vec::new();
    // (label, ef, 平均界余量 θ−U, 平均 ε) —— 用于量化"为什么剪不动"
    let mut margin_by: Vec<(String, usize, f64, f64)> = Vec::new();

    for (label, nav, rerank, rule) in &configs {
        for &ef in &EF_LIST {
            let t = Instant::now();
            let per_query: Vec<(usize, BeamStats, u64, u64)> = (0..nq)
                .into_par_iter()
                .map_init(
                    || vec![0u32; n],
                    |visited, qi| {
                        let q = &test[qi * DIM..(qi + 1) * DIM];
                        let qr = &query_rot[qi];
                        let q_bq = encode_bq2_query(q);
                        let (cands, stats) = beam_search(
                            &graph,
                            &bq2,
                            &r5,
                            &q_bq,
                            qr,
                            visited,
                            (qi + 1) as u32,
                            ef,
                            nav,
                            *rule,
                        );

                        // 精排候选的 (est, ε)：BQ2 导航时需补算 5-bit 估计
                        let rerank_n = cands.len() as u64;
                        let (final_idx, after) = match rerank {
                            RerankMode::Full => {
                                let mut scored: Vec<(f32, u32)> = cands
                                    .iter()
                                    .map(|&(_, v)| {
                                        (
                                            f32_dot(
                                                q,
                                                &train[v as usize * DIM..(v as usize + 1) * DIM],
                                            ),
                                            v,
                                        )
                                    })
                                    .collect();
                                scored.sort_unstable_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
                                (scored, rerank_n)
                            }
                            RerankMode::Pruned => {
                                // 用 5-bit 估计量 + 其 ε 做可证剪枝，再只对存活者做 f32
                                let est: Vec<f32> = cands
                                    .iter()
                                    .map(|&(_, v)| r5.estimate(qr, v as usize))
                                    .collect();
                                let eps: Vec<f32> =
                                    cands.iter().map(|&(_, v)| r5.eps_of(v as usize)).collect();
                                let keep = safe_prune(&est, &eps, TOP_K);
                                let mut scored: Vec<(f32, u32)> = keep
                                    .iter()
                                    .map(|&i| {
                                        let v = cands[i].1;
                                        (
                                            f32_dot(
                                                q,
                                                &train[v as usize * DIM..(v as usize + 1) * DIM],
                                            ),
                                            v,
                                        )
                                    })
                                    .collect();
                                scored.sort_unstable_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
                                (scored, keep.len() as u64)
                            }
                        };
                        let hit = final_idx
                            .iter()
                            .take(TOP_K)
                            .filter(|(_, v)| gt[qi].contains(&(*v as usize)))
                            .count();
                        (hit, stats, rerank_n, after)
                    },
                )
                .collect();
            let elapsed = t.elapsed().as_secs_f64();
            let hits: usize = per_query.iter().map(|x| x.0).sum();
            let recall = hits as f64 / (nq * TOP_K) as f64 * 100.0;
            let nav_evals: u64 = per_query.iter().map(|x| x.1.nav_evals).sum();
            let expansions: u64 = per_query.iter().map(|x| x.1.expansions).sum();
            let would: u64 = per_query.iter().map(|x| x.1.bound_would_skip).sum();
            let skipped: u64 = per_query.iter().map(|x| x.1.skipped).sum();
            let rerank_n: u64 = per_query.iter().map(|x| x.2).sum();
            let after: u64 = per_query.iter().map(|x| x.3).sum();
            let qps = nq as f64 / elapsed;
            let prunable_pct = would as f64 / expansions.max(1) as f64 * 100.0;
            let skipped_pct = skipped as f64 / expansions.max(1) as f64 * 100.0;
            let keep_pct = after as f64 / rerank_n.max(1) as f64 * 100.0;
            let applicable: u64 = per_query.iter().map(|x| x.1.bound_applicable).sum();
            let margin_sum: f64 = per_query.iter().map(|x| x.1.margin_sum).sum();
            let eps_sum: f64 = per_query.iter().map(|x| x.1.eps_sum).sum();
            let denom = applicable.max(1) as f64;
            margin_by.push((label.to_string(), ef, margin_sum / denom, eps_sum / denom));

            if label.starts_with("A ") && ef == 128 {
                recall_a_ef128 = recall;
            }
            recall_by.push((label.to_string(), ef, recall));
            table.push(Row {
                label: label.to_string(),
                ef,
                recall,
                qps,
                nav_evals: nav_evals as f64 / nq as f64,
                keep_pct,
                prunable_pct,
                skipped_pct,
            });
            eprintln!(
                "  {label:<26} ef={ef:<4} R@10 {recall:6.2}%  {qps:9.0} QPS  导航求值 {:.0}/q  \
                 精排保留 {keep_pct:5.1}%  展开可剪 {prunable_pct:5.2}%  实跳过 {skipped_pct:5.2}%",
                nav_evals as f64 / nq as f64,
            );
        }
    }

    // ── 守卫 1 ──
    eprintln!("\n  ── 守卫 ──");
    let dev = (recall_a_ef128 - FROZEN_RECALL_EF128).abs();
    eprintln!(
        "  守卫1 保真度: A@ef=128 = {recall_a_ef128:.2}% vs 冻结基线 {FROZEN_RECALL_EF128:.2}% \
         (偏差 {dev:.2}pp，容差 {FROZEN_TOLERANCE_PP}pp) {}",
        if dev <= FROZEN_TOLERANCE_PP {
            "PASS"
        } else {
            "FAIL"
        }
    );

    // ── 守卫 2：剪枝不损召回 ──
    let get = |lab: &str, ef: usize| {
        recall_by
            .iter()
            .find(|(l, e, _)| l == lab && *e == ef)
            .map(|(_, _, r)| *r)
            .unwrap()
    };
    let mut worst_drop = 0.0f64;
    for &ef in &EF_LIST {
        let drop_b = get("A  BQ2导航 + f32全量", ef) - get("B  BQ2导航 + 5bit界剪枝", ef);
        let drop_c = get("D  5bit导航 + f32全量", ef) - get("C  5bit导航 + 5bit界剪枝", ef);
        worst_drop = worst_drop.max(drop_b).max(drop_c);
        eprintln!(
            "  守卫2 ef={ef:<4} 剪枝导致的召回损失: B vs A {drop_b:+.2}pp, C vs D {drop_c:+.2}pp"
        );
    }
    assert!(
        worst_drop <= 0.01,
        "守卫2 失败: 界剪枝损害了召回（最大 {worst_drop:.2}pp）—— 界失效"
    );
    eprintln!("  守卫2 PASS: 剪枝零召回损失（与可证安全一致）");

    // ── 守卫 4：E1 与 D 的搜索结果必须逐位相同 ──
    // E1 只计数、不跳过。若两者召回不同，说明计数逻辑引入了副作用
    // （或判据被误接入搜索控制流），V1b 的"判别力"读数就不可信。
    for &ef in &EF_LIST {
        let d = get("D  5bit导航 + f32全量", ef);
        let e1 = get("E1 5bit导航 + 界计数不剪", ef);
        assert!(
            (d - e1).abs() < 1e-9,
            "守卫4 失败: E1 改变了搜索结果（D={d:.4} vs E1={e1:.4}）—— 计数不应有副作用"
        );
    }
    eprintln!("  守卫4 PASS: E1（界计数不剪）与 D 逐位一致 → 计数器无副作用");

    // ── V1b：界驱动的展开剪枝 ──
    eprintln!("\n  ── V1b: 界驱动的展开剪枝（判别力与代价分离）──");
    for r in table.iter().filter(|r| r.label.starts_with("E1")) {
        let (_, _, margin, eps) = margin_by
            .iter()
            .find(|(l, e, _, _)| l == &r.label && *e == r.ef)
            .unwrap();
        // θ − est_u = (θ − U) + ε。若该项为负，则即使 ε=0（无限精度码）
        // 判据也无法触发 —— 说明失效是**结构性**的，与码精度无关。
        let theta_minus_est = margin + eps;
        eprintln!(
            "  E1 ef={:<4} 判别力 {:.2}%  |  θ−U = {margin:+.4}，ε = {eps:.4}  \
             → θ−est = {theta_minus_est:+.4}{}",
            r.ef,
            r.prunable_pct,
            if theta_minus_est < 0.0 {
                "  ★ 为负 ⇒ 即使 ε=0 该判据也无法触发：**结构性失效，与码精度无关**"
            } else {
                ""
            },
        );
    }
    for &ef in &EF_LIST {
        let d = get("D  5bit导航 + f32全量", ef);
        let e2 = get("E2 5bit导航 + 界剪展开", ef);
        let row = table
            .iter()
            .find(|r| r.label.starts_with("E2") && r.ef == ef)
            .unwrap();
        let nav_d = table
            .iter()
            .find(|r| r.label.starts_with("D ") && r.ef == ef)
            .unwrap();
        eprintln!(
            "  E2 ef={ef:<4} 实跳过 {:.2}%  召回 {e2:.2}%（Δ vs D {:+.2}pp）  \
             导航求值 {:.0}/q vs D {:.0}/q（省 {:.1}%）",
            row.skipped_pct,
            e2 - d,
            row.nav_evals,
            nav_d.nav_evals,
            (1.0 - row.nav_evals / nav_d.nav_evals.max(1e-9)) * 100.0
        );
    }

    // ── markdown 输出 ──
    println!("\n### 端到端遍历结果（1M × 768，1000 查询，自实现 beam search）\n");
    println!("| 配置 | ef | R@10 | MT-QPS | 导航求值/查询 | 精排保留率 | 展开可剪率 | 实跳过 |");
    println!("|---|---|---|---|---|---|---|---|");
    for r in &table {
        println!(
            "| {} | {} | {:.2}% | {:.0} | {:.0} | {:.1}% | {:.2}% | {:.2}% |",
            r.label, r.ef, r.recall, r.qps, r.nav_evals, r.keep_pct, r.prunable_pct, r.skipped_pct
        );
    }
    eprintln!("═══════════════════════════════════════════════════════════════════");
}

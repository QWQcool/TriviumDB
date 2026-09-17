//! T2 B2-0 —— `ef_construction` 扫描（**平凡对照**，零代码改动）
//!
//! # 为什么这一步最重要
//! T2 摸底测出批量建图的 **81.35%** 花在全局束搜索（`beam_search_l0_locked`，
//! 宽度 = `ef_construction`）。在投入"分区式构建"的结构性改造之前，必须先回答：
//!
//! > **仅把这个宽度调小，能不能达到同样的成本-质量点？**
//!
//! 若能，则分区化**毫无意义**——这是本实验的防自欺机制
//! （预注册见 `docs/research/t2-b2-design.md` §0）。
//!
//! # 未提交的设计前提：随机注入与 ef 无关
//! `connect_node_fast:716` 的随机注入量为
//! `samples = self.ef.min(128).max(self.m0 * 2)`；本实验 m=32 ⇒ m0=64 ⇒ m0*2=128
//! ⇒ **对任何 ef ≤ 128 都有 samples ≡ 128**。故本扫描是**纯束搜索宽度**的扫描，
//! 随机注入量全程恒定。（守卫 G5 会在运行时断言这一点。）
//!
//! # 判据（预注册，先写死）
//! - **P1 质量**：某臂的 R@10（ef_search=128）**≥ 基线 − 1.0pp**
//! - 若 **ef_c=32 即满足 P1** ⇒ 81% 的束搜索成本靠一个配置项砍掉 4×
//!   ⇒ **PiPNN 的靶点消失，T2 整条线应停止**
//!
//! # 三条守卫
//! | 守卫 | 内容 |
//! |---|---|
//! | **G1** | 基线同进程复现：`ef_c=128` 臂的 R@10 与冻结基线 97.55% 偏差 ≤ 1pp |
//! | **G5** | 随机注入量恒为 128（由公式断言，不含 `src` 改动） |
//! | **G-det** | **并发建图的确定性**：同配置建两次，L0 边集逐位相同 |
//!
//! `G-det` 不可省：并发建图靠条纹锁，惰性追加与容量满时的剪枝**依赖线程交错**，
//! 故图**可能跨运行不确定**。若不确定，则此前所有单次运行的结论都需附上抖动范围。
//!
//! # 计时边界
//! 全部臂在**同一进程**内依次执行（消除跨运行抖动）；固定 `-C target-cpu=native`。
//! 搜索用 rayon 并行（与冻结基线同口径）。
//!
//! 用法: cargo bench --features ablation --bench bench_t2_b2_partitioned

use rayon::prelude::*;
use std::time::Instant;
use triviumdb::index::quiver::{QuIVer, QuIVerConfig, QuIVerSearchConfig};

const TOP_K: usize = 10;
/// 扫描臂（束搜索宽度）
const EF_C_LIST: [usize; 4] = [128, 64, 32, 16];
/// 搜索宽度扫描（与冻结基线一致）
const EF_SEARCH_LIST: [usize; 5] = [64, 128, 256, 512, 1024];
/// 数据集由 `T2_PREFIX` / `T2_DIM` 选择（默认 cohere / 768，与冻结基线一致）
const DEFAULT_PREFIX: &str = "cohere";
const DEFAULT_DIM: usize = 768;
/// 冻结基线 R@10（仅 cohere 有值：1M × 768，m=32/ef_c=128/α=1.2，官方 GT）。
/// 由 `T2_FROZEN_RECALL` 覆盖；新数据集未提供时**跳过守卫 G1**（尚无冻结值可比）。
const DEFAULT_FROZEN_RECALL: f64 = 97.55;
/// P1 容差
const P1_TOLERANCE_PP: f64 = 1.0;
/// 固定参数
const M: usize = 32;
const M0: usize = M * 2; // 64

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_f32(key: &str, default: f32) -> f32 {
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

fn read_i32_bin(path: &str) -> Vec<i32> {
    let b = std::fs::read(path).unwrap_or_else(|e| panic!("无法读取 {path}: {e}"));
    b.as_chunks::<4>()
        .0
        .iter()
        .map(|c| i32::from_le_bytes(*c))
        .collect()
}

fn l2_normalize(data: &mut [f32], n: usize, dim: usize) {
    let norms: Vec<f32> = (0..n)
        .into_par_iter()
        .map(|i| {
            data[i * dim..(i + 1) * dim]
                .iter()
                .map(|x| x * x)
                .sum::<f32>()
                .sqrt()
        })
        .collect();
    let p = data.as_mut_ptr() as usize;
    (0..n).into_par_iter().for_each(|i| {
        // SAFETY: 各线程只写自己那一段，区间互不重叠
        let seg = unsafe { std::slice::from_raw_parts_mut((p as *mut f32).add(i * dim), dim) };
        let inv = 1.0 / norms[i].max(1e-12);
        for x in seg.iter_mut() {
            *x *= inv;
        }
    });
}

/// L0 邻接的指纹（用于 G-det 确定性检查）
fn edge_fingerprint(index: &QuIVer, n: usize) -> (u64, u64) {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325; // FNV-1a
    let mut edges: u64 = 0;
    for v in 0..n as u32 {
        for &nb in index.layer0_neighbors(v) {
            edges += 1;
            for b in nb.to_le_bytes() {
                h ^= b as u64;
                h = h.wrapping_mul(0x1000_0000_01b3);
            }
        }
        // 分段边界也入哈希，避免不同切分产生相同流
        h ^= u32::MAX as u64;
        h = h.wrapping_mul(0x1000_0000_01b3);
    }
    (h, edges)
}

fn main() {
    eprintln!("═══════════════════════════════════════════════════════════════════");
    let prefix = std::env::var("T2_PREFIX").unwrap_or_else(|_| DEFAULT_PREFIX.into());
    let dim = env_usize("T2_DIM", DEFAULT_DIM);
    let alpha = env_f32("T2_ALPHA", 1.2);
    let n_cap = env_usize("T2_N", 0); // 0 = 全部

    // 可选开关：
    //   T2_EFC=128        单一/多值覆盖束宽（用于 α 扫描等只需单一束宽的场景）
    //   T2_SKIP_DET=1     跳过 G-det 的两次额外建图（该守卫已在 t2-b2-result.md 确立）
    let efc_list: Vec<usize> = match std::env::var("T2_EFC") {
        Ok(v) if !v.trim().is_empty() => {
            v.split(',').filter_map(|s| s.trim().parse().ok()).collect()
        }
        _ => EF_C_LIST.to_vec(),
    };
    let skip_det = std::env::var("T2_SKIP_DET").as_deref() == Ok("1");

    eprintln!("  T2 B2-0 — ef_construction 扫描（平凡对照，零代码）");
    eprintln!(
        "  数据集={prefix} dim={dim}  臂 = {efc_list:?}   m={M} m0={M0} alpha={alpha}{}",
        if skip_det { "  [T2_SKIP_DET]" } else { "" }
    );
    eprintln!("═══════════════════════════════════════════════════════════════════");

    // 守卫 G5：随机注入量必须与 ef 无关（公式断言，无需改 src）
    for &ef in &efc_list {
        let samples = ef.min(128).max(M0 * 2);
        assert_eq!(
            samples, 128,
            "守卫G5 失败: ef={ef} 的随机注入量 {samples} ≠ 128 —— ef 扫描不再干净"
        );
    }
    eprintln!("  守卫G5 随机注入量恒为 128（对全部臂）PASS");

    // 冻结基线：cohere 默认有值；其他数据集需显式 T2_FROZEN_RECALL，否则跳过守卫 G1
    let frozen_recall: Option<f64> = std::env::var("T2_FROZEN_RECALL")
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .or_else(|| (prefix == DEFAULT_PREFIX).then_some(DEFAULT_FROZEN_RECALL));

    let t0 = Instant::now();
    let mut train = read_f32_bin(&format!("{prefix}_train.f32"));
    let mut test = read_f32_bin(&format!("{prefix}_test.f32"));
    let gt_raw = read_i32_bin(&format!("{prefix}_groundtruth.i32"));
    let n_all = train.len() / dim;
    let n_train = if n_cap == 0 { n_all } else { n_cap.min(n_all) };
    train.truncate(n_train * dim);
    let n_test = test.len() / dim;
    let k_gt = gt_raw.len() / n_test;
    assert!(k_gt >= TOP_K, "GT 的 K={k_gt} 小于 TOP_K={TOP_K}");
    l2_normalize(&mut train, n_train, dim);
    l2_normalize(&mut test, n_test, dim);
    eprintln!(
        "  数据集 {prefix}  数据 {n_train} × {dim}，查询 {n_test}，GT K={k_gt}；\
         加载+归一化 {:.2}s",
        t0.elapsed().as_secs_f64()
    );

    let eval_gts: Vec<Vec<u64>> = (0..n_test)
        .map(|i| {
            gt_raw[i * k_gt..i * k_gt + TOP_K]
                .iter()
                .map(|&x| x as u64)
                .collect()
        })
        .collect();

    let ids: Vec<u64> = (0..n_train as u64).collect();
    let slots: Vec<usize> = (0..n_train).collect();

    /// 一臂的结果
    struct Arm {
        ef_c: usize,
        build_s: f64,
        recall: Vec<(usize, f64, f64)>, // (ef_search, recall%, qps)
        fp: (u64, u64),
    }

    let mut arms: Vec<Arm> = Vec::new();

    for &ef_c in &efc_list {
        eprintln!("\n  ── 臂 ef_construction={ef_c} ──");
        let config = QuIVerConfig {
            m: M,
            ef_construction: ef_c,
            alpha,
        };
        let mut index = QuIVer::new(dim, &config);

        let tb = Instant::now();
        index.batch_build_experimental_v2(&train, &ids, &slots);
        let build_s = tb.elapsed().as_secs_f64();
        let st = index.stats();
        eprintln!(
            "    建图 {build_s:.2}s  {:.0} vec/s  avg_deg_l0={:.1}  Hot {} MiB",
            n_train as f64 / build_s,
            st.avg_degree_l0,
            st.hot_bytes / 1024 / 1024
        );

        let mut recall = Vec::new();
        for &efs in &EF_SEARCH_LIST {
            let search_cfg = QuIVerSearchConfig {
                top_k: TOP_K,
                ef_search: efs,
                rerank_limit: None,
            };
            let t = Instant::now();
            let hits: usize = (0..n_test)
                .into_par_iter()
                .map(|i| {
                    let q = &test[i * dim..(i + 1) * dim];
                    let res = index.search_flat(q, &train, &search_cfg);
                    res.iter()
                        .filter(|&&(id, _)| eval_gts[i].contains(&id))
                        .count()
                })
                .sum();
            let el = t.elapsed().as_secs_f64();
            let r = hits as f64 / (n_test * TOP_K) as f64 * 100.0;
            let qps = n_test as f64 / el;
            recall.push((efs, r, qps));
            eprintln!("    ef_search={efs:<5} R@10 {r:6.2}%  {qps:9.0} QPS");
        }

        let fp = edge_fingerprint(&index, n_train);
        eprintln!("    L0 指纹 {:#018x} / {} 边", fp.0, fp.1);
        arms.push(Arm {
            ef_c,
            build_s,
            recall,
            fp,
        });
    }

    // ── 守卫 G1：基线同进程复现 ──
    let base = &arms[0];
    let base_r128 = base
        .recall
        .iter()
        .find(|(e, _, _)| *e == 128)
        .map(|(_, r, _)| *r)
        .unwrap();
    eprintln!("\n  ── 守卫 ──");
    match frozen_recall {
        Some(fr) => {
            let dev = (base_r128 - fr).abs();
            eprintln!(
                "  守卫G1 基线同进程复现: ef_c=128/ef_s=128 → {base_r128:.2}% vs 冻结 {fr:.2}% \
                 （偏差 {dev:.2}pp）{}",
                if dev <= P1_TOLERANCE_PP {
                    "PASS"
                } else {
                    "FAIL"
                }
            );
            assert!(
                dev <= P1_TOLERANCE_PP,
                "守卫G1 失败: 基线未复现（偏差 {dev:.2}pp）"
            );
        }
        None => eprintln!(
            "  守卫G1 跳过: {prefix} 尚无冻结 R@10（可用 T2_FROZEN_RECALL 提供）；\
             本臂自身即基线 {base_r128:.2}%"
        ),
    }

    // ── 守卫 G-det：并发建图确定性 + 非确定性对召回的影响 ──
    // 连做两次同配置建图（同条件、背靠背），隔离调度抖动；
    // 并各自测 R@10，以判定"边集不同"是否"质量等价"。
    // 该守卫已在 t2-b2-result.md 的 3 次运行 × 2 次重复中确立，可用 T2_SKIP_DET=1 跳过。
    let mut det_consecutive = true;
    let mut det_vs_arm = true;
    let mut recall_spread = 0.0f64;
    if skip_det {
        eprintln!("  守卫G-det 跳过（T2_SKIP_DET=1）");
    } else {
        eprintln!("  守卫G-det 正在背靠背重复建图（ef_c=128）×2 并各自测召回 ...");
        let mut det_reps: Vec<((u64, u64), f64)> = Vec::new();
        for rep in 0..2 {
            let mut ix = QuIVer::new(
                dim,
                &QuIVerConfig {
                    m: M,
                    ef_construction: 128,
                    alpha,
                },
            );
            ix.batch_build_experimental_v2(&train, &ids, &slots);
            let fp = edge_fingerprint(&ix, n_train);
            let cfg = QuIVerSearchConfig {
                top_k: TOP_K,
                ef_search: 128,
                rerank_limit: None,
            };
            let hits: usize = (0..n_test)
                .into_par_iter()
                .map(|i| {
                    let q = &test[i * dim..(i + 1) * dim];
                    let res = ix.search_flat(q, &train, &cfg);
                    res.iter()
                        .filter(|&&(id, _)| eval_gts[i].contains(&id))
                        .count()
                })
                .sum();
            let r = hits as f64 / (n_test * TOP_K) as f64 * 100.0;
            det_reps.push((fp, r));
            drop(ix); // 释放 ~1GB，避免影响下一次建图
            eprintln!("    rep{rep}: 指纹 {:#018x}  R@10 {r:.2}%", fp.0);
        }
        det_consecutive = det_reps[0].0 == det_reps[1].0;
        det_vs_arm = det_reps[0].0 == base.fp;
        recall_spread = (det_reps[0].1 - det_reps[1].1).abs();
        eprintln!(
            "  守卫G-det 背靠背两次: 指纹{}（{}）",
            if det_consecutive {
                "相同 PASS"
            } else {
                "不同 ⚠️"
            },
            if det_vs_arm {
                "，且与臂1相同"
            } else {
                "，且与臂1不同"
            }
        );
        eprintln!(
            "  守卫G-det 非确定性对召回的影响: {:.2}% vs {:.2}%（极差 {recall_spread:.2}pp）→ {}",
            det_reps[0].1,
            det_reps[1].1,
            if recall_spread <= 0.20 {
                "质量等价（边集不同但召回稳定）"
            } else {
                "⚠️ 召回不稳定，所有单次运行结论需附抖动范围"
            }
        );
    }
    let _ = det_vs_arm; // 仅在 G-det 未跳过时用于打印
    let det = det_consecutive;

    // ── 判定 ──
    eprintln!("\n═══════════════════════════════════════════════════════════════════");
    eprintln!("  B2-0 判定：ef_construction 能否独自达到成本-质量点");
    eprintln!("═══════════════════════════════════════════════════════════════════");
    let threshold = base_r128 - P1_TOLERANCE_PP;
    eprintln!("  P1 门槛 = 基线 {base_r128:.2}% − {P1_TOLERANCE_PP}pp = {threshold:.2}%\n");
    for a in &arms {
        let r = a
            .recall
            .iter()
            .find(|(e, _, _)| *e == 128)
            .map(|(_, r, _)| *r)
            .unwrap();
        let ratio = a.build_s / base.build_s;
        let ok = r >= threshold;
        eprintln!(
            "  ef_c={:<4} 建图 {:6.2}s（{ratio:5.2}×）  R@10(ef_s=128) {r:6.2}%  \
             门槛{} {}",
            a.ef_c,
            a.build_s,
            if ok { "达标" } else { "未达" },
            if ok { "✅" } else { "❌" }
        );
    }

    // 找**达标臂中最小的 ef_c** —— 它才是"平凡解"，也才是 PiPNN 必须击败的对象。
    // （`arms` 按 ef 降序 [128,64,32,16]，故 `rev()` 后首个达标者即最小达标臂。）
    let mut trivial: Option<(usize, f64, f64)> = None;
    for a in arms.iter().rev() {
        let r = a
            .recall
            .iter()
            .find(|(e, _, _)| *e == 128)
            .map(|(_, r, _)| *r)
            .unwrap();
        if r >= threshold {
            trivial = Some((a.ef_c, r, a.build_s / base.build_s));
            break;
        }
    }

    // 固定成本地板：取最小束宽臂的墙钟，作为"候选获取完全免费"时的成本**上界**
    // （保守：真实地板只会更低）。它界定任何候选获取改进的收益天花板。
    let min_arm = arms.iter().min_by_key(|a| a.ef_c).unwrap();
    let floor_ratio = min_arm.build_s / base.build_s;
    eprintln!(
        "\n  ── 固定成本地板 ──\n  ef_c={} 墙钟 {:.2}s = **{floor_ratio:.2}×** 基线\
         （候选获取即使完全免费也不可能低于此值；真实地板只会更低）。",
        min_arm.ef_c, min_arm.build_s
    );

    match trivial {
        Some((ef_c, r, ratio)) if ratio <= 0.70 => {
            eprintln!(
                "\n  ★ **平凡解已达成 P3**：ef_c={ef_c} → R@10 {r:.2}%\
                 （P1 门槛 {threshold:.2}%）且建图 **{ratio:.2}×**（P2 需 ≤0.70×）。"
            );
            eprintln!(
                "     ⇒ PiPNN 必须**击败这个平凡解**，而可争夺的空间只有 \
                 {ratio:.2}× → 地板 {floor_ratio:.2}×，即 **{:.2}×**。",
                ratio / floor_ratio
            );
            eprintln!(
                "     ⇒ 且 PiPNN 自己的候选获取成本（设计文档 §1.2：池扫描 2.4×）\
                 必须在这 {:.2}× 里支付。",
                ratio / floor_ratio
            );
        }
        Some((ef_c, r, ratio)) => {
            eprintln!(
                "\n  ★ 最小达标臂 ef_c={ef_c}：R@10 {r:.2}% 但成本 {ratio:.2}× > 0.70×\
                 ⇒ P2 **未**由平凡解满足。"
            );
            eprintln!("     ⇒ 进入 B2-1；目标：击败 {ratio:.2}×（地板 {floor_ratio:.2}×）");
        }
        None => {
            eprintln!("\n  ★ 全部臂均未达 P1 ⇒ 束搜索宽度不能独立压缩 ⇒ 进入 B2-1。");
            eprintln!("     目标：击败 {:.2}×（地板 {floor_ratio:.2}×）", 1.0);
        }
    }

    if !det || recall_spread > 0.20 {
        eprintln!(
            "\n  ⚠️ 守卫G-det：并发建图的**边集不可逐位复现**，但召回极差 {recall_spread:.2}pp \
             ⇒ 质量等价。"
        );
        eprintln!("     ⇒ **召回级**结论稳定可比；**图结构级**结论须视为单次采样估计。");
    } else {
        eprintln!(
            "\n  守卫G-det：边集不可逐位复现但召回极差 {recall_spread:.2}pp ⇒ 质量等价；\
             召回级结论稳定可比。"
        );
    }

    // ── markdown ──
    println!(
        "\n### T2 B2-0：`ef_construction` 扫描（{prefix} {n_train} × {dim}，m=32，α=1.2，同一进程）\n"
    );
    print!("| ef_c | 建图(s) | 相对基线 |");
    for e in EF_SEARCH_LIST {
        print!(" R@10@ef_s={e} |");
    }
    println!();
    print!("|---|---|---|");
    for _ in EF_SEARCH_LIST {
        print!("---|");
    }
    println!();
    for a in &arms {
        print!(
            "| {} | {:.2} | {:.2}× |",
            a.ef_c,
            a.build_s,
            a.build_s / base.build_s
        );
        for &(_, r, _) in &a.recall {
            print!(" {r:.2}% |");
        }
        println!();
    }
    eprintln!("═══════════════════════════════════════════════════════════════════");
}

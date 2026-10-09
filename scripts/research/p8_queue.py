"""P8 队列：把"剩下所有要跑的实验"按顺序一次跑完（无人值守，可关窗口）。

设计
----
* **顺序执行**，每步独立日志 `.tmp/p8_*.log`；任何一步失败都记录并继续（不阻塞后面）。
* 每步都打印 `[开始]/[完成]` 与耗时，最后写 `results/t2/p8_queue_summary.json`。
* 只用 `.venv` 的解释器与仓库内脚本；cargo 步骤自带 PATH/RUSTFLAGS。

队列内容与论文的对应
--------------------
| 步 | 实验 | 论文位置 |
|---|---|---|
| 1 | IVF-Flat vs RaBitQ 召回诊断（nprobe 是否生效 / ParameterSpace 是否穿透） | 决定 §5.6(b) 能否写 |
| 2 | RaBitQ+Refine 修正版（直接赋 nprobe/k_factor） | §5.6(b) |
| 3 | IVF-Flat 控制臂（同 nprobe 网格） | §5.6(b) |
| 4 | RaBitQ 在 `gist960c` 上跑一格 | §5.6(b) / §6.4 类型③ |
| 5-6 | PQ 跨档位补两格（`sift128c` / `wolt_clipc`） | §5.6(a) / §8.7 |
| 7-8 | 同召回对照重算（含新两格） | §5.6(a) |
| 9 | `gauss960` 竞品曲线（"索引无关崩塌"第二个证人） | §6.4 类型② |
| 10 | 引擎侧开关复现 `rc` 臂（原数据 + `TRIVIUM_SIGN_ROTATE`） | §8.6 |

用法：`.venv/Scripts/python.exe scripts/research/p8_queue.py`（建议用 `Start-Process` 放后台）
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
TMP = ROOT / ".tmp"
CARGO = str(Path.home() / ".cargo" / "bin")
ROT_SEED = "20260923"

BASES = os.environ.copy()


def env(**kw):
    e = BASES.copy()
    e.update({k: str(v) for k, v in kw.items()})
    return e


def quiver_log(prefix):
    """找该臂的 QuIVer 曲线日志（用于同召回对照），找不到就不传。"""
    for pat in (f"p7q_{prefix}_seed1.log", f"u19_{prefix}_w1.log", f"*{prefix}*w1*.log"):
        hits = sorted(TMP.glob(pat))
        if hits:
            return str(hits[0])
    return None


def steps():
    s = []
    s.append(("1 诊断 IVF-Flat vs RaBitQ",
              [PY, "scripts/research/ivf_recall_diagnostic.py", "cohere", "768", "1024"],
              env(), "p8_1_diag.log"))
    s.append(("2 RaBitQ+Refine 修正版（cohere）",
              [PY, "scripts/research/bench_rabitq_refine.py", "cohere", "768", "1024"],
              env(RA_BITQ_NPROBES="64,256,512,1024", RA_BITQ_KFACTORS="20,200",
                  TRIVIUM_MT_THREADS="32"), "p8_2_rabitq_cohere.log"))
    s.append(("3 IVF-Flat 控制臂（cohere）",
              [PY, "scripts/research/bench_rabitq_refine.py", "cohere", "768", "1024"],
              env(RA_CONTROL="ivfflat", RA_BITQ_NPROBES="64,256,512,1024",
                  TRIVIUM_MT_THREADS="32"), "p8_3_ivfflat_control.log"))
    s.append(("4 RaBitQ 在 gist960c",
              [PY, "scripts/research/bench_rabitq_refine.py", "gist960c", "960", "1024"],
              env(RA_BITQ_NPROBES="64,256", RA_BITQ_KFACTORS="20,200",
                  TRIVIUM_MT_THREADS="32"), "p8_4_rabitq_gist960c.log"))
    for prefix, dim in (("sift128c", 128), ("wolt_clipc", 512)):
        s.append((f"5/6 PQ 跨档位 {prefix}",
                  [PY, "benches/bench_baselines.py"],
                  env(BASELINES="faiss_ivfpq", TRIVIUM_ANN_DIM=dim,
                      TRIVIUM_ANN_TRAIN=str(ROOT / f"{prefix}_train.f32"),
                      TRIVIUM_ANN_TEST=str(ROOT / f"{prefix}_test.f32"),
                      TRIVIUM_ANN_GT=str(ROOT / f"{prefix}_groundtruth.i32"),
                      TRIVIUM_OPQ_NLIST="1024", TRIVIUM_OPQ_M_PQ="64",
                      TRIVIUM_MT_THREADS="32"),
                  f"p7_pq_{prefix}.log"))
        argv = [PY, "scripts/research/pq_matched_recall.py", prefix]
        qv = quiver_log(prefix)
        if qv:
            argv += ["--quiv", qv]
        s.append((f"7/8 同召回对照 {prefix}", argv, env(), f"p8_matched_{prefix}.log"))
    s.append(("9 gauss960 竞品曲线",
              [PY, "scripts/research/baseline_competitors.py"],
              env(T2_PREFIX="gauss960", T2_DIM="960", BL_THREADS="32"),
              "p8_9_gauss960_competitors.log"))
    s.append(("10 引擎侧旋转复现 rc 臂（gist960c + SIGN_ROTATE + NAV_WEIGHTED）",
              # ⚠️ 必须给 cargo **绝对路径**：Windows 的 CreateProcess 用**父进程的 PATH** 解析裸命令名，
              #    `env=` 里的 PATH 只影响子进程环境、不影响可执行文件查找 ⇒ 裸 "cargo" 会
              #    FileNotFoundError（2026-10-09 首跑队列时本步因此失败，重试才补上）。
              [str(Path.home() / ".cargo" / "bin" / "cargo.exe"),
               "bench", "--features", "ablation", "--bench", "bench_t2_b2_partitioned"],
              env(PATH=CARGO + os.pathsep + BASES.get("PATH", ""),
                  RUSTFLAGS="-C target-cpu=native", TRIVIUM_SIGN_ROTATE=ROT_SEED,
                  TRIVIUM_NAV_WEIGHTED="1", T2_PREFIX="gist960c", T2_DIM="960",
                  T2_EFC="128", T2_SKIP_DET="1", T2_ALPHA="", T2_FROZEN_RECALL=""),
              "p8_10_engine_rc.log"))
    return s


def main():
    only = os.environ.get("P8_ONLY", "").strip()
    summary, t_all = [], time.time()
    started_str = time.strftime("%Y-%m-%d %H:%M:%S")  # 真实开始时刻（此前每步重写摘要把 started 写成"最后写入时刻"）
    print(f"\n===== P8 队列开始 {started_str} =====")
    for name, argv, e, logname in steps():
        if only and not name.startswith(only):
            continue
        log = TMP / logname
        print(f"\n[{time.strftime('%H:%M:%S')}] >>> {name}\n    log → .tmp/{logname}", flush=True)
        t0 = time.time()
        ok, note = True, ""
        try:
            with open(log, "w", encoding="utf-8", errors="replace") as fh:
                p = subprocess.run(argv, cwd=ROOT, env=e, stdout=fh,
                                   stderr=subprocess.STDOUT, timeout=5400)
            ok = p.returncode == 0
            note = f"exit={p.returncode}"
        except Exception as ex:                                           # noqa: BLE001
            ok, note = False, f"{type(ex).__name__}: {ex}"
        dt = time.time() - t0
        print(f"[{time.strftime('%H:%M:%S')}] {'OK ' if ok else '失败'} {name}  "
              f"{dt / 60:.1f} min  {note}", flush=True)
        summary.append({"step": name, "log": f".tmp/{logname}", "ok": ok,
                        "minutes": round(dt / 60, 2), "note": note})
        (ROOT / "results" / "t2" / "p8_queue_summary.json").write_text(
            json.dumps({"started": started_str,
                        "steps": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n===== P8 队列结束，总耗时 {(time.time() - t_all) / 60:.1f} min =====")
    for r in summary:
        print(f"  {'✅' if r['ok'] else '❌'} {r['step']:<52} {r['minutes']:>6.1f} min  {r['log']}")


if __name__ == "__main__":
    main()

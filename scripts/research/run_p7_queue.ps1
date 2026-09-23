# P7 队列：按用户给的顺序把剩下能跑的实验串起来（每步独立日志，便于监督）。
# 用法：pwsh -NoProfile -File scripts/research/run_p7_queue.ps1 [stage]
#   stage = A（items 3b/4/5/6）| B（items 7/9 + 8）| C（items 11/12）| all
param([string]$stage = "A")
$ErrorActionPreference = "Continue"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
$env:RUSTFLAGS = "-C target-cpu=native"
$env:PYTHONIOENCODING = "utf-8"
$env:TRIVIUM_MT_THREADS = "32"

function Log($msg) { Write-Output ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) }

function Bench($prefix, $dim, $nav, $rot, $tag) {
    $env:T2_PREFIX = $prefix; $env:T2_DIM = "$dim"; $env:T2_EFC = "128"
    $env:T2_SKIP_DET = "1"; $env:T2_ALPHA = ""; $env:T2_FROZEN_RECALL = ""
    $env:TRIVIUM_NAV_WEIGHTED = $nav
    if ($rot) { $env:TRIVIUM_SIGN_ROTATE = $rot } else { $env:TRIVIUM_SIGN_ROTATE = "off" }
    Log "bench $prefix dim=$dim nav=$nav rot=$rot -> .tmp/p7q_$tag.log"
    cargo bench --features ablation --bench bench_t2_b2_partitioned 2>&1 |
        Tee-Object -FilePath ".tmp\p7q_$tag.log" |
        Select-String -Pattern "ef_search=\d+\s+R@10|建图\s+[\d.]+s" |
        ForEach-Object { ($_.Line -replace "\x1b\[[0-9;]*m", "").Trim() }
}

if ($stage -in @("A", "all")) {
    # ---- item 3b：PQ 在 glove100c（dim=100 ⇒ m_pq 必须整除 100） ----
    Log "item3b: PQ on glove100c"
    $env:TRIVIUM_ANN_DIM = "100"
    $env:TRIVIUM_ANN_TRAIN = "glove100c_train.f32"
    $env:TRIVIUM_ANN_TEST = "glove100c_test.f32"
    $env:TRIVIUM_ANN_GT = "glove100c_groundtruth.i32"
    $env:TRIVIUM_OPQ_NLIST = "1024"; $env:TRIVIUM_OPQ_M_PQ = "50"
    $env:BASELINES = "faiss_ivfpq"
    & .venv\Scripts\python.exe benches\bench_baselines.py 2>&1 |
        Tee-Object -FilePath ".tmp\p7_pq_glove100c.log" | Select-Object -Last 12

    # ---- item 4：论文的 IVF+RaBitQ+Refine（cohere） ----
    Log "item4: IVF+RaBitQ+Refine on cohere"
    & .venv\Scripts\python.exe scripts\research\bench_rabitq_refine.py cohere 768 1024 2>&1 |
        Tee-Object -FilePath ".tmp\p7_rabitq_cohere.log" | Select-Object -Last 12

    # ---- item 5：旋转+去均值组合臂 ----
    Log "item5: rotate-center gist960 -> gist960rc"
    & .venv\Scripts\python.exe scripts\research\gist960_collapse_prepare.py --rotate-center gist960:960 2>&1 |
        Tee-Object -FilePath ".tmp\p7_rotcenter_gist960.log" |
        Select-String -Pattern "任务不变性|OK\] 写出|负值占比" | ForEach-Object { $_.Line.Trim() }
    Log "item5: bench gist960rc"
    Bench "gist960rc" 960 "0" "" "gist960rc_w0"
    Bench "gist960rc" 960 "1" "" "gist960rc_w1"

    # ---- item 6：引擎侧旋转开关在 VIBE 行上的端到端 ----
    Log "item6: engine rotation on ccnews_nomic"
    Bench "ccnews_nomic" 768 "0" "20260923" "ccnews_rot"
}

if ($stage -in @("B", "all")) {
    # ---- item 7/9：VIBE 剩余 5 行：判据 + 两个导航臂 ----
    foreach ($d in @(@("arxiv_nomic", 768), @("codesearch_jina", 768), @("gooaq_roberta", 768),
                     @("landmark_nomic", 768), @("landmark_dino", 768))) {
        $p = $d[0]; $dm = $d[1]
        Log "item9: gate + bench $p"
        $env:GATE_K = "3"
        & .venv\Scripts\python.exe scripts\research\deployability_gate.py $p 2>&1 |
            Tee-Object -FilePath ".tmp\p7q_gate_$p.log" | Select-String -Pattern "^  $p" | ForEach-Object { $_.Line.Trim() }
        Bench $p $dm "0" "" "${p}_w0"
        Bench $p $dm "1" "" "${p}_w1"
    }

    # ---- item 8：位预算天花板 ----
    Log "item8: bit budget"
    foreach ($d in @(@("coco_nomic", 768), @("gist960", 960), @("gauss960", 960))) {
        & .venv\Scripts\python.exe scripts\research\bit_budget_ceiling.py $d[0] $d[1] 2>&1 |
            Tee-Object -FilePath ".tmp\p7q_bit_$($d[0]).log" |
            Select-String -Pattern "bits/维|^\s+\d+\s" | ForEach-Object { $_.Line.Trim() }
    }
}

if ($stage -in @("C", "all")) {
    # ---- item 12：探针 K=5 ----
    Log "item12: gate with K=5"
    $env:GATE_K = "5"
    & .venv\Scripts\python.exe scripts\research\deployability_gate.py 2>&1 |
        Tee-Object -FilePath ".tmp\p7q_gate_k5.log" | Select-String -Pattern "^\| " | Select-Object -Last 30

    # ---- item 11：关键集 3 次独立建图（多种子 CI） ----
    Log "item11: multi-seed CI"
    foreach ($d in @(@("gist960c", 960), @("sift128c", 128), @("glove100c", 100),
                     @("wolt_clipc", 512), @("coherec", 768))) {
        for ($i = 1; $i -le 3; $i++) {
            Bench $d[0] $d[1] "0" "" "$($d[0])_seed$i"
        }
    }
}
Log "stage $stage 完成"

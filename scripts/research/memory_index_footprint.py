"""P4-B（G10）：索引常驻内存对拍 —— 论文宣称"热内存少 4.7× / <1.3 GB per 1M"。

**测什么**：索引本身占用的字节数（不含原始数据集）。
- QuIVer 侧：bench 自己打印的 `Hot X MiB`（工程口径，取自 `.tmp/b2_*.log`；随维度的增量已核对 = 2 bit/维）。
- 竞品侧：hnswlib `save_index()` 落盘大小（其内存布局与文件布局一致）；
  FAISS 用 `faiss.serialize_index()` 的字节长度（索引序列化 = 其内存内容）。
  ⇒ 三者都是"索引自己的字节数"，可比；原始向量不重复计入（QuIVer 不存原始向量，竞品存）。

用法：`.venv/Scripts/python.exe scripts/research/memory_index_footprint.py [prefix] [dim]`
"""
import gc
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]

M, EFC, THREADS = 32, 128, 32

QUIVER_HOT_MIB = {  # 取自 .tmp/b2_*.log 的 `Hot X MiB`（1M 向量）
    "cohere": (768, 675.0),
    "coherek512": (512, 614.0),
    "coherek256": (256, 553.0),
    "coherek128": (128, 522.0),
    "cohere960pad": (960, 720.0),
    "gist960": (960, 720.0),
    "sift128": (128, 522.0),
    "glove100": (100, None),
}


def load(prefix, dim):
    tr = np.fromfile(ROOT / f"{prefix}_train.f32", dtype=np.float32).reshape(-1, dim)
    print(f"  train {tr.shape}  = {tr.nbytes / 2**30:.2f} GiB (float32, 仅用于构建)")
    return tr


def mb(n):
    return n / 2**20


def report(name, idx_bytes, n, dim, extra=""):
    print(f"  {name:<14} 索引 {mb(idx_bytes):9.1f} MiB（{idx_bytes / n:8.1f} B/向量）{extra}")
    return idx_bytes


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "cohere"
    dim = int(sys.argv[2]) if len(sys.argv) > 2 else 768
    tr = load(prefix, dim)
    n = tr.shape[0]
    out = {"prefix": prefix, "dim": dim, "n": int(n), "m": M, "ef_c": EFC}

    print(f"\n{'=' * 78}\n  {prefix}  n={n:,} dim={dim}  (M={M}, ef_c={EFC}, threads={THREADS})\n{'=' * 78}")

    # ── QuIVer：用 bench 自报的 Hot 内存（工程口径）────────────────────
    quiver = QUIVER_HOT_MIB.get(prefix, (dim, None))[1]
    if quiver:
        print(f"  {'QuIVer(BQ)':<14} 索引 {quiver:9.1f} MiB（{quiver * 2**20 / n:8.1f} B/向量）[bench 自报 Hot]")
        out["quiver_hot_mib"] = quiver
    else:
        print(f"  {'QuIVer(BQ)':<14} 未记录（在该 dim 上按 0.25 B/维 + 图 估算见文末模型）")

    # ── hnswlib：save_index 落盘大小 ────────────────────────────────
    try:
        import hnswlib
        idx = hnswlib.Index(space="ip", dim=dim)
        idx.init_index(max_elements=n, ef_construction=EFC, M=M)
        idx.set_num_threads(THREADS)
        idx.add_items(tr, np.arange(n))
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "h.bin")
            idx.save_index(p)
            b = os.path.getsize(p)
        out["hnswlib_bytes"] = b
        report("hnswlib", b, n, dim, "（含原始 float32 向量副本）")
        del idx
        gc.collect()
    except Exception as e:                                   # noqa: BLE001
        print(f"  hnswlib 跳过：{type(e).__name__}: {e}")

    # ── FAISS HNSW / IVF：serialize_index 长度 ───────────────────────
    try:
        import faiss
        faiss.omp_set_num_threads(THREADS)
        for name, factory in (("FAISS-HNSW", f"HNSW{M}"), ("FAISS-IVF", None)):
            if factory:
                idx = faiss.index_factory(dim, factory, faiss.METRIC_INNER_PRODUCT)
            else:
                nlist = max(1, int(4 * np.sqrt(n)))
                q = faiss.IndexFlatIP(dim)
                idx = faiss.IndexIVFFlat(q, dim, nlist, faiss.METRIC_INNER_PRODUCT)
                idx.train(tr)
            idx.add(tr)
            blob = faiss.serialize_index(idx)
            out[f"{name.lower()}_bytes"] = len(blob)
            report(name, len(blob), n, dim, "（faiss.serialize_index 长度）")
            del idx, blob
            gc.collect()
    except Exception as e:                                   # noqa: BLE001
        print(f"  FAISS 跳过：{type(e).__name__}: {e}")

    print(f"\n  ── 与论文宣称对拍 ──")
    if quiver and "hnswlib_bytes" in out:
        r = out["hnswlib_bytes"] / (quiver * 2**20)
        print(f"  QuIVer 相对 hnswlib 的热内存比 = 1 : {r:.2f}（论文宣称 4.7×）")
        print(f"  每 1M 向量：QuIVer {quiver:.0f} MiB（论文宣称 <1.3 GB）"
              f" / hnswlib {mb(out['hnswlib_bytes']):.0f} MiB")
    print(f"\n  ── 2-bit 模型（解释随维度的增量）──")
    print(f"  码 = 2 bit/维 = 0.25 B/维/向量 ⇒ {quiver or 0:.0f} MiB 中约 "
          f"{0.25 * dim * n / 2**20:.0f} MiB 是码，其余是图/结构")

    (ROOT / "results" / "t2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "t2" / f"memory_footprint_{prefix}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] 写出 results/t2/memory_footprint_{prefix}.json")


if __name__ == "__main__":
    main()

"""并行下载 VIBE HDF5（7 个文件并发 + 断点续传）。

`hf_hub_download` 在本机不动（.incomplete 恒为 0 B，HF 缓存 0 GB），
但直连 CDN 的 range 请求正常（hf-mirror ≈2.0 MB/s、huggingface ≈1.5 MB/s）
⇒ 改用 requests 直接流式下载，7 个文件并发以叠加带宽。

用法：`.venv/Scripts/python.exe scripts/research/download_vibe_parallel.py [--only a b ...]`
环境变量：`VIBE_ENDPOINT`（默认 https://hf-mirror.com）
"""
import os
import sys
import threading
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "vibe_hdf5"
REPO = "vector-index-bench/vibe"
FILES = [
    "coco-nomic-768-normalized.hdf5",              # 1.2 GiB
    "ccnews-nomic-768-normalized.hdf5",            # 1.4 GiB
    "landmark-nomic-768-normalized.hdf5",          # 2.2 GiB
    "landmark-dino-768-cosine.hdf5",               # 2.2 GiB
    "arxiv-nomic-768-normalized.hdf5",             # 3.9 GiB
    "codesearchnet-jina-768-cosine.hdf5",          # 4.0 GiB
    "gooaq-distilroberta-768-normalized.hdf5",     # 4.3 GiB
]
ENDPOINT = os.environ.get("VIBE_ENDPOINT", "https://hf-mirror.com")
CHUNK = 1 << 20
LOCK = threading.Lock()


def log(msg):
    with LOCK:
        print(f"  {time.strftime('%H:%M:%S')} {msg}", flush=True)


def fetch(name, retries=6):
    url = f"{ENDPOINT}/datasets/{REPO}/resolve/main/{name}"
    out = DEST / name
    for attempt in range(1, retries + 1):
        pos = out.stat().st_size if out.exists() else 0
        headers = {"Range": f"bytes={pos}-"} if pos else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=90) as r:
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                total = pos + int(r.headers.get("Content-Length", 0))
                mode = "ab" if r.status_code == 206 else "wb"
                if mode == "wb":
                    pos = 0
                got, mark = pos, pos
                with open(out, mode) as fh:
                    for chunk in r.iter_content(CHUNK):
                        fh.write(chunk)
                        got += len(chunk)
                        if got - mark >= 256 << 20:
                            mark = got
                            log(f"{name}: {got / 2**30:.2f}/{total / 2**30:.2f} GiB")
            if out.stat().st_size >= total and total > 0:
                log(f"[OK] {name}  {out.stat().st_size / 2**30:.2f} GiB")
                return True
            log(f"[重试 {attempt}] {name} 只到 {out.stat().st_size / 2**30:.2f} GiB")
        except Exception as e:                                            # noqa: BLE001
            log(f"[重试 {attempt}] {name}: {type(e).__name__}: {str(e)[:70]}")
            time.sleep(2 * attempt)
    log(f"[失败] {name}")
    return False


def main():
    DEST.mkdir(exist_ok=True)
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else FILES
    log(f"端点 {ENDPOINT}，目标 {len(only)} 个文件，并行下载")
    threads = [threading.Thread(target=fetch, args=(n,), daemon=False) for n in only]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ok = sum(1 for n in only if (DEST / n).exists())
    log(f"完成 {ok}/{len(only)}；目录合计 "
        f"{sum(f.stat().st_size for f in DEST.glob('*.hdf5')) / 2**30:.1f} GiB")


if __name__ == "__main__":
    main()

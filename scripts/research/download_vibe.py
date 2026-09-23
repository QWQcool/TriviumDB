"""下载 VIBE（vector-index-bench/vibe）的 7 个 HDF5 ⇒ 交给 convert_hdf5_to_f32.py 转成 .f32。

对应 `bench_sensitivity.rs` 里的名字：arxiv-nomic / ccnews-nomic / coco-nomic /
codesearch-jina / gooaq-roberta / landmark-nomic / landmark-dino。

用法：`.venv/Scripts/python.exe scripts/research/download_vibe.py [--check]`
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

REPO = "vector-index-bench/vibe"
FILES = [
    "arxiv-nomic-768-normalized.hdf5",
    "ccnews-nomic-768-normalized.hdf5",
    "coco-nomic-768-normalized.hdf5",
    "codesearchnet-jina-768-cosine.hdf5",
    "gooaq-distilroberta-768-normalized.hdf5",
    "landmark-nomic-768-normalized.hdf5",
    "landmark-dino-768-cosine.hdf5",
]
DEST = Path(__file__).resolve().parents[2] / "vibe_hdf5"


def main():
    check = "--check" in sys.argv
    DEST.mkdir(exist_ok=True)
    info = {f.rfilename: (f.size or 0) for f in HfApi().list_repo_tree(REPO, repo_type="dataset")
            if getattr(f, "rfilename", "").endswith(".hdf5")}
    total = sum(info.get(f, 0) for f in FILES)
    print(f"目标 {len(FILES)} 个文件，合计 {total / 2**30:.1f} GiB（HF 报告值）")
    for f in FILES:
        print(f"  {f:<46} {info.get(f, 0) / 2**20:8.1f} MiB")
    if check:
        return
    for f in FILES:
        target = DEST / f
        if target.exists() and target.stat().st_size == info.get(f, 0):
            print(f"  [跳过] {f} 已完整")
            continue
        print(f"  [下载] {f} ...", flush=True)
        p = hf_hub_download(repo_id=REPO, repo_type="dataset", filename=f,
                            local_dir=str(DEST))
        print(f"  [OK] {p}  {Path(p).stat().st_size / 2**20:.1f} MiB", flush=True)
    print(" 全部下载完成")


if __name__ == "__main__":
    main()

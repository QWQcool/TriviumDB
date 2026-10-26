"""使用 PyPI triviumdb 0.8.10 在新目录生成跨版本升级样本。"""

import importlib.metadata
from pathlib import Path
import sys

from triviumdb import TriviumDB

assert importlib.metadata.version("triviumdb") == "0.8.10", "样本生成需要安装 PyPI 0.8.10"
target = Path(sys.argv[1])
target.mkdir(exist_ok=False)
db = TriviumDB(str(target / "sample.tdb"), dim=4, dtype="f32",
    load_text_index=True, auto_build_quiver=False)
for index in range(4):
    node = db.insert([1.0, float(index), 0.0, 0.0], {"content": "测试正文 alpha", "index": index})
    db.index_text(node, "测试正文 alpha " + str(index))
    db.index_keyword(node, "测试别名" + str(index))
db.build_text_index()
db.flush()
db.close()

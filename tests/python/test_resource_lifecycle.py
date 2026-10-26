"""已关闭对象、原生句柄和跨语言 Hook 的生命周期回归。"""

import ctypes
import gc
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import weakref

import triviumdb

CASE = json.loads((Path(__file__).resolve().parents[1] / "contracts/lifecycle_cases.json").read_text(encoding="utf-8"))


class Hook:
    pass


class ResourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="tdb Python 资源生命周期-"))
        self.held = []
        self.sequence = 0

    def tearDown(self):
        for db in self.held:
            db.close()
        self.held.clear()
        gc.collect()
        shutil.rmtree(self.root)

    def create(self, **options):
        directory = self.root / str(self.sequence)
        self.sequence += 1
        directory.mkdir()
        file = directory / "sample.tdb"
        db = triviumdb.TriviumDB(str(file), dim=CASE["dimension"], auto_build_quiver=False, **options)
        db.insert_with_id(CASE["node_id"], CASE["vector"], CASE["original_payload"])
        return db, file, directory

    def assert_released(self, directory):
        if sys.platform == "win32":
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            for file in directory.iterdir():
                if not file.is_file():
                    continue
                handle = kernel.CreateFileW(str(file), 0xC0000000, 0, None, 3, 0x80, None)
                self.assertNotEqual(handle, ctypes.c_void_p(-1).value, f"关闭后仍占用 {file}：{ctypes.get_last_error()}")
                kernel.CloseHandle(handle)
        moved = directory.with_suffix(".moved")
        os.rename(directory, moved)
        os.rename(moved, directory)

    def test_close_modes_release_files_with_live_objects(self):
        for dtype in CASE["dtypes"]:
            for mode in ["close", "with", "with_exception", "timeout", "shutdown"]:
                with self.subTest(dtype=dtype, mode=mode):
                    db, file, directory = self.create(dtype=dtype)
                    if mode == "close":
                        db.close()
                    elif mode.startswith("with"):
                        try:
                            with db:
                                if mode == "with_exception":
                                    raise ValueError("测试调用方异常")
                        except ValueError:
                            pass
                    elif mode == "timeout":
                        self.assertTrue(db.close_timeout(CASE["close_timeout_ms"]))
                    else:
                        db.request_shutdown()
                        deadline = time.monotonic() + CASE["close_timeout_ms"] / 1000
                        while db.shutdown_status()["phase"] != "closed":
                            self.assertLess(time.monotonic(), deadline, "关闭未在期限内完成")
                            time.sleep(0.001)
                    self.held.append(db)
                    for read in [
                        lambda: db.get(CASE["node_id"]), lambda: db.get_payload(CASE["node_id"]),
                        lambda: CASE["node_id"] in db, lambda: len(db), db.all_node_ids,
                        lambda: db.get_edges(CASE["node_id"]), lambda: db.get_edge(CASE["node_id"], 2, "关联"),
                        lambda: db.get_incoming_edges(CASE["node_id"]), lambda: db.neighbors(CASE["node_id"]),
                        db.graph_stats, db.validate_graph, db.list_unique_indexes, db.index_info, db.clear_search_state,
                    ]:
                        with self.assertRaisesRegex(RuntimeError, "Database closed|数据库已关闭"):
                            read()
                    self.assert_released(directory)
                    reader = triviumdb.TriviumDB(str(file), dim=CASE["dimension"], dtype=dtype, access_mode="read_only", auto_build_quiver=False)
                    self.assertEqual(reader.get_payload(CASE["node_id"]), CASE["original_payload"])
                    reader.close()
                    self.held.append(reader)
                    self.assert_released(directory)

    def test_manifest_survives_sync_and_async_close(self):
        for asynchronous in [False, True]:
            db, file, directory = self.create()
            db.publish_generation_manifest("关闭制品")
            before = {p.name: p.read_bytes() for p in directory.iterdir() if not p.name.endswith(".lock")}
            if asynchronous:
                self.assertTrue(db.close_timeout(CASE["close_timeout_ms"]))
            else:
                db.close()
            self.assertEqual(before, {name: (directory / name).read_bytes() for name in before})
            reader = triviumdb.TriviumDB(str(file), dim=CASE["dimension"], access_mode="immutable", auto_build_quiver=False)
            self.assertEqual(len(reader), 1)
            reader.close()
            self.held.extend([db, reader])
            self.assert_released(directory)

    def test_hook_clear_close_and_unreachable_cycle_release_references(self):
        for mode in ["clear", "replace", "close", "timeout", "cycle", "rejected"]:
            db, _, directory = self.create()
            hook = Hook()
            reference = weakref.ref(hook)
            if mode == "cycle":
                hook.db = db
            if mode == "rejected":
                db.close()
                with self.assertRaisesRegex(RuntimeError, "Database closed|数据库已关闭"):
                    db.set_hook(hook)
            else:
                db.set_hook(hook)
            if mode == "clear":
                db.clear_hook()
            elif mode == "replace":
                db.set_hook(Hook())
            elif mode == "close":
                db.close()
            elif mode == "timeout":
                self.assertTrue(db.close_timeout(CASE["close_timeout_ms"]))
            if mode != "cycle":
                self.held.append(db)
            del hook, db
            gc.collect()
            self.assertIsNone(reference(), f"{mode} 未释放 Hook")
            if mode in ["close", "timeout", "cycle"]:
                self.assert_released(directory)

    def test_close_releases_ffi_library(self):
        source = self.root / "hook.rs"
        source.write_text("pub fn marker() -> u32 { 1 }", encoding="utf-8")
        extension = "dll" if sys.platform == "win32" else "dylib" if sys.platform == "darwin" else "so"
        for asynchronous in [False, True]:
            library = self.root / f"hook-{asynchronous}.{extension}"
            subprocess.run(["rustc", "--crate-type=cdylib", str(source), "-o", str(library)], check=True)
            db, _, _ = self.create()
            db.load_ffi_hook(str(library))
            if asynchronous:
                self.assertTrue(db.close_timeout(CASE["close_timeout_ms"]))
            else:
                db.close()
            self.held.append(db)
            library.unlink()


if __name__ == "__main__":
    unittest.main()

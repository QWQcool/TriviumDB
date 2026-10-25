"""Python 公共 API 跨层契约测试。

覆盖 Prepared TQL、一等 Path/List、四类属性索引、存储诊断和历史入口迁移错误。
"""

import json
import os
import tempfile

import triviumdb


def run_lifecycle_contract(root: str) -> None:
    case_path = os.path.join(os.path.dirname(__file__), "..", "contracts", "lifecycle_cases.json")
    with open(case_path, encoding="utf-8") as source:
        case = json.load(source)
    for dtype in case["dtypes"]:
        runtime = triviumdb.ResourceRuntime(**case["runtime"])
        db = triviumdb.TriviumDB(os.path.join(root, f"lifecycle-{dtype}.tdb"),
            dim=case["dimension"], dtype=dtype, memory_limit_mb=case["database_memory_limit_mb"],
            auto_build_quiver=False, runtime=runtime)
        db.insert_with_id(case["node_id"], case["vector"], case["original_payload"])
        snapshot = os.path.join(root, f"snapshot-{dtype}")
        restored = os.path.join(root, f"restored-{dtype}")
        manifest = db.create_snapshot(snapshot, case["generation_id"])
        assert manifest["node_count"] == 1 and manifest["complete"]
        db.update_payload(case["node_id"], case["later_payload"])
        db.insert_with_id(case["later_node_id"], case["vector"], {})
        try:
            db.create_snapshot(snapshot, case["generation_id"])
        except FileExistsError:
            pass
        else:
            raise AssertionError("不得覆盖已有快照")
        assert triviumdb.verify_snapshot(snapshot, runtime)["node_count"] == 1
        assert triviumdb.restore_snapshot(snapshot, restored, runtime)["generation_id"] == case["generation_id"]
        try:
            triviumdb.restore_snapshot(snapshot, restored, runtime)
        except FileExistsError:
            pass
        else:
            raise AssertionError("不得覆盖已有恢复目标")
        reader = triviumdb.TriviumDB(os.path.join(restored, case["database_file"]),
            dim=case["dimension"], dtype=dtype, access_mode="immutable",
            memory_limit_mb=case["database_memory_limit_mb"], runtime=runtime)
        assert reader.get_payload(case["node_id"]) == case["original_payload"]
        assert case["later_node_id"] not in reader
        assert reader.close_timeout(case["close_timeout_ms"])
        assert triviumdb.verify_snapshot(restored, runtime)["node_count"] == 1
        db.request_shutdown()
        assert db.close_timeout(case["close_timeout_ms"])
        assert db.shutdown_status()["phase"] == "closed"
        assert db.close_timeout(0)
        stats = runtime.stats()
        assert stats["attached_databases"] == 0
        assert stats["active_maintenance_tasks"] == 0
        assert stats["reserved_maintenance_bytes"] == 0
        assert stats["peak_reserved_bytes"] <= stats["memory_limit"]


def run_resource_contract(root: str) -> None:
    source_path = os.path.join(os.path.dirname(__file__), "..", "contracts", "resource_cases.json")
    with open(source_path, encoding="utf-8") as source:
        case = json.load(source)
    mb = 1024 * 1024
    for dtype in case["dtypes"]:
        runtime = triviumdb.ResourceRuntime(**case["runtime"])

        def check(phase):
            stats = runtime.stats()
            for field, expected in case["expected"][phase].items():
                assert stats[field] == expected, (dtype, phase, field, stats)
            assert stats["active_tasks"] == 0
            assert stats["reserved_workspace_bytes"] == 0
            assert stats["peak_worker_threads"] <= case["runtime"]["max_threads"]

        def open_db(name, memory):
            return triviumdb.TriviumDB(
                os.path.join(root, f"resource-{dtype}-{name}.tdb"), dtype=dtype,
                dim=case["database"]["dim"], memory_limit_mb=memory,
                auto_build_quiver=False, runtime=runtime,
            )

        first = open_db("first", case["database"]["memory_limit_mb"])
        second = open_db("second", case["database"]["memory_limit_mb"])
        check("opened")
        try:
            open_db("rejected", case["overbook_mb"])
        except triviumdb.ResourceBudgetError:
            pass
        else:
            raise AssertionError("超额开库必须返回资源异常")
        assert not os.path.exists(os.path.join(root, f"resource-{dtype}-rejected.tdb"))
        first.set_memory_limit(case["resize_mb"])
        check("resized")
        try:
            second.set_memory_limit(case["failed_resize_mb"])
        except triviumdb.ResourceBudgetError:
            pass
        else:
            raise AssertionError("扩容失败必须保留原配额")
        check("resized")
        first.set_memory_limit(case["database"]["memory_limit_mb"])
        first.insert_with_id(101, case["vector"], {"owner": "first"})
        second.insert_with_id(202, case["vector"], {"owner": "second"})
        assert first.search_exact(case["vector"], 1)[0].id == 101
        assert second.search_exact(case["vector"], 1)[0].id == 202
        first.close()
        check("closed_one")
        replacement = open_db("replacement", case["replacement_mb"])
        check("replaced")
        second.close()
        replacement.close()
        check("closed_all")
        assert runtime.stats()["peak_reserved_bytes"] <= case["runtime"]["memory_limit_mb"] * mb
    for options in [{"max_threads": 65}, {"max_threads": -1}]:
        try:
            triviumdb.ResourceRuntime(**options)
        except (ValueError, OverflowError, RuntimeError):
            pass
        else:
            raise AssertionError("无效线程额度必须被拒绝")
    try:
        triviumdb.TriviumDB(os.path.join(root, "bad-runtime.tdb"), runtime={})
    except TypeError:
        pass
    else:
        raise AssertionError("运行时参数必须是原生资源句柄")


def run_shared_contract(root: str) -> None:
    contract_path = os.path.join(os.path.dirname(__file__), "..", "contracts", "public_cases.json")
    with open(contract_path, encoding="utf-8") as source:
        contract = json.load(source)
    assert contract["schema_version"] == 1
    path = os.path.join(root, "shared-contract.tdb")
    db = triviumdb.TriviumDB(path, dim=contract["setup"]["dimension"])
    for node in contract["setup"]["nodes"]:
        db.insert_with_id(node["id"], node["vector"], node["payload"])
    for edge in contract["setup"]["edges"]:
        db.link(edge["source"], edge["target"], edge["label"], edge["weight"])
    for case in contract["cases"]:
        expected = case["expected"]
        if case["operation"] == "get_payload":
            payload = db.get_payload(case["node_id"])
            assert payload[expected["field"]] == expected["value"], case["name"]
        elif case["operation"] == "prepared_tql":
            prepared = db.prepare_tql(case["tql"])
            rows = db.execute_prepared_tql(prepared, case.get("parameters", {}))
            assert len(rows) == expected["row_count"], case["name"]
            assert rows[0].row[expected["column"]] == expected["value"], case["name"]
        elif case["operation"] == "tql_path":
            rows = db.tql(case["tql"])
            assert rows[0].row["path"] == expected["path"], case["name"]
        elif case["operation"] == "prepared_missing_parameter":
            prepared = db.prepare_tql(case["tql"])
            try:
                db.execute_prepared_tql(prepared, case.get("parameters", {}))
            except RuntimeError as error:
                assert any(needle in str(error) for needle in expected["error_contains_any"])
            else:
                raise AssertionError(case["name"])
        elif case["operation"] == "text_lifecycle":
            parameters = case["parameters"]
            db.index_text(1, parameters["old_text"])
            db.index_keyword(1, parameters["keyword"])
            db.index_keyword(1, parameters["keyword"])
            db.index_keyword(2, parameters["keyword"])
            db.build_text_index()
            db.index_text(1, parameters["new_text"])
            for phase in ["before_delete", "after_delete"]:
                if phase == "after_delete":
                    db.delete(1)
                for check in expected[phase]:
                    assert len(db.tql(check["query"])) == check["count"], case["name"]
        else:
            raise AssertionError(f"未知共享契约操作: {case['operation']}")
    db.close()
    try:
        db.build_text_index()
    except RuntimeError:
        pass
    else:
        raise AssertionError("关闭后的文本构建错误必须透传")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="triviumdb-python-public-api-") as root:
        run_lifecycle_contract(root)
        run_resource_contract(root)
        run_shared_contract(root)
        path = os.path.join(root, "api.tdb")
        db = triviumdb.TriviumDB(path, dim=2)
        db.insert_with_id(1, [1.0, 0.0], {"kind": "a", "score": 1, "tenant": "t", "region": "r"})
        db.insert_with_id(2, [0.9, 0.1], {"kind": "b", "score": 2, "tenant": "t", "region": "r"})
        db.link(1, 2, "next", 1.0)

        stages: list[str] = []

        class FullHook:
            def on_pre_search(self, query, ctx):
                stages.append("pre")
                return query

            def on_custom_recall(self, query, ctx):
                stages.append("custom")
                return None

            def on_post_recall(self, hits, ctx):
                stages.append("post_recall")
                return hits

            def on_pre_graph_expand(self, hits, ctx):
                stages.append("pre_graph")
                return hits

            def on_rerank(self, hits, ctx):
                stages.append("rerank")
                return hits

            def on_post_search(self, hits, ctx):
                stages.append("post")
                return hits

        db.set_hook(FullHook())
        db.search_with_context([1.0, 0.0], top_k=2, expand_depth=1, min_score=0.0)
        assert {"pre", "custom", "post_recall", "pre_graph", "rerank", "post"} <= set(stages)
        db.clear_hook()

        class BrokenHook:
            def on_pre_search(self, query, ctx):
                raise RuntimeError("python-hook-failure")

        db.set_hook(BrokenHook())
        try:
            db.search_with_context([1.0, 0.0], top_k=2)
            raise AssertionError("Hook 异常必须传播")
        except RuntimeError as error:
            assert "python-hook-failure" in str(error)
        db.clear_hook()

        db.create_index("kind")
        db.create_ordered_index("score")
        db.create_composite_index(["tenant", "region"])
        db.create_bitmap_index("region")
        indexes = db.index_info()
        assert len(indexes) == 4
        assert next(item for item in indexes if item["kind"] == "composite")["fields"] == [
            "tenant",
            "region",
        ]

        storage = db.storage_info()
        assert storage["database_format_current"] == 9
        assert storage["property_index_format"] == 6
        assert storage["node_count"] == 2

        vector_prepared = db.prepare_tql(
            "SEARCH VECTOR [$x, $y] TOP 1 RETURN *"
        )
        assert vector_prepared.parameter_names() == ["x", "y"]
        vector_rows = db.execute_prepared_tql(vector_prepared, {"x": 1, "y": 0.0})
        assert vector_rows[0].row["_"].get("id") == 1

        prepared = db.prepare_tql(
            'FIND {kind: "a"} AS seed WITH seed RETURN seed, $bonus + 1 AS score'
        )
        assert prepared.parameter_names() == ["bonus"]
        prepared_rows = db.execute_prepared_tql(prepared, {"bonus": 4})
        assert len(prepared_rows) == 1
        assert prepared_rows[0].row["score"] == 5
        try:
            db.execute_prepared_tql(prepared, {})
        except RuntimeError as error:
            assert "缺少参数" in str(error) or "missing parameter" in str(error)
        else:
            raise AssertionError("缺少 Prepared TQL 参数必须失败")

        rows = db.tql(
            "SEARCH VECTOR [1, 0] TOP 1 AS seed WITH seed shortest_paths seed TO [2] "
            "LABEL next AS route WITH route RETURN path(route) AS path"
        )
        assert rows[0].row["path"] == [1, 2]

        try:
            db.tql_mut('FIND {kind: "a"} RETURN *')
        except RuntimeError as error:
            assert "API 已移除" in str(error) or "API removed" in str(error)
        else:
            raise AssertionError("tql_mut 读查询必须失败")
        db.close()


if __name__ == "__main__":
    main()

"""通过已安装的原生绑定验证类型身份、完整解析和打开准入。"""
import json
from pathlib import Path
import triviumdb


def expect_error(action, code):
    try:
        action()
    except (triviumdb.TriviumDBError, triviumdb.CapacityError) as error:
        assert error.code == code
        return error
    raise AssertionError(f"必须返回结构化错误：{code}")


def run_kernel_boundaries(root):
    contract = json.loads((Path(__file__).parents[1] / "contracts/kernel_boundaries.json").read_text(encoding="utf-8"))
    for dtype in contract["dtypes"]:
        file = str(Path(root) / f"kernel-{dtype}.tdb")
        db = triviumdb.TriviumDB(file, dim=2, dtype=dtype, auto_build_quiver=False)
        try:
            for node in contract["nodes"]:
                db.insert_with_id(node["id"], node["vector"], node["payload"])
            before = Path(file + ".wal").read_bytes()
            for query in contract["invalid_mutations"]:
                expect_error(lambda: db.tql_mut(query), "TDB_QUERY_PARSE")
                assert Path(file + ".wal").read_bytes() == before
                for node in contract["nodes"]:
                    assert db.get(node["id"]).payload == node["payload"]
            expect_error(lambda: db.tql(contract["invalid_read"]), "TDB_QUERY_PARSE")
            expect_error(lambda: db.tql("MATCH (n) WHERE " + "NOT " * 16384 + "n.x == 1 RETURN n"), "TDB_QUERY_PARSE")
        finally:
            db.close()
        for requested in contract["dtypes"]:
            if requested == dtype:
                continue
            error = expect_error(lambda: triviumdb.TriviumDB(file, dim=2, dtype=requested), "TDB_DTYPE_MISMATCH")
            assert dict(error.details) == {"stored": dtype, "requested": requested}
        reopened = triviumdb.TriviumDB(file, dim=2, dtype=dtype)
        try:
            for node in contract["nodes"]:
                actual = reopened.get(node["id"])
                assert actual.vector == node["vector"]
                assert actual.payload == node["payload"]
        finally:
            reopened.close()

    file = str(Path(root) / "kernel-load-budget.tdb")
    db = triviumdb.TriviumDB(file, dim=2, auto_build_quiver=False)
    db.insert_with_id(1, [1, 0], {"text": "x" * (2 * 1024 * 1024)})
    db.close()
    before = {p.name: p.read_bytes() for p in Path(root).glob("kernel-load-budget.tdb*")}
    error = expect_error(lambda: triviumdb.TriviumDB(file, dim=2, memory_limit_mb=1), "TDB_CAPACITY_RESERVATION_REJECTED")
    assert error.details["memory_limit"] == 1024 * 1024
    assert error.details["current_bytes"] + error.details["estimated_bytes"] > error.details["memory_limit"]
    assert {p.name: p.read_bytes() for p in Path(root).glob("kernel-load-budget.tdb*")} == before

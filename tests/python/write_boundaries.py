"""Python 精确整数、容器转换与无效输入的原子拒绝契约。"""
import os

import triviumdb


def run_write_boundaries(root: str) -> None:
    file = os.path.join(root, "u64-boundaries.tdb")
    db = triviumdb.TriviumDB(file, dim=1, dtype="u64", auto_build_quiver=False)
    values = [0, 1, 2**53 + 1, 2**63 + 1, 2**64 - 1]
    try:
        for i, value in enumerate(values, 1):
            db.insert_with_id(i, [value], {"integer": value})
            tx = db.transaction()
            tx.insert_with_id(i * 100, [value], {"integer": value})
            tx.commit()
            assert db.get(i).vector == [value]
            assert db.get(i * 100).vector == [value]
            tx = db.transaction()
            tx.update_vector(i, [value])
            tx.commit()
            tx = db.transaction()
            tx.insert([value], {"integer": value})
            [generated] = tx.commit()
            assert db.get(generated).vector == [value]
            assert db.get_payload(i) == {"integer": value}
        original = db.get(1).vector
        for invalid in [-1, 0.5, float("nan"), float("inf"), 2**64]:
            with open(file + ".wal", "rb") as source:
                before = source.read()
            for operation in [
                lambda: db.insert([invalid], None),
                lambda: db.update_vector([invalid], 1),
                lambda: db.transaction().insert([invalid], None),
                lambda: db.transaction().insert_with_id(99, [invalid], None),
                lambda: db.transaction().update_vector(1, [invalid]),
                lambda: db.batch_insert([[1], [invalid]], [None, None]),
            ]:
                try:
                    operation()
                except (ValueError, TypeError, OverflowError):
                    pass
                else:
                    raise AssertionError(f"非法 u64 分量应拒绝: {invalid}")
                assert db.get(1).vector == original
                with open(file + ".wal", "rb") as source:
                    assert source.read() == before
        db.close()
        db = triviumdb.TriviumDB(file, dim=1, dtype="u64", auto_build_quiver=False)
        for i, value in enumerate(values, 1):
            assert db.get(i).vector == [value]
            assert db.get_payload(i) == {"integer": value}
            assert db.get(i * 100).vector == [value]
    finally:
        db.close()

    for dtype in ["f32", "f16", "u64"]:
        file = os.path.join(root, f"payload-conversion-{dtype}.tdb")
        db = triviumdb.TriviumDB(file, dim=1, dtype=dtype, auto_build_quiver=False)
        try:
            payload = {"signed": -(2**63), "unsigned": 2**64 - 1, "large": 2**63 + 1,
                       "nested": (True, None, ["中文", 1.5])}
            expected = {**payload, "nested": [True, None, ["中文", 1.5]]}
            db.insert_with_id(1, [1], payload)
            assert db.get_payload(1) == expected
            cycle: list = []
            cycle.append(cycle)
            for invalid in [2**64, -(2**63) - 1, float("nan"), float("inf"),
                            {1: "lost-key"}, {"nested": {1: "lost-key"}}, object(), cycle]:
                with open(file + ".wal", "rb") as source:
                    before = source.read()
                for operation in [
                    lambda: db.insert([1], invalid),
                    lambda: db.update_payload(1, invalid),
                    lambda: db.patch_payload(1, {"$set": {"nested": invalid}}),
                    lambda: db.transaction().insert([1], invalid),
                    lambda: db.transaction().update_payload(1, invalid),
                    lambda: db.batch_insert([[1], [1]], [None, invalid]),
                    lambda: db.upsert_edge(1, 1, "edge", 1, invalid),
                ]:
                    try:
                        operation()
                    except (ValueError, TypeError, OverflowError):
                        pass
                    else:
                        raise AssertionError("非法 Payload 应在写入前拒绝")
                    assert db.get_payload(1) == expected
                    with open(file + ".wal", "rb") as source:
                        assert source.read() == before
            db.close()
            db = triviumdb.TriviumDB(file, dim=1, dtype=dtype, auto_build_quiver=False)
            assert db.get(1).payload == expected
        finally:
            db.close()

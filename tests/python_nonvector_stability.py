# Python 绑定层非向量（文档过滤 / 图遍历 / 事务 / TQL DML）稳定性测试
#
# 与 python_context_manager.py 的分工：
#   python_context_manager.py        —— 上下文关闭、文件锁、异常路径下的生命周期
#   python_nonvector_stability.py    —— 非向量查询路径：FIND / MATCH / transaction / tql_mut
#
# 运行（需先安装 PyO3 扩展）：python tests/python_nonvector_stability.py

import os
import shutil
import sys
import tempfile

import triviumdb

DIM = 8
NODES = 1000


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="triviumdb-py-nonvector-")
    db_path = os.path.join(tmpdir, "nonvector.tdb")
    db = triviumdb.TriviumDB(db_path, dim=DIM)
    try:
        # 1. 写入文档型数据
        ids = []
        for i in range(NODES):
            v = [(i % 100) / 50.0 - 1.0] * DIM
            pid = db.insert(v, {
                "type": "person" if i % 3 == 0 else "event",
                "age": (i % 80) + 1,
                "region": ["cn", "us", "jp", "eu"][i % 4],
                "idx": i,
            })
            ids.append(pid)

        # 2. 建立图关系
        for i in range(1, 100):
            db.link(ids[0], ids[i], "NEXT", 1.0)
        for i in range(100, NODES):
            db.link(ids[i % 100], ids[i], "NEXT", 1.0)

        db.flush()

        # 3. 文档过滤：等值
        persons = db.tql('FIND {type: "person"} RETURN *')
        assert len(persons) == 334, f"expected 334 persons, got {len(persons)}"

        # 4. 文档过滤：组合条件（等值 + 范围）
        filtered = db.tql('FIND {region: "cn", age: {$gte: 30}} RETURN *')
        assert len(filtered) > 0, "组合条件应能命中记录"
        for row in filtered:
            # QueryRow 需通过 .row 属性取结果字典，不支持下标访问
            payload = row.row["_"]["payload"]
            assert payload["region"] == "cn"
            assert payload["age"] >= 30

        # 5. 图遍历：固定两跳
        two_hops = db.tql("MATCH (a)-[:NEXT]->(b)-[:NEXT]->(c) RETURN c")
        assert len(two_hops) > 0, "两跳遍历应有结果"

        # 6. 事务：提交后可见
        with db.transaction() as tx:
            tx.insert([0.1] * DIM, {"name": "tx_node"})
        found = db.tql('FIND {name: "tx_node"} RETURN *')
        assert len(found) == 1, "事务提交后应能查到节点"

        # 7. TQL DML：CREATE -> SET -> 校验 -> DETACH DELETE
        created = db.tql_mut('CREATE (n {name: "temp", age: 1})')
        assert created["affected"] == 1

        db.tql_mut('MATCH (n {name: "temp"}) SET n.age == 2')
        updated = db.tql('FIND {name: "temp"} RETURN *')
        assert updated[0].row["_"]["payload"]["age"] == 2

        db.tql_mut('MATCH (n {name: "temp"}) DETACH DELETE n')
        deleted = db.tql('FIND {name: "temp"} RETURN *')
        assert len(deleted) == 0, "DETACH DELETE 后应查不到"

        print("PYTHON_NONVECTOR_STABILITY_OK")
        return 0
    finally:
        db.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

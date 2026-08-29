'use strict'

// Node.js 绑定层非向量（文档过滤 / 图遍历 / TQL DML）稳定性测试
//
// 与 node_lifecycle.js 的分工：
//   node_lifecycle.js          —— 连接生命周期、dispose、跨进程文件锁、searchAdvanced 图控制参数
//   node_nonvector_stability.js —— 非向量查询路径：FIND / MATCH / tqlMut 的功能正确性
//
// 运行：npm run test:nonvector

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { TriviumDB } = require('../index.js')

const DIM = 8
const NODES = 1000

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'triviumdb-node-nonvector-'))
const dbPath = name => path.join(root, `${name}.tdb`)

try {
  const db = new TriviumDB(dbPath('nonvector'), DIM)

  // 1. 写入文档型数据
  const ids = []
  for (let i = 0; i < NODES; i++) {
    const v = []
    for (let d = 0; d < DIM; d++) v.push((i % 100) / 50 - 1)
    const id = db.insert(v, {
      type: i % 3 === 0 ? 'person' : 'event',
      age: (i % 80) + 1,
      region: ['cn', 'us', 'jp', 'eu'][i % 4],
      idx: i,
    })
    ids.push(id)
  }

  // 2. 建立图关系：root -> 99 个 mid，每个 mid 挂若干 leaf
  for (let i = 1; i < 100; i++) {
    db.link(ids[0], ids[i], 'NEXT', 1.0)
  }
  for (let i = 100; i < NODES; i++) {
    db.link(ids[i % 100], ids[i], 'NEXT', 1.0)
  }

  db.flush()

  // 3. 文档过滤：等值
  const persons = db.tql('FIND {type: "person"} RETURN *')
  assert.equal(persons.length, 334, `expected 334 persons, got ${persons.length}`)

  // 4. 文档过滤：组合条件（等值 + 范围）
  const filtered = db.tql('FIND {region: "cn", age: {$gte: 30}} RETURN *')
  assert.ok(filtered.length > 0, '组合条件应能命中记录')
  for (const row of filtered) {
    assert.equal(row._.payload.region, 'cn')
    assert.ok(row._.payload.age >= 30)
  }

  // 5. 文档过滤：逻辑组合
  const orRows = db.tql('FIND {$or: [{type: "event"}, {age: {$lt: 10}}]} RETURN *')
  assert.ok(orRows.length > 0, '$or 组合应能命中记录')

  // 6. 文档过滤：排序与分页
  const paged = db.tql('FIND {type: "person"} RETURN * ORDER BY _.idx DESC LIMIT 5')
  assert.equal(paged.length, 5)

  // 7. 图遍历：可变长路径
  const varlen = db.tql('MATCH (a)-[:NEXT*1..2]->(b) RETURN b')
  assert.ok(Array.isArray(varlen), '可变长路径应返回数组')

  // 8. 图遍历：固定两跳
  const twoHops = db.tql('MATCH (a)-[:NEXT]->(b)-[:NEXT]->(c) RETURN c')
  assert.ok(twoHops.length > 0, '两跳遍历应有结果')

  // 9. TQL DML：CREATE -> SET -> 校验 -> DETACH DELETE
  const create = db.tqlMut('CREATE (n {name: "temp", age: 1})')
  assert.equal(create.affected, 1)
  assert.equal(create.createdIds.length, 1)

  db.tqlMut('MATCH (n {name: "temp"}) SET n.age == 2')
  const updated = db.tql('FIND {name: "temp"} RETURN *')
  assert.equal(updated[0]._.payload.age, 2)

  db.tqlMut('MATCH (n {name: "temp"}) DETACH DELETE n')
  const deleted = db.tql('FIND {name: "temp"} RETURN *')
  assert.equal(deleted.length, 0, 'DETACH DELETE 后应查不到')

  db.close()

  console.log('NODE_NONVECTOR_STABILITY_OK')
} finally {
  // Windows 上 .vec 的 mmap 释放可能滞后于 close()，直接 rmSync 会抛 EPERM。
  // 临时目录清不掉不影响测试结论，因此吞掉清理异常，避免把环境问题误报成测试失败。
  try {
    fs.rmSync(root, { recursive: true, force: true })
  } catch {
    /* 忽略临时目录清理失败 */
  }
}

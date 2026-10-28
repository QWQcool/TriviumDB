// Node 数值输入契约：所有入口在转换失败时保留完整节点、边和 WAL。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

module.exports = async function runWriteBoundaries(root, TriviumDB) {
  for (const dtype of ['f32', 'f16', 'u64']) {
    const file = path.join(root, `numeric-ids-${dtype}.tdb`)
    const db = new TriviumDB(file, { dim: 1, dtype, autoBuildQuiver: false })
    try {
      db.insertWithId(1, [1], { keep: 1 })
      db.insertWithId(2, [0], { keep: 2 })
      db.upsertEdge(1, 2, 'edge', 1, { keep: true })
      for (const id of [1.9, -1, NaN, Infinity, -Infinity, 2 ** 53]) {
        const operations = [
          () => db.get(id), () => db.getPayload(id), () => db.getEdges(id),
          () => db.getIncomingEdges(id), () => db.contains(id),
          () => db.insertWithId(id, [1], null), () => db.upsertWithId(id, [1], null),
          () => db.updatePayload(id, { changed: true }),
          () => db.patchPayload(id, { $set: { keep: 3 } }),
          () => db.updateVector(id, [0]), () => db.delete(id),
          () => db.deleteManyAtomic([2, id]),
          () => db.compareAndSetPayloadField(id, 'keep', 1, 3),
          () => db.link(id, 2, 'other', 1), () => db.link(1, id, 'other', 1),
          () => db.upsertEdge(id, 2, 'edge', 2), () => db.upsertEdge(1, id, 'edge', 2),
          () => db.getEdge(id, 2, 'edge'), () => db.getEdge(1, id, 'edge'),
          () => db.updateEdge(id, 2, 'edge', 2), () => db.updateEdge(1, id, 'edge', 2),
          () => db.unlink(id, 2), () => db.unlink(1, id),
          () => db.neighbors(id, 1), () => db.reachable(id),
          () => db.reachableDetailed(id), () => db.querySubgraph(id),
          () => db.indexText(id, 'text'), () => db.indexKeyword(id, 'keyword'),
          () => db.batchInsertWithIds([3, id], [[1], [0]], [null, null]),
          () => db.commitTransaction([{ type: 'delete', id: 2 }, { type: 'updatePayload', id, payload: null }]),
        ]
        const before = fs.readFileSync(file + '.wal')
        for (const operation of operations) {
          assert.throws(operation, Error, `dtype=${dtype}, id=${id}`)
          assert.deepEqual(fs.readFileSync(file + '.wal'), before)
          assert.deepEqual(db.get(1).vector, [1])
          assert.deepEqual(db.getPayload(1), { keep: 1 })
          assert.deepEqual(db.getPayload(2), { keep: 2 })
          assert.deepEqual(db.allNodeIds().sort(), [1, 2])
          assert.equal(db.getEdge(1, 2, 'edge').weight, 1)
        }
      }
      db.insertWithId(Number.MAX_SAFE_INTEGER, [1], { boundary: 'safe-id' })
      assert.deepEqual(db.getPayload(Number.MAX_SAFE_INTEGER), { boundary: 'safe-id' })
    } finally { db.close() }
  }

  const file = path.join(root, 'u64-vector-boundaries.tdb')
  const db = new TriviumDB(file, { dim: 1, dtype: 'u64', autoBuildQuiver: false })
  try {
    db.insertWithId(1, [1], { keep: true })
    for (const value of [-1, 0.5, NaN, Infinity, -Infinity, 2 ** 64]) {
      const before = fs.readFileSync(file + '.wal')
      for (const operation of [
        () => db.insert([value], null), () => db.insertWithId(2, [value], null),
        () => db.upsertWithId(1, [value], null), () => db.updateVector(1, [value]),
        () => db.batchInsert([[1], [value]], [null, null]),
        () => db.batchInsertWithIds([2, 3], [[1], [value]], [null, null]),
        ...['insert', 'insertWithId', 'updateVector'].map(type => () => db.commitTransaction([
          { type: 'updatePayload', id: 1, payload: { changed: true } },
          { type, id: 1, vector: [value], payload: null },
        ])),
        () => db.search([value], 1, 0, 0),
        () => db.searchAdvanced([value], { topK: 1, minScore: 0 }),
        () => db.searchWithContext([value], { topK: 1, minScore: 0 }),
        () => db.searchGrouped([value], 1, 0, 0),
        () => db.searchHybrid([value], 'query', 1, 0, 0),
      ]) {
        assert.throws(operation, Error, `value=${value}`)
        assert.deepEqual(fs.readFileSync(file + '.wal'), before)
        assert.deepEqual(db.get(1).vector, [1])
        assert.deepEqual(db.getPayload(1), { keep: true })
        assert.deepEqual(db.allNodeIds(), [1])
      }
      await assert.rejects(async () => db.searchBatch([[1], [value]], 1), Error)
    }
    // JavaScript Number 在这个边界以内仍能精确表示这些整数分量。
    for (const value of [0, 1, 2 ** 32, 2 ** 53, 2 ** 63, 2 ** 64 - 2048]) {
      db.updateVector(1, [value])
      assert.deepEqual(db.get(1).vector, [value])
    }
    db.close()
    const reopened = new TriviumDB(file, { dim: 1, dtype: 'u64', autoBuildQuiver: false })
    try { assert.deepEqual(reopened.get(1).vector, [2 ** 64 - 2048]) } finally { reopened.close() }
  } finally { db.close() }
}

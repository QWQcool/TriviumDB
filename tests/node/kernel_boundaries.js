'use strict'
// 原生 SDK 验证持久化类型、完整语句与打开预算的共享契约。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { TriviumDB } = require('../../index.js')
const contract = require('../contracts/kernel_boundaries.json')

function runKernelBoundaries(root) {
  for (const dtype of contract.dtypes) {
    for (const storageMode of ['rom', 'mmap']) {
      const file = path.join(root, `kernel-${dtype}-${storageMode}.tdb`)
      const options = { dim: 2, dtype, storageMode, autoBuildQuiver: false }
      const db = new TriviumDB(file, options)
      try {
        for (const node of contract.nodes) db.insertWithId(node.id, node.vector, node.payload)
        const before = fs.readFileSync(file + '.wal')
        for (const query of contract.invalid_mutations) {
          assert.throws(() => db.tqlMut(query), error => error.code === 'TDB_QUERY_PARSE')
          assert.deepEqual(fs.readFileSync(file + '.wal'), before)
          for (const node of contract.nodes) assert.deepEqual(db.get(node.id).payload, node.payload)
        }
        assert.throws(() => db.tql(contract.invalid_read), error => error.code === 'TDB_QUERY_PARSE')
        assert.throws(() => db.tql('MATCH (n) WHERE ' + 'NOT '.repeat(16384) + 'n.x == 1 RETURN n'), error => error.code === 'TDB_QUERY_PARSE')
      } finally { db.close() }
      for (const requested of contract.dtypes.filter(value => value !== dtype)) {
        assert.throws(() => new TriviumDB(file, { ...options, dtype: requested }), error => {
          assert.equal(error.code, 'TDB_DTYPE_MISMATCH')
          assert.deepEqual(error.details, { stored: dtype, requested })
          return true
        })
      }
      const reopened = new TriviumDB(file, options)
      try {
        for (const node of contract.nodes) {
          assert.deepEqual(reopened.get(node.id).vector, node.vector)
          assert.deepEqual(reopened.get(node.id).payload, node.payload)
        }
      } finally { reopened.close() }
    }
  }
  const file = path.join(root, 'kernel-load-budget.tdb')
  const db = new TriviumDB(file, { dim: 2, autoBuildQuiver: false })
  db.insertWithId(1, [1, 0], { text: 'x'.repeat(2 * 1024 * 1024) })
  db.close()
  const snapshot = () => fs.readdirSync(root).filter(name => name.startsWith('kernel-load-budget.tdb')).sort().map(name => [name, fs.readFileSync(path.join(root, name))])
  const before = snapshot()
  assert.throws(() => new TriviumDB(file, { dim: 2, memoryLimitMb: 1 }), error => {
    assert.equal(error.code, 'TDB_CAPACITY_RESERVATION_REJECTED')
    assert.equal(error.details.memory_limit, 1024 * 1024)
    assert.ok(error.details.current_bytes + error.details.estimated_bytes > error.details.memory_limit)
    return true
  })
  assert.deepEqual(snapshot(), before)
}

module.exports = { runKernelBoundaries }

// 验证 B1/B3/B4 修复效果 —— 用法: node verify-fixes.js <path/to/triviumdb.node>
const path = require("path");
const fs = require("fs");

const nativePath = process.argv[2];
if (!nativePath) { console.error("用法: node verify-fixes.js <xxx.node>"); process.exit(2); }
const binding = require(nativePath);
const { TriviumDB } = binding;

const os = require("os");
const DATA_DIR = path.join(os.tmpdir(), "triviumdb-probe", "verify");
fs.mkdirSync(DATA_DIR, { recursive: true });
const DIM = 4;
function vec(seed) { const v = []; for (let i = 0; i < DIM; i++) v.push(Math.sin(seed * (i + 1)) * 0.5 + 0.5); return v; }
function fresh(name) {
  const p = path.join(DATA_DIR, name);
  for (const suffix of ["", ".lock", ".wal"]) { try { fs.unlinkSync(p + suffix); } catch {} }
  return p;
}

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log(`[PASS] ${name}`); pass++; }
  catch (e) { console.log(`[FAIL] ${name} -> ${e.message.slice(0, 200)}`); fail++; }
}
function expectError(name, fn, keyword) {
  try { fn(); console.log(`[FAIL] ${name} (期待报错，实际无异常)`); fail++; }
  catch (e) { const ok = !keyword || e.message.includes(keyword); console.log(`[${ok ? "PASS" : "FAIL"}] ${name} -> ${e.message.slice(0, 120)}`); ok ? pass++ : fail++; }
}

console.log("=== B1: close 后锁释放 ===");
{
  const p = fresh("b1.tdb");
  let db = new TriviumDB(p, DIM, "f32", "normal");
  db.insert(vec(1), { chunkId: "a" });
  db.close();
  db = null;
  const db2 = new TriviumDB(p, DIM, "f32", "normal");   // 旧版本在这里抛 Database locked
  t("close 后同进程立即重开成功", () => { if (db2.nodeCount() !== 1) throw new Error("nodes!=1"); });
  t(".lock 文件已清理", () => { if (fs.existsSync(p + ".lock")) throw new Error("lock 残留"); });
  db2.close();
}

console.log("=== B3: top_k 边界校验 ===");
{
  const db = new TriviumDB(fresh("b3.tdb"), DIM, "f32", "normal");
  for (let i = 1; i <= 5; i++) db.insert(vec(i), { chunkId: "c" + i });
  expectError("search topK=0 报错", () => db.search(vec(1), 0, 0, -1), "top_k");
  expectError("search topK=-3 报错", () => db.search(vec(1), -3, 0, -1), "top_k");
  t("search topK=2 正常返回 2 条", () => { const h = db.search(vec(1), 2, 0, -1); if (h.length !== 2) throw new Error(`len=${h.length}`); });
  db.close();
}

console.log("=== B4: unlink 幂等语义 ===");
{
  const db = new TriviumDB(fresh("b4.tdb"), DIM, "f32", "normal");
  const a = db.insert(vec(1), { chunkId: "a" });
  const b = db.insert(vec(2), { chunkId: "b" });
  db.link(a, b, "rel", 1);
  t("unlink(a,b) 成功", () => db.unlink(a, b));
  t("unlink(b,a) 无出边 → 无操作不报错", () => db.unlink(b, a));  // 旧版本报 NodeNotFound
  t("link 后 neighbors 正确", () => {
    db.link(a, b, "rel", 1);
    if (db.neighbors(a, 1).length !== 1) throw new Error("neighbors!=1");
    if (!db.neighbors(b, 1) || db.neighbors(b, 1).length !== 0) throw new Error("b neighbors 应为 0");
  });
  expectError("unlink 不存在的节点仍报 NodeNotFound", () => db.unlink(9999, a), "节点不存在");
  db.close();
}

console.log(`\n结果: PASS=${pass} FAIL=${fail}`);
process.exit(fail ? 1 : 0);

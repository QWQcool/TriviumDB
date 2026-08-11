# TriviumDB 审计与修复笔记（远程同步版）

> 本文件为**脱敏版**（供从 GitHub 拉取到其他电脑继续工作）；完整版（含本机细节）保留在原作者工作区，不在此仓库公开分支。
> 用途：**回家后在新电脑继续 TriviumDB 修复收尾的接续入口**。

- 审计日期：2026-08-11
- 测试对象：`triviumdb@0.7.2` 预编译二进制（napi .node）
- 源码基线：fork `QWQcool/TriviumDB`（v0.7.2）对比上游 `YoKONCy/TriviumDB`（master @ 25550a5, v0.7.3）

---

## 一、确认的业务逻辑 bug（黑盒实测）

| # | 严重度 | 描述 | 0.7.3 状态 |
|---|--------|------|-----------|
| B1 | 中 | `close()` 不同步释放锁：同进程 close 后立即重开报 Database locked；`.lock`/`.wal` 残留。根因：`database/mod.rs` 用 `try_lock_exclusive()` 持锁，锁释放依赖 Rust Drop（JS GC 时机），close 只 flush 不释放锁不删文件。跨进程/崩溃后可正常重开（OS 释放） | **未修复** |
| B2 | 中 | d.ts 声明 `filterWhere`/`query` 但运行时 undefined（43 个运行时方法中不存在） | ✅ 已修复（PR #9 `84cc7f1`，d.ts 与运行时同步） |
| B3 | 中 | `search` topK 边界：`topK=0` 返回 1 条（`pipeline.rs:67` max(1)）；**负数被 `Option<u32>` 无符号化成超大值 → 静默返回全库** | **未修复** |
| B4 | 低 | `unlink(src,dst)` 在 src 无出边时误报 `NodeNotFound(src)`（`memtable.rs`：edges 表只登记有出边的节点） | **未修复** |

信息级：B5 `insertWithId` 同 id 抛 `Node already exists`（严格语义，非 upsert）；B6 `payload=null` 可插入。

## 二、安全审计结论

- ✅ **损坏文件攻击面安全**：截断/翻转/magic 清零/字段篡改/空文件 5 场景全部优雅报错、零崩溃（0.7.2 已有 magic/header/BQ 块/溢出边界检查）。
- ✅ **跨进程锁与崩溃恢复**正确。
- ✅ unsafe 64 处集中在 mmap/量化/FFI（8 文件），关键路径有长度/对齐检查，未见可利用越界。
- ⚠️ `loadFfiHook(lib_path)` 可加载任意 DLL（调用方信任模型，无路径/签名校验）；`migrate(new_path)` 任意路径写入面；`vec_pool.rs` mmap 对齐异常会 panic（理论 DoS，难触发）。
- **0.7.3 上游自证修复**（commit 26daf1e）：FlushMarker 加 generation（断电撕裂恢复）、TQL 执行顺序 + OPTIONAL MATCH 语义、Windows 原子替换加杀软瞬态锁重试。

## 三、修复进展（B1/B3/B4 已改完，待收尾）

分支 `fix/audit-bugs`，提交 `3cc76bc`（4 文件 66+/15-）：
- B1：`database/mod.rs` `_lock_file` Option 化 + 新增 `release_lock()`（take 句柄 + 删 .lock），nodejs/python `close()` 同步调用
- B3：`nodejs.rs` 4 处 `top_k: Option<u32>` → `Option<i64>`，`<=0` 返回错误（search / search_hybrid / searchAdvanced / searchWithContext）
- B4：`memtable.rs` `unlink` let-else 重构，src 无出边且节点存在时幂等返回 `Ok(())`

验证状态：`cargo test --features nodejs` **全绿**（282 单元 + 集成 + doc-tests，0 failed）；JS 层黑盒验证待新电脑执行（见下）。

## 四、新电脑收尾步骤（回家流程）

前置：新电脑需安装 **Node.js 22+** 与 **Rust 工具链**（rustup + stable；Windows 需 MSVC Build Tools 或已有 Visual Studio C++ 组件）。

```bash
# 1. 拉取仓库（含全部历史与分支）
git clone https://github.com/QWQcool/TriviumDB.git
cd TriviumDB
# 2. 本笔记所在分支（如未自动检出）：
git checkout home/audit-notes
# 3. 切到修复分支：
git checkout fix/audit-bugs
# 4. 确认远程修复分支只含源码提交（应无 docs 提交 e921fee）：
git log --oneline -3
#    如果仍看到 e921fee（说明 force push 未生效），执行：
#    git fetch origin && git reset --hard origin/fix/audit-bugs
# 5. 重新编译绑定（首次需拉取依赖，耗时几分钟）：
cargo build --features nodejs
# 6. 黑盒验证 3 个修复（期待 PASS=7）：
cp target/release/triviumdb.dll /tmp/triviumdb.win32-x64-msvc.node
node audit-report/verify-fixes.js /tmp/triviumdb.win32-x64-msvc.node
# 7. 全部 PASS 后提 PR：
#    GitHub → QWQcool/TriviumDB → Compare & pull request
#    base: YoKONCy/TriviumDB master ← compare: QWQcool/TriviumDB fix/audit-bugs
#    PR 描述附上：本笔记 bug 清单 + verify-fixes.js 输出
```

> 说明：`audit-report/` 在本仓库为未跟踪文件（不进任何提交/PR）；`home/audit-notes` 分支仅用于把本笔记同步到其他电脑。

## 五、远程 fork 同步参考

- 远程 fork master 同步上游最新：GitHub 网页 fork 页面 → **Sync fork** → Update branch（或 `git merge --ff-only upstream/master`）。
- 仓库结构：`origin` = fork（可 push），`upstream` = 官方（只读）。

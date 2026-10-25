# 实例关闭、快照与恢复

> 适用范围：0.9.0-beta.1。单机和容器使用同一套嵌入式接口。

## 维护额度

`ResourceLimits.maintenance_memory_limit` 在总预算内保护维护工作区，零值在有限总预算下自动保护八分之一。Python 参数为 `maintenance_memory_limit_mb`，Node 参数为 `maintenanceMemoryLimitMb`，两端单位均为 MiB。

刷盘、压实、关闭、快照使用维护保护额度，并可借用闲置的前台额度；总账受 `memory_limit` 约束。维护任务使用独立名额，最多同时准入 `max_threads` 个根任务，前台任务按 `max_active_tasks` 单独计数。

保存按估算堆内存的两倍加 1 MiB 检查工作区，快照复制/校验另需 2 MiB 工作区。宿主按实例规模和并行维护量配置总额与保护额度。维护可用额度不足时，操作返回预算错误并保留重试条件。运行时预算用于资源准入，进程内存和 CPU 限额由操作系统或容器配置。

## 关闭协议

| Rust | Python | Node.js | 行为 |
| --- | --- | --- | --- |
| `request_shutdown()` | `request_shutdown()` | `requestShutdown()` | 拒绝新操作、停止后续周期维护，并登记自动关闭任务 |
| `shutdown_status()` | `shutdown_status()` | `shutdownStatus()` | 读取阶段、已有操作数与最近失败诊断，不触发准入 |
| `close_timeout(Duration)` | `close_timeout(timeout_ms)` | `closeTimeout(timeoutMs)` | 在给定期限内等待完成；成功返回 `true`，等待超时返回 `false`，操作失败返回错误 |
| `close()` | `close()` | `close()` | 保留同步关闭入口，等待持久化和资源释放 |

异步关闭阶段依次为 `open → draining → flushing → closed`。失败时为 `failed`，下一次等待返回保存的原始错误；消费错误后，可再次调用 `close_timeout` 重试。`last_error` 提供诊断文本，宿主通过结构化 `last_failure` 和调用返回的错误分类处理故障。

`shutdown_status()` 还返回结构化 `last_failure`（分类、消息及可选预算字段），以及当前关闭登记的 `maintenance` 状态。宿主可以区分排空等待、维护准入延期与已执行失败，详见[后台维护诊断](resource-runtime.md#后台维护诊断)。`active_operations` 统计本实例已进入的操作调用，内部嵌套调用可能计入多次，并非共享运行时的根任务数。一次新的关闭尝试清除上次故障诊断。

等待超时返回 `false`，关闭任务继续持有内存、配额和文件锁。已有操作与 Hook 完成后，共享调度器继续执行关闭；已排空的关闭任务优先于周期压实。后续调用可继续等待或读取状态。返回 `true` 时，可写实例已完成持久化，数据库配额已归还、文件锁已释放；Reader 完成自身资源释放，并保持数据库制品原样。

`request_shutdown()` 自动推进关闭，关闭任务在语言包装对象回收后继续持有所需的数据和文件锁。排空阶段等待已有操作完成，宿主通过任务管理与协作取消控制这些操作的生命周期。需要设置退出等待期限时，使用显式关闭接口。

Rust 的同步 `close()` 保留重复关闭返回 `DatabaseClosed` 的行为；Python/Node 的同步 `close()` 保留幂等行为。三端 `close_timeout()` 在已经关闭后均返回 `true`。

同步 `close()` 失败时也保留原有重试行为：阶段恢复为 `open`，`last_failure` 记录本次失败。再次同步关闭会清除上次诊断并重试。

### Rust

```rust
use std::time::Duration;

db.request_shutdown()?;
if !db.close_timeout(Duration::from_secs(5))? {
    let status = db.shutdown_status();
    println!("关闭尚未完成：{:?}", status);
    // 宿主可继续等待，正在使用的资源仍受保护。
}
```

### Python

```python
db.request_shutdown()
if not db.close_timeout(5000):
    print("关闭尚未完成：", db.shutdown_status())
```

关闭等待和快照复制期间释放 GIL。宿主在自身的退出信号处理流程中调用关闭接口。

### Node.js

`closeTimeout` 是同步等待。事件循环需要继续工作时，可以发起关闭后轮询零等待接口：

```javascript
db.requestShutdown()
while (!db.closeTimeout(0)) {
  await new Promise(resolve => setTimeout(resolve, 10))
}
```

宿主应为轮询循环设置自身截止时间。超过截止时间后可以停止等待，数据库关闭任务仍然继续。

## 一致快照

| 能力 | Rust | Python | Node.js |
| --- | --- | --- | --- |
| 创建 | `db.create_snapshot(destination, generation_id)` | `db.create_snapshot(destination, generation_id)` | `db.createSnapshot(destination, generationId)` |
| 校验 | `storage::snapshot::verify_snapshot(directory)` | `triviumdb.verify_snapshot(directory, runtime=None)` | `verifySnapshot(directory, runtime?)` |
| 恢复 | `storage::snapshot::restore_snapshot(source, destination)` | `triviumdb.restore_snapshot(source, destination, runtime=None)` | `restoreSnapshot(source, destination, runtime?)` |

Rust 校验和恢复还有接收 `&ResourceRuntime` 的 `_with_runtime` 入口。三端返回同一份 manifest，包含 generation ID、dtype、维度、节点数和各文件长度/CRC。

创建快照需要可写句柄。内核持有源库写锁，完成 checkpoint 和 WAL 清理，再复制该代所需的主文件、向量、冷载荷及索引制品。目标使用独立目录，内部数据库名固定为 `database.tdb`。源库在快照完成后可继续更新，快照中的事实保持在捕获时刻。

创建和恢复使用已存在的父目录及全新的目标目录，恢复目标位于源快照目录之外。已有目标返回 `SnapshotDestinationExists`。快照目录由 manifest 和其中声明的普通文件组成；校验发现符号链接、管道、WAL、临时文件、额外制品或 manifest 错配时返回错误。

复制采用有界缓冲，逐文件 fsync，在隐藏暂存目录中生成并验证 manifest，最后通过目录 rename 和父目录同步发布。目录 rename 是目标的可见发布点。发布前的普通错误清理本次暂存目录；强杀后可能留下隐藏暂存目录，正式快照由目标路径及有效 manifest 识别。目标父目录可能保留用于并发发布互斥的隐藏锁文件。

重命名完成后，若父目录同步失败，Rust 返回 `SnapshotPublicationUncertain`，Python 抛出 `SnapshotPublicationError`，Node 错误码为 `TDB_SNAPSHOT_PUBLICATION_UNCERTAIN`。此时保留已发布的完整目标，宿主通过校验目标决定后续操作。已有目标分别返回 Rust `SnapshotDestinationExists`、Python `FileExistsError`、Node `TDB_SNAPSHOT_EXISTS`。

校验检查文件集合、长度、CRC 及主文件头的维度和节点数。打开数据库时继续执行内部格式校验。发布后的快照目录按不可变制品管理；创建和校验期间，宿主保持源文件与发布目录的内容稳定。

### 创建、校验、恢复与打开

示例中的 `db` 为已打开的 Writer，`runtime` 为其共享运行时。源库与恢复后的 Reader 分别登记自身配额。

```python
import os
import triviumdb

os.makedirs("./snapshots", exist_ok=True)
os.makedirs("./restored", exist_ok=True)
db.create_snapshot("./snapshots/agent-a", "agent-a-001")
manifest = triviumdb.verify_snapshot("./snapshots/agent-a", runtime)
triviumdb.restore_snapshot("./snapshots/agent-a", "./restored/agent-a", runtime)

# 需要校验恢复目录或让多个 Reader 共享时，以 immutable 方式打开。
reader = triviumdb.TriviumDB(
    os.path.join("./restored/agent-a", "database.tdb"),
    dim=manifest["dim"], dtype=db.dtype, access_mode="immutable",
    memory_limit_mb=64, runtime=runtime,
)
reader.close()
```

恢复完成后，宿主选择以 Immutable、ReadOnly 或 ReadWrite 模式打开 `database.tdb`，并配置 dtype、维度与预算。以可写模式打开后，恢复目录作为活动数据库使用；后续状态通过再次创建快照捕获。

独立快照接口复用现有 generation manifest 格式。`GenerationStore` 的 current 发布与 Reader 租约机制继续可用，适合需要原子切换多个不可变代际的宿主；新快照接口提供从活动实例到完整目录的统一捕获与恢复步骤。

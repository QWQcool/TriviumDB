# 实例关闭、快照与恢复

> 开发中源码能力，尚未包含在已发布的 0.8.11 包中。单机和容器使用同一套嵌入式接口。

## 维护额度

`ResourceLimits.maintenance_memory_limit` 在总预算内保护维护工作区，零值在有限总预算下自动保护八分之一。Python 参数为 `maintenance_memory_limit_mb`，Node 参数为 `maintenanceMemoryLimitMb`，两端单位均为 MiB。

数据库配额与前台工作区不能占用这部分保护额度。刷盘、压实、关闭、快照可以使用它，也可以借用未使用的前台额度；总账始终受 `memory_limit` 约束。维护任务使用独立名额，最多同时准入 `max_threads` 个根任务，因此前台任务数达到上限不会直接拒绝维护任务。

预留不代表任何规模都能关闭：保存目前按估算堆内存的两倍加 1 MiB 检查工作区，快照复制/校验另需 2 MiB 工作区。若维护可用额度不足，操作明确失败并保留重试条件；应按实际实例规模配置总额与保护额度。这些仍是准入预算，不能代替容器内存硬限制。

## 关闭协议

| Rust | Python | Node.js | 行为 |
| --- | --- | --- | --- |
| `request_shutdown()` | `request_shutdown()` | `requestShutdown()` | 拒绝新操作、停止后续周期维护，并登记自动关闭任务 |
| `shutdown_status()` | `shutdown_status()` | `shutdownStatus()` | 读取阶段、已有操作数与最近失败诊断，不触发准入 |
| `close_timeout(Duration)` | `close_timeout(timeout_ms)` | `closeTimeout(timeoutMs)` | 在给定期限内等待完成；成功返回 `true`，等待超时返回 `false`，操作失败返回错误 |
| `close()` | `close()` | `close()` | 保留同步关闭入口，等待持久化和资源释放 |

关闭阶段依次为 `open → draining → flushing → closed`。失败时为 `failed`，下一次等待会返回保存的原始错误；消费错误后，可以再次调用 `close_timeout` 重试。`last_error` 是诊断文本，不能作为控制流判断依据。

超时只结束调用方等待。它不会撤销 fsync、终止正在运行的 Hook、释放仍在使用的内存或放开文件锁。已有操作排空后，共享调度器会继续执行关闭；已排空的关闭任务优先于周期压实。后续调用可继续等待或读取状态。`true` 表示数据已持久化、数据库配额已归还、文件锁已释放；Reader 关闭不写入数据库制品。

调用 `request_shutdown()` 也会自动推进关闭；即使语言包装对象在随后被回收，关闭任务仍持有所需的数据和文件锁。未结束的操作可能使关闭长期停留在排空阶段，宿主需管理这些操作的完成或协作取消。普通 Drop 仍不提供等待期限，不能代替显式关闭协议。

Rust 的同步 `close()` 保留重复关闭返回 `DatabaseClosed` 的行为；Python/Node 的同步 `close()` 保留幂等行为。三端 `close_timeout()` 在已经关闭后均返回 `true`。

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

关闭等待和快照复制期间会释放 GIL。宿主收到退出信号后自行调用接口，库不会接管宿主的信号处理。

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

目标父目录必须已经存在，目标目录必须不存在。恢复也只创建新目录，不覆盖正在使用或已存在的数据。恢复目标不能位于源快照内部。快照目录只允许声明的普通文件；符号链接、管道、WAL、临时文件、额外制品和不匹配的 manifest 都会被拒绝。

复制采用有界缓冲，逐文件 fsync，在隐藏暂存目录中生成并验证 manifest，最后通过目录 rename 和父目录同步发布。失败或进程被强杀时，目标要么尚未出现，要么已经是完整目录。发布前的普通错误会清理本次暂存目录；强杀可能留下不可见的暂存目录，后续操作不会将它当作有效快照。目标父目录可能保留用于并发发布互斥的隐藏锁文件。

重命名完成后，若父目录同步失败，Rust 返回 `SnapshotPublicationUncertain`，Python 抛出 `SnapshotPublicationError`，Node 错误码为 `TDB_SNAPSHOT_PUBLICATION_UNCERTAIN`。此时完整目标会保留，宿主应校验目标并决定后续操作，不能将错误理解为“目标一定不存在”。已有目标分别返回 Rust `SnapshotDestinationExists`、Python `FileExistsError`、Node `TDB_SNAPSHOT_EXISTS`。

校验会检查文件集合、长度、CRC 及主文件头的维度/节点数；不提供密码学认证，也不替代打开数据库时的内部格式检查。快照目录应在发布后保持不可变，外部进程不得同时修改源文件或篡改发布目录。

### 创建、校验、恢复与打开

```python
import os
import triviumdb

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

恢复完成后，宿主自行选择以 Immutable、ReadOnly 或 ReadWrite 模式打开 `database.tdb`，并明确配置 dtype、维度与预算。可写打开会使该恢复目录成为普通活动数据库；后续写入或关闭后，不再将原 manifest 当作当前状态的快照证明。

独立快照接口复用现有 generation manifest 格式。`GenerationStore` 的 current 发布与 Reader 租约机制继续可用，适合需要原子切换多个不可变代际的宿主；新快照接口提供从活动实例到完整目录的统一捕获与恢复步骤。

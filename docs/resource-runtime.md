# 多实例共享资源运行时

> 开发中源码能力，尚未包含在已发布的 0.8.11 包中。

同一进程中的多个嵌入式数据库可以共享 `ResourceRuntime`。适用于一个 Agent 平台同时打开多个租户、会话或任务数据库的场景；数据库仍由宿主应用直接调用。

## 资源准入

| 配置 | 含义 | 零值 |
| --- | --- | --- |
| `memory_limit` | 数据库声明配额与已预留临时工作区的总和上限，Rust 单位为字节 | 不限 |
| `maintenance_memory_limit` | 总预算内保护的维护工作区，Rust 单位为字节 | 有限总预算下自动保护八分之一，至少 1 字节 |
| `max_threads` | 同一运行时所有缓存计算池的工作线程总上限，最大 64 | 按可用并行度选择，最多 64 |
| `max_active_tasks` | 同时准入的根任务数；同一任务的内部嵌套调用复用名额 | 不限 |

有共享内存上限时，每个数据库必须声明非零 `Config.memory_limit`。打开数据库先登记完整配额，超额会在创建数据库制品前失败。调整配额失败保留原值；成功关闭释放实际内存和登记配额，无需等待语言包装对象被垃圾回收。打开失败也回收登记。

**维护额度属于总预算，不会自动扩大总预算。** 例如总额 256 MiB、保护 32 MiB 维护额度，数据库配额与前台工作区合计最多使用 224 MiB。维护操作可以使用保护额度，并借用当前未使用的前台额度；前台不能抢占保护额度，也不能抢占维护正在借用的额度。

刷盘、压实、关闭和快照使用独立的维护任务名额，最多同时准入 `max_threads` 个维护根任务，不占用前台 `max_active_tasks`。同一维护任务的嵌套调用复用名额。后台调度优先处理已排空的关闭任务，再处理周期压实。

维护仍须在工作前通过峰值预算检查。保护额度过小、数据库规模过大或其他维护占用额度时，保存仍可能失败；它不保证磁盘永不出错，也不会绕过内存总上限。失败会保留可重试状态。详见[关闭、快照与恢复](lifecycle-snapshots.md)。

资源不足立即返回错误，宿主可以限流、退避重试或释放闲置实例。运行时不会为了减轻负载而静默截断结果、降低召回参数或改变排序。

## Rust

```rust
use triviumdb::{Database, ResourceLimits, ResourceRuntime};
use triviumdb::database::Config;

fn main() -> triviumdb::Result<()> {
    let runtime = ResourceRuntime::new(ResourceLimits {
        memory_limit: 256 * 1024 * 1024,
        maintenance_memory_limit: 32 * 1024 * 1024,
        max_threads: 4,
        max_active_tasks: 8,
    })?;
    let config = Config {
        dim: 768,
        memory_limit: 64 * 1024 * 1024,
        ..Default::default()
    };
    let mut first = Database::<f32>::open_with_runtime("first.tdb", config, runtime.clone())?;
    let mut second = Database::<f32>::open_with_runtime("second.tdb", config, runtime.clone())?;
    println!("共享资源统计：{:?}", runtime.stats());
    first.set_memory_limit(80 * 1024 * 1024)?;
    first.close()?;
    second.close()?;
    Ok(())
}
```

`DatabaseReader`、`DatabaseWriter` 也提供 `open_with_runtime`。现有 `open` / `open_with_config` 入口复用进程默认运行时：不限制配额与任务数，但缓存工作线程总数最多 64。显式创建的运行时相互独立，其上限不会自动合并。

`set_memory_limit` 现在返回 `Result<()>`，调用方应处理扩容失败。资源拒绝是 `TriviumError::ResourceBudgetExceeded { resource, requested, used, limit }`，可直接按字段分类。

## Python

```python
from triviumdb import TriviumDB, ResourceRuntime, ResourceBudgetError

runtime = ResourceRuntime(memory_limit_mb=256, maintenance_memory_limit_mb=32, max_threads=4, max_active_tasks=8)
first = TriviumDB("first.tdb", dim=768, memory_limit_mb=64, runtime=runtime)
second = TriviumDB("second.tdb", dim=768, memory_limit_mb=64, runtime=runtime)
try:
    first.set_memory_limit(80)
except ResourceBudgetError:
    print("额度不足，稍后重试")
print(runtime.stats())
first.close()
second.close()
```

Python 配额参数单位为 MiB，资源拒绝抛出 `ResourceBudgetError`，它继承 `RuntimeError`。数据库的 `resource_stats()` 和运行时的 `stats()` 返回同一运行时的共享统计。

## Node.js

```javascript
const { TriviumDB, ResourceRuntime } = require('triviumdb')
const runtime = new ResourceRuntime({ memoryLimitMb: 256, maintenanceMemoryLimitMb: 32, maxThreads: 4, maxActiveTasks: 8 })
const first = new TriviumDB('first.tdb', { dim: 768, memoryLimitMb: 64, runtime })
const second = new TriviumDB('second.tdb', { dim: 768, memoryLimitMb: 64, runtime })
console.log(runtime.stats())
first.close()
second.close()
```

Node.js 配额参数单位为 MiB，资源拒绝的 `error.code` 为 `QueueFull`；不要解析错误消息判断是否可重试。`resourceStats()` / `stats()` 的 JSON 字段与 Rust 统计保持一致，使用下划线命名。

## 调度与观测边界

运行时统一管理数据库入口使用的扫描、构图、TQL 计算及后台压实工作池。闲置池的线程退出后才建立替代池，避免缓存多个并行度时累计超额。后台压实共用一个进程计时线程，实际维护进入所属运行时；资源不足或数据库正忙时延期。

`max_threads` 统计计算池工作线程，不包含宿主调用线程、进程共享的计时线程和宿主自行创建的线程。直接调用底层算法模块、外部 Hook 自行分配的资源不纳入该约束。运行时不自动读取 cgroup，也不承诺跨进程总额控制；容器仍应配置自身内存和 CPU 限额。

`stats()` 包含数据库与工作区预留、峰值预留、登记实例数、分配/实际存活/峰值工作线程、前台/维护活动任务、维护工作区预留、拒绝计数和维护任务计数。统计不触发资源准入，可在过载时读取。

内存额度是**显式配额和已接入工作区的准入账本**，不是分配器级硬限制。它不能覆盖所有分配，也不能等同于进程 RSS：mmap 驻留、操作系统页缓存、线程栈、语言运行时及 Hook 内存均存在额外开销。数据库已有的 `estimated_memory`、索引/载荷统计及进程内存诊断仍用于观测，不以瞬时 RSS 决定查询结果。

根任务准入覆盖返回 `Result` 的数据库工作入口；统计和历史不返回错误的读取辅助接口不获取任务名额。Prepared 构图任务从准备成功起占用任务与工作区，直到执行或丢弃，宿主应及时处理它们。同步 `close()` 继续等待本库操作完成；`request_shutdown()` 与 `close_timeout()` 提供可观测关闭和有界等待，超时后保持关闭中状态并继续保护正在使用的资源。

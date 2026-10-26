# 未发布变更

当前开发分支基于 `0.9.0-beta.1`，版本元数据保持原值。

## 关闭与资源所有权

- 同步关闭、限时关闭和后台关闭在成功完成时释放最终 WAL writer、向量与 Payload 映射、索引存储、数据库持有的 Hook 和文件锁。调用方可继续持有关闭对象；没有其他占用时，可以立即移动、删除文件组或重新打开。
- 最终 WAL 同步失败传播原始错误，并保留内存、Hook 与文件锁，供宿主处理后重试。关闭等待超时继续推进后台任务。
- Node Hook 由 JS 对象持有，原生侧使用弱引用，引用清理在所属事件线程完成。Python Hook 循环引用参与 GC。成功关闭会清除数据库 Hook；FFI 动态库随最后一个 Hook 所有者释放而卸载。

## 生命周期与 Rust API 迁移

数据读取统一经过生命周期与资源准入检查。以下 Rust 方法返回 `Result`：

`get`、`get_payload`、`get_edge`、`get_edges`、`get_incoming_edges`、`get_all_ids`、`all_node_ids`、`node_count`、`contains`、`neighbors`、`neighbors_with_labels`、`shortest_path`、`graph_stats`、`validate_graph`、`list_indexes`、`list_unique_indexes`、`index_info`、`clear_search_state`。`set_hook` 返回 `Result<()>`。Reader facade、CLI 与 Server 同步处理错误。

```rust
let count = db.node_count()?;
if let Some(node) = db.get(42)? {
    println!("节点 ID：{}", node.id);
}
db.set_hook(my_hook)?;
```

关闭后返回 `DatabaseClosed`。Python/Node 打开状态的返回类型保持一致，关闭后数据访问抛错，资源准入失败保留结构化预算字段；Python 的 `len` 和成员判断采用相同规则。关闭状态、实例与资源统计、维度、dtype 及配置诊断仍可读取，`clear_hook` 仍可清理。

`SearchHook` 增加 `Any` 约束，用于 Python GC 识别原生包装；Rust Hook 实现需要满足 `'static` 生命周期。`hook()` 返回当前 Hook 的 `Arc`，外部持有者负责释放其独立所有权。FFI ABI 继续使用 v2。

## 分组提交与检查点

- `group_commit` 拒绝关闭后的调用；闭包正常返回或 panic 展开均结束同步组，后续普通写入恢复各自的同步模式。闭包内关闭会返回输入错误。
- 同步组结束时若同步失败，当前 WAL 停止接受写入，后续写入返回 `WalClosed`。释放实例后重新打开，按 WAL 恢复结果处理应用层重试。
- 当前格式、没有新增持久化变更的关闭与周期维护保留现有检查点，已发布 manifest 的校验值保持有效。节点、边、属性索引、文本索引与 QuIVer 持久化变更要求新检查点。显式 `flush` 继续执行检查点，历史格式继续在可写关闭时升级。

## 回归与 CI

Rust、Python、Node 增加资源生命周期回归，覆盖三种 dtype、两种存储模式、强引用下的文件操作、关闭失败重试、Hook GC、注册失败保留旧 Hook、冻结 JS 包装对象、FFI 动态库卸载与 Worker 退出。Rust 增加分组提交 panic 后进程强退的恢复检查及关闭请求登记不等待 WAL 锁的并发检查。绑定回归接入 Linux、macOS、Windows CI，Node 发布前校验也执行资源套件。

具体命令见[测试实践](../testing.md#关闭与资源所有权回归)，关闭契约见[生命周期和快照](../lifecycle-snapshots.md)。

## QuIVer 自动切换提前

自动构建阈值调整为 `ceil(666,667 / dim)`，限制在 209–834 节点，约为原值的十二分之一。768 维在 834 节点触发，1536 维在 435 节点触发，3072 维在 218 节点触发。查询准备与连续视图入口统一使用该阈值，Rust、Python 和 Node 复用同一内核规则。构建与查询算法、磁盘格式和禁用自动构建的配置保持原有行为。

## 启动与退出的规模回归

新增三平台原生子进程验收：30 万节点 WAL 恢复与全量 Payload 校验、检查点和 QuIVer 重开内存采样、带在途查询和周期维护的关闭排空。Linux 同时验证真实 SIGTERM 后的落盘、自然退出、重开数据与文件组移动。CI 保存分阶段内存及生命周期诊断报告。

自动阈值回归覆盖全部合法维度的十二分之一规则，并验证三种 dtype、两种存储模式和最高合法维度在阈值前后的实际查询路由及重载。

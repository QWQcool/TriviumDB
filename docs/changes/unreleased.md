# 未发布变更

后续变更以 `0.9.0-beta.2` 为基线；该版本内容见[变更说明](0.9.0-beta.2.md)。

## 事务与 WAL 恢复

- 事务预检按缓冲顺序投影节点存在状态。同一 ID 可在删除后重建、更新或再次删除；重建后的重复插入在写 WAL 前整批拒绝，保留原节点、索引、ID 分配状态和 WAL。
- 自动 ID 在预检中确定；提交后直接应用已校验的 JSON 值。Payload 和边元数据在写 WAL 前验证可恢复的 JSON 深度，底层应用错误向调用方传播。
- WAL 帧与 CRC 校验后继续检查 Payload、边元数据、向量维度、有限数值及插入 ID 边界。语义非法记录返回结构化损坏错误，恢复失败保留原 WAL 与检查点文件。合法 `null`、检查点幂等跳过及未提交事务过滤继续按原契约执行。
- 增加三种 dtype、Rom/Mmap 的有序状态模型、图与文本/唯一索引联动、ID 分配器、非法 WAL 和提交边界回归；Rust、Python、Node 共享固定事务样例，分别验证当前会话、WAL 回放与持久化重开结果。


## 写入、恢复与绑定一致性

- WAL 追加或同步失败后隔离 writer，后续写入、Group Commit 与清空/检查点返回 `WalClosed`，释放句柄重开后执行恢复。此前确认记录继续恢复；失败操作按实际持久化日志核对。
- Payload 与边元数据统一采用读取可接受的 JSON 深度边界；更新、补丁及事务按原始字节和解析值增长进行预算准入。`$inc` 保持整数精度，溢出、非法类型和非有限结果原子拒绝。
- 只读图按边数统计入度，多标签平行边的分数、排序和完整性检查与可写模式一致。
- `.pidx` 升级 v7，绑定实际 Payload 字节；`.gidx` 升级 v3，绑定主文件事实。旧属性索引在内存重建，旧图索引读取主文件；只读打开保持文件零写。
- Python 事务精确提取 `u64` 向量，Payload 整数往返保留完整 `i64/u64`，元组转数组，非法类型和字典键明确拒绝。Node 所有数值 ID 使用安全整数校验，`u64` 分量验证有限性、整数性与范围。
- 增加跨存储模式、dtype、缓存状态、进程退出恢复、旧代 sidecar、合法数值边界和拒绝原子性的泛用测试；Python/Node 公共 API 测试执行相同核心边界。

## Write, recovery and binding consistency

- WAL append or synchronization failures quarantine the writer. Subsequent writes, group commits, clearing and checkpoints return `WalClosed`. Releasing and reopening the handle performs recovery; acknowledged records remain intact, and the failed operation is reconciled against the log that actually persisted.
- Payload and edge metadata share the reader's JSON nesting limit. Updates, patches and transactions admit raw-byte and parsed-value growth before writing. `$inc` preserves integer precision and atomically rejects overflow, invalid types and non-finite results.
- Read-only graphs count incoming edges individually, preserving scores, ordering and integrity checks for multiple labels between the same nodes.
- Property sidecars use v7 and bind the actual Payload bytes. Graph sidecars use v3 and bind the main fact file. Legacy property indexes rebuild in memory; legacy graph indexes use the main graph. Read-only access preserves physical files.
- Python transactions extract `u64` vectors exactly. Payload conversion preserves the complete `i64/u64` integer domain, converts tuples into arrays, and rejects invalid types or dictionary keys. Node numeric IDs share safe-integer validation; `u64` components require finite, integral values within range.
- General boundary tests cover storage modes, dtypes, cache settings, process-exit recovery, stale sidecars, valid numeric limits and rejection atomicity through Rust and installed Python/Node bindings.

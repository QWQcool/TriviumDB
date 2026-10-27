# 未发布变更

后续变更以 `0.9.0-beta.2` 为基线；该版本内容见[变更说明](0.9.0-beta.2.md)。

## 事务最终键、范围候选与 TQL 数值域

- 复合唯一索引按事务最终状态投影所有权，支持临时占用其他节点的键后再次改键、删除或恢复原键。提交前准备并预留最终键变更，提交后统一安装；异常展开恢复同步标志并隔离实例。WAL 回放后从最终事实恢复并验证唯一映射，验证成功后截断日志。
- Ordered ART 范围遍历在 LIMIT/OFFSET 前约束数值或字符串类型，混合类型字段保持完整范围结果。
- TQL 的字面量、Prepared 参数、运行时及一等值新增完整无符号整数表示，投影、WHERE、排序和聚合保持整数精度。整数加减乘及 SUM 返回整数，整数溢出返回 Null；MIN/MAX 保留选中值。浮点相等采用实际值比较，除法检查实际零分母，有限小分母正常计算。
- Python 保留完整 `int`；Node 的超安全整数标量及列表/对象中的相应整数返回十进制字符串。Rust 调用方可匹配新增的 `UInt(u64)` 变体；Server 查询协议同步提供 `uint` 编码。
- Hash、Ordered、Bitmap、Composite、N-gram 与唯一索引创建共用解析/构建峰值准入和隔离候选构建。预算拒绝、非法字段值或唯一约束失败保持已有定义、缓存与 WAL，可调整配额后重试。
- 新增事务多次改键与 WAL 恢复、混合类型分页、完整整数/浮点边界、七类索引预算和跨语言安装制品回归。差分参考模型按有界原生整数与固定样例分别验收整数运算及完整 u64 域。

## Final transaction keys, typed ranges and TQL numbers

- Composite unique indexes project ownership from the final transaction state. A node may temporarily use another node's key before changing it again, deleting it or restoring its original key. Final key changes are prepared and reserved before the WAL, then installed together after application. Unwinding restores synchronization flags and isolates the instance. Recovery rebuilds and validates ownership from final facts before truncating the WAL.
- Ordered ART traversal restricts candidates to the boundary's numeric or string type before LIMIT/OFFSET, preserving range results for mixed-type fields.
- TQL literals, prepared parameters, runtime values and public results represent the full unsigned integer domain. Projection, WHERE, sorting and aggregates preserve integer precision. Integer addition, subtraction, multiplication and SUM retain integer results; integer overflow returns Null. MIN/MAX preserve the selected value. Floating equality compares actual values, and division treats only actual signed zero as a zero denominator.
- Python preserves exact integers. Node returns decimal strings for unsafe integer scalars and corresponding integers inside projected lists and objects. Rust exposes the new `UInt(u64)` variants; the Server query protocol adds `uint` encoding.
- Hash, Ordered, Bitmap, Composite, N-gram and unique index creation share parsing/build peak admission and isolated candidate construction. Budget rejection, invalid indexed values and uniqueness failures preserve existing definitions, caches and the WAL; callers can adjust the quota and retry.
- Regression cases cover repeated key changes and recovery, typed range pagination, integer/floating boundaries, seven index admission paths and installed language packages. The independent differential model covers bounded native integer arithmetic, while fixed boundary cases cover the full u64 domain.

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


## 检索确定性与计量开销

- BruteForce 分片采用有界 Top-K 堆，按分数降序、外部 NodeId 升序合并和截断。QuIVer 默认 SM 与公开 BQ 路径在精排名额和最终同分结果中使用外部 NodeId；无效查询按现有 Vec 返回契约拒绝，冷向量的维度和有限数值统一校验。
- 有序索引在 2^53 数值边界回退精确范围比较，包含该范围数值键的 `ORDER BY` 从 Payload 精确排序后分页。普通与管线字段排序覆盖完整 `i64/u64` 整数域及混合浮点数。
- Payload、图、属性 posting、文本和 QuIVer 热内存使用增量计数或容量计量；写入准入与查询观测按索引定义数量读取估算。TQL 阶段预算直接读取 Payload 访问计数。属性统计保持跨加载模式的字段及索引类型顺序。
- 实验追加构图入口使用顺序反向剪枝，保持追加行为与邻居选择语义，并移除跨线程创建可变自身引用的实现。
- 事务应用通过 RAII 恢复 QuIVer 同步标记；应用异常后隔离实例和共享查询，完整 WAL 经重开恢复。事务编号使用进程内单调计数并检查耗尽。
- 增加槽位复用、分段与并行 Top-K、非法冷向量、极值排序、增量计量重载，以及已准入查询与事务故障交错测试。

## Deterministic retrieval and accounting cost

- BruteForce uses bounded per-partition Top-K heaps, merging and truncating by descending score and ascending external NodeId. Default SM and public BQ reranking apply external NodeId tie-breaking before rerank admission and final truncation. Invalid queries follow the existing Vec return contract; cold vectors share dimension and finite-value validation.
- Ordered range boundaries at the 2^53 magnitude use exact fallback comparisons. Indexes containing such numeric keys defer ORDER BY pagination to exact Payload sorting. Plain and pipeline property ordering preserve the complete i64/u64 integer domain and mixed finite floating-point values.
- Payload, graph, property posting, text and QuIVer hot-memory estimates use incremental counters or capacities. Admission and query observations read accounting by index definition count. TQL stage budgets read Payload access counters directly. Property diagnostics retain field and index-kind order across loading modes.
- The experimental append builder performs reverse pruning sequentially, preserving append and neighbor-selection behavior while removing concurrent mutable self references.
- An RAII guard restores QuIVer synchronization state. Unexpected transaction application failures isolate the instance and shared queries; reopening replays the complete committed WAL. Transaction IDs use a checked process-local monotonic counter.
- Boundary tests cover slot reuse, segmented and parallel Top-K, invalid cold vectors, numeric extremes, accounting after reload, and admitted queries interleaved with application failures.


## 索引覆盖、图资源与数字接口

- 删除 Hash 唯一索引同步移除唯一约束。Ordered 排序和复合前缀/范围访问按字段覆盖情况选择完整候选；缺失字段、容器与混合排序类型通过扫描保留结果。复合唯一约束使用完整类型键，精确保留 i64/u64/f64 标量，打开时从 Payload 事实恢复映射；查询 posting 和磁盘格式继续使用现行版本。
- 图写入在 WAL 前检查标签 65,535 UTF-8 字节上限和预算。堆账本计入标签、Metadata、邻接容量、反向索引、标签索引、统计及只读图缓存；普通修改增量维护，移除最后一条入边同步清理零入度项。
- Rust/Python 节点 ID 保留 `1..=u64::MAX-1`；保留值和自动分配耗尽在 WAL 前拒绝。Node 数量参数在整数转换前校验，数字 ID 的全部输出遵守安全整数范围，超范围返回参数错误；TQL 返回完整字符串 ID。自动插入、批量、事务、TQL CREATE 和迁移在持久化变更前检查返回 ID。
- 新增固定跨端 WAL 样本，以及覆盖部分索引、唯一键交换、标签字节边界、图堆账本、预算拒绝、同步/异步搜索、遍历、只读零写和恢复的边界测试。

## Index coverage, graph resources and numeric interfaces

- Dropping a unique Hash index removes its constraint definition. Ordered sorting and composite prefix/range access select complete candidates based on field coverage. Scans preserve records with missing fields, containers or mixed sorting types. Composite uniqueness uses full typed scalar keys, preserving i64/u64/f64 values exactly, and restores its map from Payload facts on open. Query postings retain the current disk formats.
- Graph writes check the 65,535 UTF-8-byte label limit and memory admission before WAL writes. Heap accounting includes labels, metadata, adjacency capacities, reverse and label indexes, statistics and read-only graph caches. Ordinary mutations maintain counters incrementally, and removing the final incoming edge removes its zero-degree entry.
- Rust/Python node IDs retain `1..=u64::MAX-1`; reserved values and exhausted allocation fail before WAL writes. Node validates quantities before integer conversion and enforces safe integers for every numeric ID result. Oversized results return an input error; TQL returns complete string IDs. Automatic, batch, transaction and TQL CREATE allocation, plus migration, validate result IDs before persistent changes.
- Boundary tests add a fixed cross-language WAL sample and verify partial indexes, unique-key swaps, UTF-8 labels, graph heap accounting, admission rejection, synchronous/asynchronous search, traversal, read-only file preservation and recovery.

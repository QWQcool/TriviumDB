# 未发布变更

后续变更以 `0.9.0-beta.3` 为基线；该版本内容见[中英文变更说明](0.9.0-beta.3.md)。

- MATCH 反向遍历按实际边保留平行边行重数，具名与匿名边共用枚举；双向单跳自环计一次，索引前后保持相同计数。
- 图模式与可变长路径改用显式栈；最小跳数前的探索、边扫描和回溯统一计步并检查取消/期限，工作区提前准入。增加小栈子进程、运行中取消和指数路径回归。
- 精确、GraphFirst、普通与物理检索算子共享维度和有限值校验；候选池倍增使用饱和算术，超大 Top-K 保持有界结果。

- 内核统一错误码和结构化详情；Python 异常与 Node 同步/异步错误保留类别、版本、节点、约束、迁移和预算字段。Prepared 缺参/额外参数提供独立类别与参数名，额外参数按名称稳定选择。查询行超限统一返回查询预算错误。
- Rust 穷尽匹配新增 `MissingQueryParameter`、`UnexpectedQueryParameter` 分支；查询行超限使用 `QueryRowBudgetExceeded`。Node 错误详情的大整数类型为 `number | string`，调用方按字段类型读取。
- 三端共享真实 API 错误用例，检查完整详情和语言映射；Rust/Python 映射样例涵盖全部核心错误变体。Node 错误字段中的大整数使用十进制字符串。
- Mmap、Rom、快照说明与文件组布局同步，安全文档引用当前模块；README 标明 Python 3.9–3.12 安装范围。
- 两条 CD 共用发布来源校验。Stable Tag 对应 master 发布主线中的同仓库 dev → master 合并提交，并核对同提交 master CI；历史 Release 可在 master 前进后按原 Tag 补发。Beta 保留现行公开测试质量门禁。
- 来源校验器从工作流提交加载到 Runner 临时目录，历史 Tag 使用原始源码参与验收和构建。

- `.tdb` 升级为 v10：文件头保存 dtype、元素宽度与 CRC；错误类型在写入前拒绝，Rom/Mmap 校验精确向量块长度。新库先完成准入并保存类型检查点，再接收 WAL。非空 v5–v9 检查点按几何验证；历史仅 WAL/无类型空基础附带日志的样本，先用原版本恢复和完成检查点。回退使用升级前备份。旧空库升级按文件组发布并保留索引定义；只读加载保留空 Hash 索引字段。
- Windows 向量替换或重映射失败导致当前映射失效时，实例及共享句柄进入待恢复状态，保留原 I/O 错误与 WAL，释放后重新打开恢复。
- TQL 全部字符串解析入口验证完整输入；新增输入大小、token、括号与运算复杂度限制，覆盖连续 NOT 和平坦表达式链。非法写尾部在执行前拒绝。
- 打开流程在节点、Payload、图、派生索引和 WAL 解码前检查保守峰值及实例预算，最终复核实际估算；容量准入完成后迁移/截断 WAL。预算拒绝释放共享预留并保留恢复依据。恢复阶段暂缓填充解析缓存，成功后按剩余预算设置缓存上限。
- 新增 Rust、Python、Node 的类型、解析、预算与恢复边界测试；Linux CI 执行 release 2 MiB 小栈解析回归，Windows 测试使用真实共享标志验证文件替换失败。

- 唯一约束创建与删除持有写锁完成发布。发布失败隔离实例和共享句柄；可写重开根据提交点恢复旧约束或采用新约束，再回放 WAL。预检拒绝保持实例可用。
- `.pidx v8` 使用 JSON 字符串数组保存复合字段列表，保留 NUL、转义及 Unicode。历史复合 posting 由事实扫描提供结果，唯一约束从主文件定义恢复；普通复合索引可按原字段列表重新创建。复合字段名总长最多 1 MiB，数量为 2–65,535。
- Node JSON 输入输出统一使用带长度的属性名，保留嵌套 NUL 键和 `__proto__` 自有属性，覆盖 CRUD、事务、过滤器、业务边、Hook 和查询结果；非法 JSON 值及循环结构在写入前拒绝。
- 图副本在采用前完整验证边、数量和目录，并与主文件端点、标签、边权及 Metadata 逐项比对。只读校验失败保留文件组并返回损坏错误；Writer 可显式重建。校验及 JSON 解码峰值参与加载准入。
- 增加发布提交前后故障、持有句柄隔离、恢复数据与约束、v7 复合兼容、CRC 一致图畸形样例，以及实际 Python/Node 制品的共享契约验收。

- 浮点余弦在范数、点积或分母发生上溢/下溢时回退到 `f64` 累加，常规有限幅值保留 SIMD；覆盖通用和 384 维缓存范数路径，零向量得分为 `0`。
- `u64` 基础检索保持完整位模式，统一使用精确汉明匹配位数。自动 QuIVer 构建按浮点 dtype 选择，历史二进制索引副本跳过采用，显式 `u64` 构建返回结构化输入错误；Hook 浮点观察视图的向量改写明确拒绝。
- 维度迁移在写入前拒绝已有目标文件组，先完成独占暂存构建，再在目标写锁下发布文件组并交接锁。发布使用同盘原子硬链接；提交前只回收本次创建的目录项，提交后保留完整新库。源库和碰撞文件保持原样。
- 增加独立几何与整数样例、SIMD/缓存范数、三端检索、迁移故障、提交点及目标锁交错测试。

## Unreleased

Subsequent changes build on `0.9.0-beta.3`. See the bilingual [release notes](0.9.0-beta.3.md).

- Reverse MATCH traversal preserves a row for every physical parallel edge. Named and unnamed patterns share enumeration; bidirectional single-hop matching counts each self-loop once, with consistent counts before and after indexing.
- Graph patterns and variable-length paths use explicit stacks. Exploration below the minimum depth, edge scans and backtracking consume a shared step budget and check cancellation/deadlines. Workspace admission precedes traversal. Regressions cover small-stack subprocesses, in-flight interruption and exponential path graphs.
- Exact, GraphFirst, ordinary and physical vector operators share dimension and finite-value validation. Candidate-pool expansion uses saturating arithmetic, keeping oversized Top-K requests bounded by actual candidates.

- Core errors expose stable codes and structured details. Python exceptions and synchronous/asynchronous Node errors retain version, node, constraint, migration and budget fields. Prepared statements report missing and unexpected parameter names through dedicated categories; unexpected names are selected deterministically. Row-limit failures consistently report the query-budget category.
- Exhaustive Rust matches include the new `MissingQueryParameter` and `UnexpectedQueryParameter` variants. Row-limit failures use `QueryRowBudgetExceeded`. Large integer fields in Node error details have type `number | string`; callers read them according to their runtime type.
- Shared real-API cases assert complete error details across all three languages. Rust and Python mapping samples cover every core error variant. Node preserves large integers in error details as decimal strings.
- Mmap, Rom and snapshot documentation describe the current file group, security references point to current modules, and both READMEs state the Python 3.9–3.12 installation range.
- Both CD workflows share release provenance validation. Stable tags identify a same-repository dev-to-master merge on master's release history with successful master CI for that exact commit. Historical releases remain eligible for recovery publishing after master advances. Beta releases retain their public-testing quality gates.
- The provenance validator is loaded from the workflow commit into the runner's temporary directory, while historical tags retain their original source for validation and builds.

- `.tdb` v10 stores dtype, element width and a header CRC. Mismatched types are rejected before writes, and both layouts require exact vector geometry. New databases pass admission and persist type identity before accepting WAL entries. Nonempty v5–v9 checkpoints establish dtype from geometry; historical WAL-only data and untyped empty checkpoints with nonempty WAL must first be recovered and checkpointed with their original version. Downgrades use pre-upgrade backups. Empty legacy databases migrate their complete file group and retain index definitions; read-only loading retains empty Hash index fields.
- Vector replacement or remapping failures that invalidate a live mapping quarantine the instance and shared query handles. The original I/O error and WAL remain available; release the instance and reopen writable to recover.
- Every TQL string parser requires complete input consumption. Limits on bytes, tokens, nesting and operators cover repeated NOT and flat expression chains. Invalid mutation tails are rejected before execution.
- Opening checks conservative allocation peaks for nodes, payloads, graph data, derived indexes and WAL, then verifies the final heap estimate. WAL migration/truncation follows admission. Rejected opens release shared reservations and preserve the WAL for a later retry. Recovery defers parsed-cache population and configures the cache against remaining heap headroom afterward.
- Rust, Python and Node regressions cover type, parser, budget and recovery boundaries. Linux CI runs optimized parsing on a 2 MiB stack; Windows tests use actual file-sharing flags to exercise replacement failures.

- Unique constraint creation and removal hold the write lock through publication. Publication errors quarantine the instance and shared query handles; writable reopening uses the actual commit point to recover the old schema or accept the new schema, then replays WAL. Validation failures leave the instance usable.
- `.pidx` v8 encodes composite fields as a JSON string array, preserving NUL, escapes and Unicode. Legacy composite postings fall back to ground-truth queries; unique constraints rebuild from authoritative main-file definitions. Recreate ordinary composite indexes with their original field list. Composite names total at most 1 MiB across 2–65,535 fields.
- Node JSON boundaries use length-aware property names throughout CRUD, transactions, filters, business edges, hooks and query results. Nested NUL keys and own `__proto__` data properties round-trip; invalid JSON values and cyclic structures are rejected before writes.
- Graph sidecars validate every edge, count and directory against each other and compare endpoints, labels, weights and Metadata with main-file facts before adoption. Read-only failures preserve the file group and report corruption; writers can explicitly rebuild the sidecar. Validation and JSON decode peaks participate in load admission.
- Regression coverage includes pre/post-commit failures, retained handles, recovered data and constraints, v7 composite compatibility, CRC-consistent graph mutations and actual Python/Node artifacts.

- Cosine kernels fall back to f64 accumulation when norms, dot products or denominators overflow or underflow, while ordinary finite magnitudes retain SIMD execution. Both general and cached 384-dimensional paths share the checks; zero vectors score zero.
- Basic u64 retrieval preserves complete query bit patterns and consistently scores matching bits through exact Hamming search. Automatic QuIVer construction selects floating-point dtypes; historical binary sidecars are skipped, and explicit u64 construction returns a structured input error. Observable floating-point hook query rewrites are rejected for binary fingerprints.
- Dimension migration rejects existing destination artifacts before writing, builds a private staging database, publishes under the destination write lock, and transfers that lock to the returned instance. Publication uses atomic same-filesystem hard links. Pre-commit failures reclaim only newly created entries; post-commit failures preserve the complete new database. Source data and colliding files remain unchanged.
- Independent geometry/integer examples, SIMD/cached-norm checks, native SDK retrieval, migration faults, commit boundaries and lock interleavings extend regression coverage.

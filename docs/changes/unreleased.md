# 未发布变更

后续变更以 `0.9.0-beta.3` 为基线；该版本内容见[中英文变更说明](0.9.0-beta.3.md)。

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

## Unreleased

Subsequent changes build on `0.9.0-beta.3`. See the bilingual [release notes](0.9.0-beta.3.md).

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

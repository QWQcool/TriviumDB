# 未发布变更

后续变更以 `0.9.0-beta.3` 为基线；该版本内容见[中英文变更说明](0.9.0-beta.3.md)。

- 内核统一错误码和结构化详情；Python 异常与 Node 同步/异步错误保留类别、版本、节点、约束、迁移和预算字段。Prepared 缺参/额外参数提供独立类别与参数名，额外参数按名称稳定选择。查询行超限统一返回查询预算错误。
- Rust 穷尽匹配新增 `MissingQueryParameter`、`UnexpectedQueryParameter` 分支；查询行超限使用 `QueryRowBudgetExceeded`。Node 错误详情的大整数类型为 `number | string`，调用方按字段类型读取。
- 三端共享真实 API 错误用例，检查完整详情和语言映射；Rust/Python 映射样例涵盖全部核心错误变体。Node 错误字段中的大整数使用十进制字符串。
- Mmap、Rom、快照说明与文件组布局同步，安全文档引用当前模块；README 标明 Python 3.9–3.12 安装范围。
- 两条 CD 共用发布来源校验。Stable Tag 对应 master 发布主线中的同仓库 dev → master 合并提交，并核对同提交 master CI；历史 Release 可在 master 前进后按原 Tag 补发。Beta 保留现行公开测试质量门禁。
- 来源校验器从工作流提交加载到 Runner 临时目录，历史 Tag 使用原始源码参与验收和构建。

## Unreleased

Subsequent changes build on `0.9.0-beta.3`. See the bilingual [release notes](0.9.0-beta.3.md).

- Core errors expose stable codes and structured details. Python exceptions and synchronous/asynchronous Node errors retain version, node, constraint, migration and budget fields. Prepared statements report missing and unexpected parameter names through dedicated categories; unexpected names are selected deterministically. Row-limit failures consistently report the query-budget category.
- Exhaustive Rust matches include the new `MissingQueryParameter` and `UnexpectedQueryParameter` variants. Row-limit failures use `QueryRowBudgetExceeded`. Large integer fields in Node error details have type `number | string`; callers read them according to their runtime type.
- Shared real-API cases assert complete error details across all three languages. Rust and Python mapping samples cover every core error variant. Node preserves large integers in error details as decimal strings.
- Mmap, Rom and snapshot documentation describe the current file group, security references point to current modules, and both READMEs state the Python 3.9–3.12 installation range.
- Both CD workflows share release provenance validation. Stable tags identify a same-repository dev-to-master merge on master's release history with successful master CI for that exact commit. Historical releases remain eligible for recovery publishing after master advances. Beta releases retain their public-testing quality gates.
- The provenance validator is loaded from the workflow commit into the runner's temporary directory, while historical tags retain their original source for validation and builds.

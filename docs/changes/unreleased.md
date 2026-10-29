# 未发布变更

后续变更以 `0.9.0-beta.4` 为基线；该版本内容见[中英文变更说明](0.9.0-beta.4.md)。

- 维度迁移发布使用不覆盖既有目标的原子重命名，替代暂存库与目标之间的硬链接。进程在发布期间被强杀后，Unix 打开入口不会再因遗留的第二个主文件链接挡住恢复；提交前按发布日志回滚，提交后保留完整目标，源库保持原样。源、目标目录均在提交点前后同步。底层文件系统必须支持排他原子重命名；不支持时返回 I/O 错误，不退回覆盖或非原子复制。
- 增加 Rom/Mmap 源库在首文件发布后、提交前及提交后强杀的回归，验证源文件组、目标节点/向量/Payload/业务边、只读零写，以及再次打开和持久化结果。普通硬链接别名仍按既有规则拒绝。
- 迁移预检按实际文件系统规则识别主文件与任意同名前缀侧文件的大小写别名，遇到已有文件组时在创建目标租约、暂存库或发布日志前返回 `TDB_IO` / `AlreadyExists`，避免把新库第一代发布日志写到已有多代数据库。区分大小写的目录仍允许独立目标，实际空闲协调锁可复用；Unix 同时保留非 UTF-8 侧文件并拒绝悬空主文件链接。
- npm/PyPI 发布摘要按真实上传作业结果区分成功、失败、取消及上游阻断；只有版本门禁确认版本已存在时才标为跳过。Python 版本显示遵循 PEP 440。上传成功不表示 npm 的异步公开处理已完成。

## Unreleased

Subsequent changes build on `0.9.0-beta.4`. See the bilingual [release notes](0.9.0-beta.4.md).

- Dimension migration now publishes with exclusive atomic renames instead of hard links between staging and destination files. After a process is killed during publication, Unix opening no longer rejects the destination because of a leftover second main-file link: pre-commit state rolls back through the publication journal, committed targets retain complete data, and the source remains unchanged. Both source and destination directories are synchronized around the commit point. The filesystem must support exclusive atomic renaming; unsupported operations return an I/O error without falling back to replacement or non-atomic copying.
- New regressions kill migrations from Rom and Mmap sources after the first file, before commit and after commit. They check source-file preservation, complete destination nodes/vectors/Payload/business edges, physical zero-write read-only access, reopening and persistence. Ordinary hard-link aliases remain rejected.
- Migration preflight recognizes case aliases of the main file and arbitrary same-prefix sidecars according to the actual filesystem. Existing file groups return `TDB_IO` / `AlreadyExists` before creating a destination lease, staging database or publication journal, preventing a new database's first-generation journal from being applied to an existing multi-generation database. Case-sensitive directories still permit independent destinations, and actual idle coordination locks remain reusable. Unix checks also preserve non-UTF-8 sidecars and reject dangling main-file symlinks.
- npm/PyPI release summaries distinguish successful, failed, cancelled and upstream-blocked uploads using actual job results. Existing-version skips require confirmation from the version gate. Python versions use PEP 440 notation. Successful upload does not imply that npm has finished its asynchronous public processing.

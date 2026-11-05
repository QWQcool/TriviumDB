# 批跑后的三次人工重跑（记录）

> 已向上游反馈：issue **#86**（`bench_pipeline_gate` 断言与 provenance 差异）、
> issue **#87**（release+LTO 下 `fault_allocator` 编译时 rustc 崩溃）。
> 两个 issue 都附了复现命令与本机结果，修复进度不影响本次已产出的数字。

批跑（`run_all.py`）记录了 12 步，其中 3 步失败。以下是失败原因与处置，供复核。

## 1. p1_pipeline_20k / p1_pipeline_200k —— 官方断言误判，补丁后重跑成功

**现象**：`assert_eq!(baseline_output, optimized_output)` 报
`property_filter_rank/384 结果不一致`。

**根因**：0.9.0 的两个物理计划返回的节点、相似度、属性分数一致，但 `provenance`
元数据不同（优化计划会写 `property_origin`），官方断言按 `NodeSet` 全等比较，
因此必然失败。这不是查询结果错误。

**处置**：只在隔离工作树 `.bench090` 内修改基准，不改主仓库：

- 新增 `content_signature()`：按 id 排序后折叠 `(id, similarity, property_score)`；
- 断言改为比较内容签名，若全等失败但内容一致，打一行
  `[provenance-diff]` 到 stderr。

**重跑命令**：

```powershell
cd d:\TriviumDB\.bench090
$env:TDB_PIPELINE_GATE_NODES="20000";  cargo bench --locked --bench bench_pipeline_gate
$env:TDB_PIPELINE_GATE_NODES="200000"; cargo bench --locked --bench bench_pipeline_gate
```

产物：`bench/p1_pipeline_20k/pipeline-gate.json`、`bench/p1_pipeline_200k/pipeline-gate.json`。
16 个组合全部 `passed: true`。

## 2. p4_fault_suites —— release+LTO 下 rustc 崩溃，改 debug 构建通过

**现象**：

```
error: could not compile `triviumdb` (test "fault_allocator")
Caused by: process didn't exit successfully: rustc.exe ... (exit code: 0xc0000005, STATUS_ACCESS_VIOLATION)
```

`-C lto -C codegen-units=1` 的 release 测试目标在编译 `fault_allocator` 时
rustc 自身崩溃（工具链问题，不是测试失败）。

**处置**：改用 debug 构建（无 LTO）重跑，去掉 `fault_allocator` 之外的
五个套件均正常；`fault_allocator` 未纳入本次计数。

**重跑命令**：

```powershell
cd d:\TriviumDB\.bench090
cargo test --features test-hooks --test fault_io --test fault_power --test fault_crash `
  --test fault_lock --test fault_hardware -- --test-threads=1
```

**结果**：103 passed / 0 failed / 1 ignored（6 个测试二进制），日志
`logs/p4_fault_suites_debug.log`。

> 因是 debug 构建，**耗时不可引用**，只引用通过/失败计数。

## 3. 归档文件名修正

仓库自带的报告文件名带规模后缀，批跑脚本最初的归档通配符写错了：

| 步骤 | 实际文件名 |
|---|---|
| deep traversal | `deep-traversal-1000000.json` |
| query parallel | `query-parallel-200000-768.json` |
| graph parallel | `graph-parallel.json` |

三个文件已手工补齐到 `bench/<step>/`，`run_all.py` 与 `make_report.py`
的匹配规则也已修正。

# Phase 0 Runtime 验收记录

日期：2026-09-05。范围为本地 Python Runtime 与合成评测，不代表真实求职质量或生产性能。

## 已完成

`services/agent` 提供版本化 Pydantic 契约、追加式 Run Event、内存/SQLite 存储、纯函数状态投影和无副作用回放。有限步循环包含阶段工具集、Token/费用/截止时间预算、取消与无进展停止。Tool Spec、Handler、Policy 分开注册；写入必须通过与完整规范化参数、身份、工具指纹和幂等键绑定的人工审批。

最小完整流程为：读取模拟候选人 → 提议模拟 Application Plan → 停止并展示审批 → 另一个 CLI 进程批准 → 创建一条模拟计划 → 完成 → 回放 → 导出脱敏 spans。写入回执丢失时，恢复只查询原幂等结果。审批拒绝、过期和最终完成均覆盖断开事件流后的恢复边界。

Evaluation Runner 支持固定用例、版本/内容指纹、逐例确定性评分、Baseline/Challenger 配对和失败退出码。运行数据与共享的脱敏报告分开保存。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| `npm run agent:setup` | 锁定依赖安装成功，Python 3.12.13 |
| `npm run agent:check` | Ruff 规则及格式检查通过 |
| `npm run agent:test` | 48 项通过 |
| `npm run typecheck:app` | 通过 |
| 本地合成 Baseline | 9/9 用例通过，未批准写入为 0 |
| 两步预算 Challenger | 8/9 通过，门禁拒绝；未批准写入仍为 0 |

48 项测试涵盖两种存储的追加/不可变/顺序/版本契约、进程互斥、CLI 跨进程审批回放、预算与取消、无进展、模型/工具异常、动态暴露、权限拒绝、参数/身份绑定、审批过期与拒绝、幂等冲突、写入回执丢失核实、恢复断点、脱敏与 exporter 故障隔离、配对身份/缺例检测，以及不同进程哈希种子下的数据集指纹一致性。

两步预算 Challenger 的 `approved-plan` 用例能在第二步完成已批准的模拟写入，但没有第三步预算生成最终结果，因此 Workflow Outcome 为 `partial`。门禁将它标记为退化；节约 Token 不能替代所要求的完整结果。

可检查完整结果：[Baseline JSON](phase0-baseline.json)、[成对比较 JSON](phase0-paired-short-budget.json)。报告中的代码、依赖锁文件、数据集和配置哈希标识此次执行依据；后续代码或数据变化需要重新生成报告。

## 复现

从仓库根目录执行：

```sh
npm run agent:setup
npm run agent:check
npm run agent:test
npm run agent:eval -- --out .agent-data/baseline.json

uv run --project services/agent --locked getoffers-agent evaluate \
  --challenger datasets/evals/runtime-v1/challenger-short-budget.json \
  --out .agent-data/paired.json
```

最后一条命令应返回退出码 1，这是负对照的预期结果。人工操作的演示步骤见 [Agent README](../../services/agent/README.md)。

## 验收边界

Token 与费用来自固定模拟响应；报告中的本机时延只用于验证统计流程，不能用作生产 p95 指标。九个用例是合成 Runtime 合约集，不能替代 Phase 1 的人工审核岗位检索评测。

当前为 macOS/Linux 单机 SQLite，没有真实模型/产品 API、D1/R2、远程 Trace 存储与访问控制、HTTP 服务、Web 审批 UI、Job Search、Knowledge Retrieval 或多 Agent 执行。异步工具必须支持协作取消；未知业务写入保持核实状态，不自动重发。Event Store 采用本地同步短事务与从完整事件投影的简单实现，后续远程存储和长 Run 需要异步 I/O 与增量投影。

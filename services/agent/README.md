# GetOffers Agent — Runtime 与 Job Search

本地 Python Harness 已实现：类型化 Run Event、有限步循环、工具策略、精确参数审批、SQLite 暂停恢复、无副作用回放，以及固定合成用例的 Evaluation Runner。

下文介绍 Phase 0 Runtime，使用 Fake Model Provider 和 Fake Product Port，演示只写本地模拟计划表。Phase 1 已新增独立 Job Search 模块、真实 BGE 适配与产品查询接口，见 [岗位检索指南](SEARCH.md)。用户知识库、审批写入、ReAct 助手及本机 Codex 已由后续模块实现；当前阶段见 [路线图](../../docs/architecture/implementation-roadmap.md)，开发者查看入口见 [Phase 4 说明](../../docs/experiments/phase4-developer-inspector.md)。下文仅描述 Phase 0 演示自身。

## 从仓库根目录启动

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/) 和 macOS/Linux（本地进程互斥使用 `flock`）。依赖版本已固定在 `uv.lock`；无需模型 API key。

```sh
npm run agent:setup
npm run agent:test
npm run agent:check
npm run agent:demo
```

也可以直接运行 `uv sync --project services/agent --locked`，所有入口都可通过 `uv run --project services/agent --locked getoffers-agent ...` 使用。默认数据目录是当前目录下的 `.agent-data/`，已加入 Git 忽略。

`demo` 读取模拟候选人资料，然后打印 `workflow_run_id` 和 `pending_approval` 并退出。审批内容包括具体工具、完整规范化参数、用户/租户、参数哈希、操作 ID、幂等键与失效时间。确认内容后，使用输出中的三个值：

```sh
uv run --project services/agent --locked getoffers-agent approve RUN_ID \
  --action-id ACTION_ID --arguments-hash ARGUMENTS_HASH
```

将 `approve` 改为 `reject` 可以拒绝。默认审批有效期为 5 分钟，整个 Run 的截止时间为启动后 10 分钟。过期后启动新的 `demo`；旧审批不能授权新 Run 或更改后的参数。

```sh
# 只读取历史，不创建模型或产品适配器
uv run --project services/agent --locked getoffers-agent replay RUN_ID

# 从已提交事件恢复执行；不会替用户批准
uv run --project services/agent --locked getoffers-agent resume RUN_ID

# 导出脱敏的 span JSON；可作为后续 OTEL exporter 的输入
uv run --project services/agent --locked getoffers-agent spans RUN_ID \
  --out .agent-data/spans.json

uv run --project services/agent --locked getoffers-agent list
```

可在子命令前加 `--data-dir PATH`。多个 CLI 进程必须使用同一目录才能恢复同一 Run。

## 核心接口与代码入口

| 模块 | 责任 |
| --- | --- |
| `domain/contracts.py` | Session、Workflow/Agent Run、Step、Budget、Outcome、Context、Tool、Approval、错误契约 |
| `runtime/events.py` | 版本化事件词汇、载荷校验、顺序/身份校验、纯函数投影 |
| `adapters/events.py` | 内存/SQLite 追加存储、本地进程互斥 |
| `runtime/engine.py` | `run` / `resume` 异步事件流与 `replay` 纯读取 |
| `runtime/tools.py` | Tool Spec、Handler、Policy 与 Registry |
| `runtime/context.py` | 确定性阶段切换、模型可见工具、版本化 Context Manifest |
| `adapters/fakes.py` | 按 Step 回应的模拟模型、支持幂等查询的模拟产品表 |
| `career/demo.py` | 读取 → 提议计划 → 总结的最小工作流 |
| `runtime/telemetry.py` | 仅允许固定字段的脱敏投影；导出失败不影响执行 |
| `evaluation/runner.py` | 固定用例、确定性评分、成对比较与回归门禁 |

```python
async for event in runtime.run(request):
    ...  # 事件已持久化；消费方可展示进度

async for event in runtime.resume(resume_request):
    ...  # 必须传入产品层确认过的当前身份和权限

projection = runtime.replay(workflow_run_id)
```

事件是状态源，`checkpoint.created` 是可丢弃的进度标记；恢复时从事件重建状态，不依赖 Python 对象、模型游标或内存中的审批。实现保留父/子 Agent ID 与 linked Run ID；当前执行一个 Agent、每步最多一个工具。此阶段本地 Event Store 使用同步短事务，异步模型/工具使用可注入接口；后续远程存储适配器需要异步 I/O 接口。

## 恢复、审批与预算语义

- 写入前持久化 `tool.started`。审批绑定规范化后的全部参数、工具指纹、用户、租户、有效期和幂等键；恢复时重新检查当前权限。
- 审批拒绝/过期与终态原子提交。重复恢复终态返回空事件流；重复点击不会再次执行工具。
- 写入可能成功但回执丢失时进入 `awaiting_reconciliation`。`resume` 仅按原幂等键查询结果；只有确认结果才继续。`not_found` 或 `unknown` 继续等待核实，绝不盲目重发。截止时间耗尽或取消会终止 Run；实际业务结果仍需通过产品记录核实。
- `replay` 永远不调用模型、工具或幂等查询。需要重新执行时，创建新的 Run；可用 `linked_run_id` 关联原 Run。
- 已记录模型结果可直接恢复处理。进程在模型调用期间退出而没有结果时，标记 `interrupted` 和未知用量并停止，避免在未知费用下悄悄再调一次模型。
- 步数、总截止时间、输入/输出 Token、费用、连续相同工具结果的无进展次数都有停止条件。达到 Token/费用上限可结束当前 Step，但不能开启下一次模型调用；超过上限立即停止后续工具动作。
- 实际用量由 Provider 报告，剩余额度随 Model Request 传入。真实 Provider 必须限制输出并报告用量；已花费的超额费用无法事后撤回。异步适配器必须协作处理取消，阻塞或吞掉取消的第三方代码需要进程隔离后才能接入。

## Evaluation Runner

```sh
npm run agent:eval

# 同一用例配对比较；该 Challenger 故意只允许两步，应返回退出码 1
uv run --project services/agent --locked getoffers-agent evaluate \
  --challenger datasets/evals/runtime-v1/challenger-short-budget.json \
  --out .agent-data/paired.json
```

数据集位于 [datasets/evals/runtime-v1](../../datasets/evals/runtime-v1/)。报告记录数据集/配置/运行代码哈希、逐例 Runtime 指纹、评分版本、合成数据版本、结果、Token、费用口径和时延。Baseline 与 Challenger 必须使用相同 case IDs、数据与评分身份；缺例、重复例或身份错配直接拒绝比较。

这些用例验证 Runtime 合约与权限边界，未经人工标注为真实求职质量样本。模型 Token 与费用是固定合成值，时延是本机假适配器实测；不能据此宣称真实模型质量、生产 p95 或零运行成本。评测中的批准来自合成测试夹具，CLI 演示始终等待用户选择。

## 数据与接入边界

本地 SQLite 保存完整 restricted trace，数据库文件以仅当前用户可读写的权限创建；没有 HTTP 访问控制、加密或远程存储，适用于受信任的本地开发。模型输入输出、工具参数与个人信息不会进入脱敏 span；异常只记录稳定类别，不保存异常原文或隐藏推理。不要把本地数据库提交到 Git。

接入真实产品前，由 TypeScript 产品层认证并绑定 actor/tenant/capabilities，提供审批交互、事实读写和幂等查询。不要把 CLI 的固定演示身份当作线上认证。本段仅描述 Phase 0 演示。后续已增加知识检索、真实模型适配和本地脱敏查看；生产事件存储、OTEL 网络导出与多 Agent 执行仍待完成。

实现依据：[Phase 0 路线图](../../docs/architecture/implementation-roadmap.md)、[Runtime 设计](../../docs/architecture/agent-runtime.md)。契约校验采用 [Pydantic Models](https://docs.pydantic.dev/latest/concepts/models/)，异步执行使用 [Python asyncio](https://docs.python.org/3/library/asyncio-task.html)。

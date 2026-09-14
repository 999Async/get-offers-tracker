# Phase 4 首个切片：岗位助手评测与审核闭环

初版日期：2026-09-10。初版验证时真实模型未配置。2026-09-13 已接入本机 Codex 并完成一条合成用例真实模型冒烟，审核结果也已接入设置页；见[最新验证](phase4-review-and-codex.md)。**这不代表 Phase 3 质量验收或完整 Phase 4 已完成。**

## 本次完成

岗位助手沿用同一个 ReAct Runtime、工具策略、知识库解析/事实审核和岗位索引。新增开发者本地命令，使用隔离的合成材料、修正事实与冻结 JD，生成可核对的执行报告与审核表。

- `run`：逐用例执行，记录输入/数据集/代码/依赖/工作流/模型配置身份、模型和工具耗时、Token、计算费用、失败原因与完整事件。
- `replay`：检查报告、结果、Trace 哈希与事件序列，查看该用例的工具步骤和检查结果；不再调用模型或工具。
- `review`：读取人工填写的 CSV，绑定原始回答，拒绝缺行、重复行、改过的输入/回答/引用和不合法标签。原报告保持不变，回填结果写入新文件。
- `compare`：对同一数据集、用例和输入做逐例比较，展示自动检查、耗时、Token、费用差异。可附两份审核 CSV，比较已完成配对的人工评分；pending 和 n/a 不进入分母。
- `check`：兼容 API 模式只检查本地配置，不发起网络请求；`--provider codex` 检查本机账号、可用模型和 CLI 版本，不执行推理。两者均不打印凭据。

初版没有修改普通用户页面。完整 Trace 和评测正文通过本地开发者命令访问，输出目录 0700，报告/CSV/Trace 文件 0600；后续本机设置页仅展示脱敏投影。服务端聊天仍使用内存事件和脱敏审计；只有显式本地评测收集完整合成 Trace。没有接入生产材料或自动投递。

## 固定用例与评测边界

数据集：[assistant-synthetic-v1](../../datasets/evals/assistant-v1/synthetic.json)。8 条开发用例覆盖项目梳理、JD 简历调整、JD 面试准备、北京城市条件、缺材料、缺 JD、用户修正事实、来源中的越权指令。额外隔离账号中的标记文本用于检测数据是否越过账号边界。

自动检查包括：最终结果通过服务校验、必要/禁止工具、只读工具范围、产物类型、引用存在、岗位城市、特定禁止片段和隔离账号标记。字面片段检查仅用于已知回归，不能证明语义事实正确。运行失败仍占用例分母，不按成功子集计算通过率。

用例与审核要求由开发阶段编写，标记为 `pending_human_review`；并非人工标注的 Core/Lockbox 集。`scripted` 模式仅验证评测管道，生成脚本化回复，Token 为无模型推理的 0，费用为空；不代表 AI 回答质量。`live` 使用实际模型适配器，缺配置时退出，**不会退回 scripted**。

所有结果保留 `quality_claim=false`、`production_release=not_evaluated`。人工回填完成只意味着这批合成结果被审核，不触发发布或配置切换。审核员姓名由本地操作者填写，尚未接入企业身份认证与审批审计。

## 离线运行与回放

在项目根目录使用现有 Python 虚拟环境。每次指定新目录，已存在的输出不能覆盖：

```bash
npm run assistant:eval -- run --mode scripted --out .agent-data/assistant-eval/check-001
npm run assistant:eval -- replay --report .agent-data/assistant-eval/check-001/report.json --case resume
```

输出包含 `report.json`、`review.csv`、`traces/<case_id>.json`。请保留完整目录；读取报告时也会检查引用的 Trace。报告记录模型/工具组件时间与完整步骤，病例中的原始请求和最终回答位于本地 Trace/审核表。

完整事件用于“查看当时发生了什么”；`run` 才会再次执行。重新调用模型可能产生不同答案，不保证字节级复现。每条用例当前仅采样一次，p50/p95 是描述统计，不能据此判断显著提升或生产延迟。

## 真实模型配置与运行

本机 Codex 可使用 `npm run assistant:eval -- run --provider codex --limit 1 --out .agent-data/assistant-eval/codex-smoke-001`，无需下述 API 密钥配置。模型选择、账号检查和费用边界见[Codex 评测说明](phase4-review-and-codex.md#使用)。以下为兼容 API 模式。

复制 [配置模板](../../services/agent/assistant.env.example) 到项目根目录 `.env.assistant`，填写服务地址、模型名和密钥。该文件被 Git 忽略；解析器只读取限定的 LLM 变量，不执行 shell、不展开变量。费用单价未知时保持空白。

```bash
npm run assistant:eval -- check --env-file .env.assistant
npm run assistant:eval -- run --mode live --env-file .env.assistant --limit 1 --out .agent-data/assistant-eval/live-smoke-001
npm run assistant:eval -- run --mode live --env-file .env.assistant --out .agent-data/assistant-eval/live-baseline-001
```

先用 1 条用例确认模型支持工具调用、JSON 最终输出和 usage 字段，再跑全部用例。单用例沿用最多 8 步和 5 分钟截止时间。执行顺序为串行。支持的配置键：

| 键 | 用途 |
| --- | --- |
| `LLM_BASE_URL` | 模型服务地址，使用当前 Chat Completions 兼容适配器 |
| `LLM_MODEL` / `LLM_API_KEY` | 模型名称与密钥，缺任何一项不能运行 |
| `LLM_MAX_OUTPUT_TOKENS` | 单次输出上限，默认 3000 |
| `LLM_INPUT_PRICE_PER_MILLION` / `LLM_OUTPUT_PRICE_PER_MILLION` | 可选美元单价；两项齐全才计算费用 |

Token 来自供应商 usage；费用为 Token 乘配置单价的计算值，不是供应商账单，未细分缓存等优惠。usage 不完整时保留未知，不能显示为零。`check` 只做配置检查，不验证连接、余额或模型能力。

助手服务也支持 `npm run assistant -- --env-file .env.assistant`。该文件只装模型配置，Knowledge/Search/Assistant 服务密钥继续按既有环境变量注入；不在本次评测中启动产品网关。

## 人工审核

`review.csv` 使用 UTF-8 BOM、标准 CSV 引号与换行，可由 Excel/WPS 打开。模型输出等文本单元格会进行公式前缀防护。前 10 列是冻结的输入/输出/校验依据，只填写最后 5 列：

| 列 | 填写要求 |
| --- | --- |
| `fact_support` | pass / fail / pending；确实不涉及事实可 n/a，但要求引用的用例不能跳过 |
| `usefulness` | pass / fail / pending；不能 n/a |
| `jd_fit` | pass / fail / pending；无 JD 的用例可 n/a |
| `reviewer` | 记录实际审核者；填写 pass/fail 后必填 |
| `notes` | 失败依据或保留意见；有 fail 时必填 |

保留 pending 表示尚未核实，不等价于 fail，也不能混入已审核指标。另存审核 CSV 后执行：

```bash
npm run assistant:eval -- review --report .agent-data/assistant-eval/live-baseline-001/report.json --csv .agent-data/assistant-eval/live-baseline-001/reviewed.csv --out .agent-data/assistant-eval/baseline-review-001.json
```

设置页会直接读取报告同目录的 `reviewed.csv`，无需先生成审核 JSON。它与 CLI 共用来源校验逻辑，原报告和 Trace 不变；刷新时重新验证。详见[页面审核流程](phase4-review-and-codex.md#把审核表接入页面)。

## 配对比较

两组必须使用相同数据集、评分器、依赖版本、检索模式、执行模式、完整用例集合与输入哈希；不允许把单条 smoke 和全量运行、scripted 和 live 混配。模型、代码、工作流变化会列入 `changed_factors`，应一次只改变一个因素。依赖变更暂时不作为可配对实验。

```bash
npm run assistant:eval -- compare --baseline .agent-data/assistant-eval/live-baseline-001/report.json --challenger .agent-data/assistant-eval/live-challenger-001/report.json --baseline-csv .agent-data/assistant-eval/live-baseline-001/reviewed.csv --challenger-csv .agent-data/assistant-eval/live-challenger-001/reviewed.csv --out .agent-data/assistant-eval/comparison-001.json
```

两份审核 CSV 可一起省略，此时只比较自动检查和资源指标。人工评分按同一 case 配对，仅两边都是 pass/fail 才进入该维度的比较；报告同时列出配对数量与被排除数量。没有有效配对时差值为空。

## 验证及未完成项

全量 Python 回归 201 passed、3 skipped；随后补充配对人工评分回归，助手专项覆盖 50 项 Python 用例与 4 项产品 API 测试。覆盖真实本地知识库/索引、报告不可覆盖、Trace 篡改、审核错配、CSV 编码与公式前缀、失败分母、未知用量、配置文件不执行命令、无模型配置不伪造运行。

初版离线完整运行与重复运行各 8/8 自动契约检查通过；未填写的审核回读保持 pending。初版运行证据摘要见 [phase4-assistant-eval.json](phase4-assistant-eval.json)；当时没有真实模型耗时/费用/质量结果。最新真实模型冒烟和回归结果以[2026-09-13 报告](phase4-review-and-codex.md)为准。

后续仍需：真实模型基线、经人工复核的真实工作流、既定质量阈值与多次采样；生产登录端到端验收；D1/R2 事件适配、权限化受限 Trace 访问、保留/删除策略和部署。本机 Runs/Evaluation 页面及审核绑定已实现，仍不打开多 Agent 或自动发布。

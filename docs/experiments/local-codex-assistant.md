# 本机 Codex 岗位助手

日期：2026-09-11。状态：真实 Codex 账号连接与无材料对话已通过浏览器验收；真实材料对话等待用户选择文件。未部署。

## 使用

从仓库根目录运行 `npm run assistant:local`，打开 `http://localhost:5178/` 后会默认连接本机已登录的 Codex；本机 CLI 需先完成 `codex login`。左侧选择“岗位助手”，输入栏的模型图标可展开列表并直接切换模型；设置页也可选择模型。

本次验证的 CLI 是 0.146.0，默认模型来自账号模型列表，实际调用使用 GPT-5.6-Sol。本地 CLI 调用远端模型，不是离线推理。模型名保存于被 Git 忽略的 `.agent-data/assistant/local-model.json`；不复制登录凭据，不接收浏览器传入的命令或密钥。

启动命令负责启动 Knowledge、Search、Assistant 和 Vite，沿用 `.agent-data` 本地数据，在 `.dev.vars` 中更新本地服务地址并保留已有令牌（缺失时生成）。Ctrl+C 关闭该命令启动的全部进程。它不运行数据库迁移、不启动 Career 审批服务、不做部署。已有本地数据库需完成项目迁移。端口为 8767、8766、8780、5178；同端口有服务时应先关闭旧服务。

## 链路

浏览器 → 开发环境账号适配器 → 原有产品 API → Python AssistantService / AgentRuntime → Codex CLI。

- 账号检查使用官方 `codex app-server` 的 `account/read` 和 `model/list`，连接时请求正常令牌刷新。没有读取或解码凭据文件，也没有模拟账号。
- 页面自动连接后创建随机 HttpOnly / SameSite=Strict 会话，八小时过期，服务重启失效。每三十秒重新检查 CLI 账号；账号变更或检查失败使会话失效。该模式仅用于受信任的单用户本机开发，不能作为互联网多用户认证服务。
- 本机账号使用独立 `codex-local:` 身份空间。材料与投递保存在本机，不自动合并到托管站点的账号数据。已有托管登录实现不变。
- Vite 适配器只在显式 `GETOFFERS_LOCAL_CODEX=1` 的开发模式启用，校验连接来自回环地址、Host 和写请求 Origin。清除浏览器自带的身份头，校验会话后同时重建标准头与 Cloudflare 所读取的原始头。
- 模型推理使用 `codex exec --ignore-user-config --ephemeral --sandbox read-only --json --output-schema`，参数列表直接创建进程，不执行 shell 拼接。运行目录独立且临时，禁用 CLI 的 shell、插件、浏览器、记忆等功能；原生工具事件不被接受为结果。
- 每一步 CLI 只返回结构化工具决定或最终回答。读取所选材料、检索岗位、引用复核等继续由 Python Runtime 和 ToolPolicy 执行。没有改成把 CLI 的文件系统工具直接暴露给网页。
- 只渲染产品级进度和最终结构化回答，不渲染 CLI 内部推理或原始诊断。CLI 非致命警告与 `turn.failed` 区分处理，缺失最终结果/usage、失败、超时均不能伪装为回答。
- 取消请求会终止 CLI 进程组；每次模型调用有 100 秒本地超时。继承的环境变量使用允许列表，不传入产品服务令牌。Token 来自 CLI usage，费用未知；现有每轮步数、时长、累计 Token 和引用校验继续生效。CLI 模式没有承诺精确的供应商预付费 Token 上限。
- 2026-09-12 起聊天与草稿支持按账号保存、恢复和继续，详见 [历史对话](assistant-conversation-history.md)。Codex 内部推理与完整 Run Trace 的临时存储策略不变。

## 验证记录

- 62 项 Python 回归通过：原有助手与评测、真实账号会话的伪造/过期/断开/切换隔离、配置权限、CLI 失败与用量检查、取消后子进程清理。
- 9 项 Node 测试通过：产品 API 身份/流协议，以及开发适配器的身份头清洗、会话绑定、Host/Origin 检查和 Cookie 不回传到 JSON。
- 应用 TypeScript 检查、生产构建、Python Ruff 检查通过。
- 浏览器通过真实账号连接、模型列表显示、页面去掉未登录状态、输入并发送无材料问题、显示模型中文回复。验证问题：“我想梳理项目，但还没选择材料。请简短告诉我需要提供什么。”模型明确要求选择材料，没有伪造项目内容。
- **没有完成真实材料对话验收**：当前账号无已处理材料，已向用户请求指定文件。无材料连通结果不能视为 RAG 引用或简历质量验收。

参考：[Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)、[Codex App Server](https://learn.chatgpt.com/docs/app-server)。实现同时对照本机 CLI `--help` 和生成的协议 JSON Schema。

2026-09-12 UI 更新：模型菜单直接列出可用选项，勾选当前模型；移除断开按钮及账号说明。侧栏正常同步状态缩为头像旁状态点。自动连接复用并发请求、确认会话后通知页面刷新身份，失败时可手动重试。新增 4 项客户端连接测试，连同 5 项本机网关测试通过；浏览器已验证模型切换并恢复原选择。

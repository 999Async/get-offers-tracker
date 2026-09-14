# GetOffers

GetOffers 把求职过程中最容易散落的两件事放到一起：

- **投递进度管理**：记录岗位、笔试、面试、Offer 和下一步安排。
- **招聘表单助手**：把简历资料安全地复用到不同招聘网站，减少重复输入。

## 我只想马上使用

### 使用招聘表单助手（无需会代码）

下载并解压本项目，把 [browser-extension](browser-extension/) 文件夹加载到 Chrome 或 Edge，即可在招聘页面导入资料、预览并填写高置信度字段。扩展内置空白模板和 AI 生成提示词，可把 PDF/Word 简历快速转换为 profile.json。

完整的逐步安装方法、资料模板和常见问题见：[招聘表单助手使用说明](browser-extension/README.md)。

它不会自动提交、勾选协议、发送验证码或上传附件；最终内容始终由你复核并提交。

### 使用投递进度管理

项目界面支持：

- 投递记录的列表与看板视图。
- 笔试、一面、二面、三面、HR 面和 Offer 流程时间线。
- 从时间线自动生成首页安排与日历事件。
- 岗位搜索与投递计划。
- JSON 数据导入、导出和账号内多端同步。
- 桌面端与移动端布局。

当前 Web 版面向 OpenAI Sites / Cloudflare Workers 部署，投递记录写入绑定的 D1 数据库并按登录用户隔离。浏览器扩展完全独立，不部署 Web 版也能使用。

## Career Agent 升级设计

项目正在按“岗位检索 + 用户知识库 + 求职辅导 Agent + 评测与可观测闭环”的方向演进。Phase 0 已提供 Run Event 回放、有限步循环、工具策略、人工审批与本地评测。Phase 1 新增完整岗位版本、Qdrant 检索、BGE 模型适配、排序解释、原文证据和独立查询接口。Phase 2 已接入个人知识库页面，支持材料解析、版本、带引用检索、事实审核和可重试删除。Phase 3 已接通“选简历 → 查岗位 → 核对依据 → 确认加入待投递”的确定性闭环。另新增“岗位助手”，通过单 Agent ReAct 循环接入可配置的模型接口、材料检索和岗位工具，支持项目梳理、JD 简历草稿与面试准备。本机 Codex 已接入，支持模型切换与历史对话保存。Phase 4 新增设置页中的本机运行记录、评测结果与配对比较；正式质量验收仍需人工复核的真实工作流与生产环境验证。

- [Phase 0 本地运行与验收说明](services/agent/README.md)
- [Phase 1 岗位检索运行指南](services/agent/SEARCH.md)
- [Phase 1 验证范围与待办](docs/experiments/phase1-job-search.md)
- [Phase 2 知识库运行指南](services/agent/KNOWLEDGE.md)
- [Phase 2 评测与验收边界](docs/experiments/phase2-knowledge.md)
- [Phase 3 求职闭环、配置与验收边界](docs/experiments/phase3-career.md)
- [岗位助手 ReAct 实现、模型配置与验证边界](docs/architecture/assistant-react.md)
- [Phase 4 本地评测、审核与模型对比](docs/experiments/phase4-assistant-evaluation.md)
- [Phase 4 本机运行与评测查看](docs/experiments/phase4-developer-inspector.md)
- [Phase 4 审核结果查看与本机 Codex 评测](docs/experiments/phase4-review-and-codex.md)

- [总体系统设计](docs/architecture/system-design.md)
- [Agent Runtime](docs/architecture/agent-runtime.md)
- [岗位搜索与 RAG](docs/architecture/job-search-and-rag.md)
- [评测与可观测](docs/architecture/evaluation-and-observability.md)
- [安全与隐私](docs/architecture/security-and-privacy.md)
- [分阶段实施路线图](docs/architecture/implementation-roadmap.md)
- [架构决策记录](docs/adr/)

## 开发者本地运行

需要 Node.js 22.13 或更高版本。

    npm install
    npm run dev

常用检查：

    npm run lint
    npm run build
    npm test

Web 版的数据接口依赖：

- 名为 DB 的 Cloudflare D1 binding。
- OpenAI Sites 注入的 ChatGPT 登录用户请求头。
- 可选的 JOB_FEEDS R2 binding，用于岗位数据。

对应的部署绑定声明位于 [.openai/hosting.json](.openai/hosting.json)，数据库结构位于 [drizzle/](drizzle/)；扩展本身不需要这些服务。

## 数据与隐私

- Web 版投递记录保存在部署者配置的 D1 中，并按登录用户隔离。
- 设置页可以导出 JSON 备份，也可以把备份导入当前账号。
- 浏览器扩展的简历资料只保存在本机的 chrome.storage.local。
- 扩展只在用户点击时访问当前标签页，没有全站常驻读取权限。
- 不要把包含真实个人信息的资料 JSON 提交到 Git。

## 项目结构

    app/                 Web 界面与 API
    browser-extension/   可独立安装的招聘表单助手
    db/                  D1 数据访问与表结构
    docs/                Career Agent 架构与决策记录
    drizzle/             数据库迁移
    tests/               Web 端验证
    services/agent/      Python Agent Runtime 与本地验证
    datasets/evals/      版本化评测集
    worker/              Cloudflare Worker 入口

## 技术栈

- React 19
- TypeScript
- vinext / Vite
- Cloudflare Workers、D1、R2
- Chrome Extension Manifest V3

### 本机 Codex 岗位助手

运行 `npm run assistant:local`，在侧栏“岗位助手”连接已登录的本机 Codex 并选择模型。材料与投递使用本机账号空间，模型由 CLI 调用。[运行方式与验收边界](docs/experiments/local-codex-assistant.md)。

本机开发者可运行 `npm run assistant:developer`，在设置中查看脱敏运行记录和评测结果。普通启动默认不启用此入口。

评测可使用已登录的 Codex：`npm run assistant:eval -- run --provider codex --limit 1 --out .agent-data/assistant-eval/codex-smoke-001`。把实验目录内的 `review.csv` 另存为 `reviewed.csv` 并填写审核列后，页面可查看绑定的评分与配对差值。真实材料质量仍待人工验收。

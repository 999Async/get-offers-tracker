# Phase 2 本地知识库

这是可运行的本地工程基线。网页入口为主工作台侧栏“个人知识库”，内容在右侧区域切换，Python 服务入口 `getoffers-knowledge`；正式质量门禁和生产迁移尚未通过。材料检索与岗位检索分别建模、分别评测。

## 安装与运行

从仓库根目录执行：

```sh
npm run knowledge:setup
export AGENT_KNOWLEDGE_TOKEN="$(openssl rand -hex 32)"
npm run knowledge -- serve --port 8767
```

`knowledge:setup` 保留 neural、documents、r2 三组选装依赖。仅处理 Markdown/TXT 时可以使用基础安装；`knowledge` 使用 `--no-sync`，不会在启动时移除已安装的 PDF 或模型依赖。

在网页运行环境配置 `AGENT_KNOWLEDGE_URL=http://127.0.0.1:8767` 和同一 `AGENT_KNOWLEDGE_TOKEN`。本地 Cloudflare 开发环境从忽略提交的 `.dev.vars` 读取这两项，修改后重启 `npm run dev`。网页需要现有认证网关注入用户身份；不要把测试身份逻辑加入生产认证代码。部署环境需使用可达的 HTTPS 私有服务地址，本机回环地址只适用于本地开发。

默认数据库、对象和 Qdrant 均位于 `.agent-data/knowledge`。CLI 全局选项应放在 `serve` 或 `evaluate` 前：

```sh
npm run knowledge -- --neural --device mps serve --port 8767
```

启用神经检索使用 Phase 1 已固定版本的 BGE 模型，准备方法见 `SEARCH.md`。知识库页面不提供独立搜索入口；Python 检索接口可选择 lexical、dense、hybrid、hybrid-rerank。未配置模型时请求神经模式会报错，不会静默换成词法检索。

## PDF / DOCX

DOCX 使用真实 Docling 适配器。PDF 使用本地布局模型，首次使用前下载公开模型；解析用户文件时不下载模型：

```sh
services/agent/.venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
from getoffers_agent.knowledge.contracts import KnowledgeConfig
snapshot_download(
    "docling-project/docling-layout-heron",
    revision=KnowledgeConfig().pdf_layout_revision,
    cache_dir=".agent-data/docling-models",
    allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors"],
)
PY
```

可用绝对路径 `KNOWLEDGE_DOCLING_CACHE` 指定其他模型缓存。当前锁定 Docling 2.126.0，布局模型 revision 写入配置与解析身份。PDF OCR、表格结构识别、外部插件和远程服务均未启用：扫描件、复杂多栏及 PDF 表格不能视为已支持的质量范围。DOCX 表格和 Markdown 表格保留单元格；PDF 原生文本保留页码、边界框和 Docling source reference。

上传限制为 5 MiB、100 页、5,000 个节点。PDF/DOCX 子进程限制为 60 秒、1,536 MiB RSS，CPU 和输出文件也有限制。上传验证扩展名、MIME、文件签名、UTF-8、DOCX 压缩包展开量。解析关闭网络客户端连接并设置离线模式；这些应用级措施不等价于操作系统隔离，生产仍需独立容器、无网络策略及总租户配额。

## 数据与审核语义

Source Artifact 不可变；同一材料的新版本先完整解析和构建索引，成功后才原子切换活动版本。旧原文件仍可下载，但旧证据与旧确认事实退出检索和当前事实列表。解析失败可在版本列表重试。

Canonical Document 保存标题层级、段落、列表、表格、问答和来源位置。Evidence Unit 默认最多 800 UTF-8 字节；完整 Evidence Pack 的 JSON 字节数作为保守 token 上界，包含引用与定位元数据。引用打开时重新核验活动版本、内容哈希和原文区间。网页显示引用对应段落；PDF 可下载原文件核对页码，目前没有 PDF 页面高亮阅读器。

Candidate Fact 是原文摘录提案。`proposed`、`rejected` 不进入 `confirmed_only`；用户确认或修正之后才返回。审核保存修订号和历史记录，过期修订被拒绝。用户修正表示用户声明，不能被解释为原文逐字支持。当前没有生成式事实抽取，也未把事实自动接入岗位硬条件；该接线属于下一步 Career Agent 集成。

浏览器只传 action/payload，Product Port 从认证上下文绑定 actor/tenant。后端使用服务令牌和细分能力检查；检索必须显式传入文档范围，Qdrant 注入 tenant 和许可 Evidence ID 过滤，返回结果再次核对权威事实。文档内容始终标记为不可信数据，不执行其中指令。

## 删除与存储边界

删除先将材料设为 deleting，使其退出查询、引用和事实读取，再清理：

1. 该租户全部历史 Qdrant 集合和含私人词汇的索引清单。
2. 该材料所有版本的 source/canonical 对象。
3. Evidence Units 与 Candidate Facts（包括审核历史）。
4. 用其余活动材料重建该租户索引，删除版本元数据并写入不含材料名称的完成标记。

任一步失败保留删除状态与错误阶段；页面“重试删除”和内部 `reconcile` 操作可恢复。全量清理租户索引期间，该租户其他材料检索可能暂不可用；其他租户不受影响。当前单进程服务通过进程/文件锁串行化索引写入与检索，尚无定时后台 reconciliation worker。

本地事实存储为 SQLite，`drizzle/0002_smiling_chamber.sql` 提供相同表结构并有迁移一致性测试。尚未接通远程 D1 事务适配器，也未执行生产迁移。`--r2` 可切换注入的 S3 兼容对象适配器，需配置 `KNOWLEDGE_R2_ENDPOINT`、`KNOWLEDGE_R2_BUCKET`、`KNOWLEDGE_R2_ACCESS_KEY_ID`、`KNOWLEDGE_R2_SECRET_ACCESS_KEY`，使用独立私有 bucket；此次未验证真实 R2。

知识库尚未接入 Run Trace、持久缓存和备份系统，当前删除覆盖上述活动存储，不包含外部备份或未来 trace 副本。接入这些系统前必须扩展删除覆盖与验证。

## 复现检查

```sh
services/agent/.venv/bin/pytest services/agent/tests -q
GETOFFERS_DOCUMENT_INTEGRATION=1 services/agent/.venv/bin/pytest services/agent/tests/test_document_integration.py -q
npm test
npm run knowledge -- evaluate --out docs/experiments/phase2-knowledge-lexical.json
npm run knowledge -- --neural --device mps evaluate --out docs/experiments/phase2-knowledge-neural.json
```

真实 Docling 检查使用合成 PDF/DOCX，不包含个人信息。受限 macOS 沙箱若禁止读取子进程 RSS，会阻止该检查；应在允许本地子进程监测的环境运行，不能取消资源限制来使测试通过。

评测详情见 `docs/experiments/phase2-knowledge.md`。发布前仍需 40–60 份许可使用且人工审核的 Parsing Gold、约 100 条人工审核检索问题、生产隔离与删除验证，以及确认事实到匹配的完整流程。

## 投递记录关联简历

投递表单的“简历文件”直接读取当前用户知识库的文件版本。用户明确选择文件作为本次投递简历；列表包括可访问的已上传文件，不根据文件名自动判断简历。原文件可用性不依赖解析成功。

记录保存 `resumeDocumentId`、`resumeVersionId` 和显示名称快照，下载仍经知识库的用户鉴权。上传新版本不会替换历史关联。保存或导入新关联时，服务端按认证用户核验文档与版本；客户端提供的文件名称不能覆盖服务端名称。历史文字名称保留为未关联文件，旧设置里的独立版本列表不再读写。

删除知识库材料后，投递记录及其名称快照保留，文件不再可下载；编辑记录时显示不可用，并可改选或取消关联。删除已被明确告知不连带删除投递记录。文件内容不会复制到投递表或 JSON 备份中，导入关联也不会恢复已删除文件。

部署此变更需先应用 `drizzle/0003_talented_toxin.sql`。本地已核验旧数据迁移、真实文件下载与固定版本关联；此次未执行生产数据库迁移。

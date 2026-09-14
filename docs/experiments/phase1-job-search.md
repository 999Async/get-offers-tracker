# Phase 1 Job Search 验证记录

日期：2026-09-06。状态：本地工程基线已实现；人工标签与质量发布门槛待完成。

## 本次实现

`services/agent/src/getoffers_agent/job_search/` 提供完整岗位的事实、检索与评测链路。岗位以内容版本保存，采集审计与当前状态分离；SQLite 本地适配与新增 D1 迁移采用同一表结构。旧 Feed 摘要保持兼容，缺少完整职责与要求的记录不会进入正式检索。

索引使用 Qdrant 独立版本 collection；BM25 sparse、BGE-M3 dense、RRF 与 BGE reranker 可以独立比较。检索前绑定身份和硬约束，召回后复核事实；排序给出原始分数、加权项和带来源身份的引用。纯语义召回的引用明确标为 context，不伪称字面命中。索引激活有 manifest 校验，alias 同步失败可修复，没有跨 D1/Qdrant 原子事务的假设。

产品层增加 `POST /api/job-search`，使用现有认证取得用户身份，再向 Python 只读查询接口发起服务端调用。浏览器不能注入 tenant、capabilities 或任意存储过滤器。当前未修改搜索界面、执行远程 D1 迁移或上线部署。

## 可复核结果

| 检查 | 结果 |
| --- | --- |
| Python Runtime、检索、评测及安全边界 | 72 项通过 |
| 真实 BGE-M3 与 reranker 集成回归 | 1 项通过，固定权重 SHA-256 校验、MPS、512 token |
| 产品测试（含新查询路由） | 12 项通过：原有 9 项、新路由 3 项；已纳入 `npm test` |
| 完整应用构建 | 通过，包含 `/api/job-search` 路由 |
| Ruff 校验与格式检查 | 通过 |
| 新 TypeScript 路由、D1 schema 与路由测试 ESLint | 通过 |
| D1 迁移与 SQLite schema 对齐 | 测试通过；不影响原 applications 表 |
| Python 真实 HTTP 请求 | 无凭证 401；合法请求 200，返回 3 个岗位 |
| Qdrant 1.19.1 独立服务 | 24 项检索/评测测试通过，包含租户过滤、停用、alias 恢复和损坏 manifest 拒绝 |
| 固定版真实 BGE reranker | MPS、512 token 上加载及正负岗位排序通过 |
| 官方语料词法基线 | 150 条执行完成；约束、停用版本和重复计数均为 0 |
| 真实四组成对评测 | 同一语料上的 150 × 4 次查询完成，四组安全计数均为 0 |

词法逐例报告：[phase1-official-lexical.json](phase1-official-lexical.json)。HTTP 记录：[phase1-http-smoke.json](phase1-http-smoke.json)。报告包含代码/依赖/语料/配置身份、候选版本、质量指标、阶段时延与资源统计。Phase 0 的报告保留原验证时的快照身份，不改写成当前依赖下的结果。

服务版本记录：[phase1-qdrant-service.json](phase1-qdrant-service.json)。Docker Hub 直连超时，本次通过镜像源拉取同版本并记录 digest，服务绑定在 `127.0.0.1:6336`。真实重排记录：[phase1-reranker-smoke.json](phase1-reranker-smoke.json)，权重与固定 revision 的官方 SHA-256 一致；该两岗位对照只验证模型执行与方向，不代表基准质量。

验收结束后已停止临时容器；数据和镜像保留。本机可用 `docker start getoffers-phase1-qdrant` 恢复该实例。普通本地模式不需要容器。

本次真实模型测试设备为 Apple M5、16 GiB 内存，使用 MPS、512 token 截断、batch size 4。语料只有 30 个完整岗位，时延来自一次本地开发会话的顺序运行；没有重复运行置信区间，查询时延不包含模型加载和权重下载。返回的岗位事实仍保留全文。

### 四组结果：仅针对未审核草稿

| 配置 | MRR | nDCG@10 | p50 | p95 |
| --- | ---: | ---: | ---: | ---: |
| BM25 词法 | 0.9475 | 0.9608 | 17.4 ms | 34.8 ms |
| BGE-M3 向量 | 0.8748 | 0.8913 | 46.8 ms | 131.8 ms |
| BM25 + 向量 + RRF | 0.9251 | 0.9440 | 60.2 ms | 79.2 ms |
| 混合召回 + BGE reranker | 0.9387 | 0.9544 | 5428.2 ms | 8069.3 ms |

完整证据：[phase1-official-neural-paired.json](phase1-official-neural-paired.json)。索引构建约 5.46 秒，报告的进程峰值 RSS 约 1.10 GiB；该 RSS **不包括完整 GPU/Metal 内存占用**。本地计算费用未定价。

按当前草拟标签，重排相对词法的 nDCG@10 有 6 条改善、8 条下降、136 条相同。这份语料的复制式查询偏向词法匹配，未判断的候选也不是已确认负例，因此不能据此判断真实业务中的模型优劣。重排时延是本次实际观测，当前产品查询默认仍为词法模式。

[逐例复核表](phase1-case-review.csv) 包含 150 条查询、四组前五名的岗位名称与版本 ID、标签提议、配对差值和审核栏，按原草稿差值排序。审核栏现已填入 [AI 全量复核](phase1-label-review.md)：134 条完成全部 30 岗位评分，16 条待确认；原排名和差值仍是历史草稿结果。该表没有把自动生成结果标记为人工审核。

与本次四组实验配置一致的运行方式（先启动专用 Qdrant 服务）：

```sh
uv run --project services/agent --locked --extra neural getoffers-search \
  --data-dir .agent-data/reproduce-phase1 \
  --qdrant-url http://127.0.0.1:6336 --device mps --max-length 512 \
  evaluate datasets/evals/job-search-v1/official-draft.json --neural \
  --out .agent-data/reproduce-phase1.json
```

## 数据与质量边界

冻结的 Figure AI 官方 Greenhouse 响应包含 112 个岗位，结构解析得到 93 个具有职责与要求的岗位，本次选择 30 个完整岗位组成开发语料。150 条查询与标签均为 machine-proposed；部分查询直接复用岗位原文，每条只提出一个正例，其余结果尚未判定相关性。因此词法高分不能解释为实际求职推荐质量，也不能据此选择最终模型。

原始公开响应、哈希、完整岗位、版本标签和人工审核 CSV 均保存在 [数据集目录](../../datasets/evals/job-search-v1/README.md)。单公司、主要英文的语料不代表中文校招；正式评测需要跨公司岗位、真实用户查询、负向职责案例、多相关岗位分级标签与人工审核。

所有当前报告的 `reviewed_dataset_ready=false`、`production_release_ready=false`；本地计算费用为未定价，RSS 仅代表进程内存，不能推算云端价格或 GPU 总内存。Qdrant local mode 的小语料时延也不能外推为线上大规模 ANN 性能。

## 运行与后续验收

可直接按 [运行指南](../../services/agent/SEARCH.md) 导入快照、建索引、查询、运行成对评测或启动本地产品接口。仍需完成真实标签审核、校准质量与资源阈值，再接入产品界面及受保护的部署适配。当前工程实现不代表这些质量和上线事项已经完成。

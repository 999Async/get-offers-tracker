# Phase 1 — Job Search

岗位搜索返回完整 Job Version，并附排序因子和原文证据。它与后续按段落检索的 Knowledge Retrieval 保持独立。

## 本地运行

从仓库根目录运行。默认使用 Qdrant 客户端的本地持久化模式，无需 Docker 或模型密钥。

```sh
npm run agent:setup

# 导入随仓库提供的官方 JD 历史快照
npm run search -- ingest datasets/evals/job-search-v1/official-draft.json

# 建立并激活只含完整 JD 的 BM25 索引
npm run search -- build --source-kind public-official

npm run search -- search "robot learning" --top-k 5
npm run search -- search "Python Agent" --city 深圳 --exclude "Java backend"
```

示例官方语料来自美国 Figure AI；其城市字段没有深圳，第二个查询应返回空结果。空结果是硬约束生效，不能通过放松用户约束补满结果。

可用 `--data-dir PATH` 在子命令前选择目录。原 `/api/jobs` Feed 仍可用：导出的 JSON 用 `ingest FILE --format legacy-feed` 导入后标为 `summary`，有完整职责与要求前不会进入 Job Search。JSON 完整岗位导入契约见 `JobInput`；Greenhouse 源也支持 `ingest FILE --format greenhouse --board figureai --company 'Figure AI' --observed-at ISO_TIME`。

## 事实与索引

- D1 迁移：`drizzle/0001_white_cannonball.sql`；Drizzle 类型在 `db/schema.ts`。
- 本地 SQLite 使用同一表结构，测试验证新表与迁移一致并保留已有 applications 表。
- `job_sources` 与不可变 `job_versions` 保存事实；`job_current` 保存当前有效版本与最近观测时间。
- 内容变化产生新版本；重复导入同一内容不会新增版本；旧时间的采集不能覆盖新状态；同一时间相互冲突的内容会拒绝并回滚整批。
- Corpus Snapshot 固定版本集合与观测时间；索引有 `building`、`validated`、`failed` 状态和可复查 manifest。
- 新索引创建独立 Qdrant collection，验证完整 ID 集合后才能激活。事实库的 active pointer 是查询依据，查询直接使用物理 collection 名。
- Qdrant alias 是可修复投影。跨 SQLite/D1 和 Qdrant 没有分布式事务；alias 同步失败不使查询转向错误集合，可运行 `repair-alias`。
- `activate INDEX_ID` 支持切换/回滚到仍通过验证、且未包含停用版本的索引。旧/停用版本会在召回前与返回前再次检查。

## 检索与解释

当前实现：

```text
受信任的身份/能力 → 解析查询中的城市条件，与显式 Hard Constraints 合并
→ 从事实确定允许检索的 Job Version 集合
→ Qdrant BM25 sparse / BGE-M3 dense
→ RRF 合并
→ 可选 BGE reranker
→ 职责/要求匹配、负向职责、时效、来源质量与偏好加权
→ 去重与公司多样性限制
→ 事实复核
→ 完整 Ranked Jobs + Job Evidence
```

BM25 使用显式版本化的词频、长度归一化和冻结语料 IDF，在 Qdrant 中以 sparse vectors 检索。英文按词处理，中文采用字符二元组；这不是 BGE-M3 learned sparse，也没有隐式启用 Qdrant Cloud Inference。`k1`、`b`、分词版本、RRF 参数和特征权重均进入配置身份。

请求不接受 tenant、能力或任意 Qdrant filter。服务从已认证的产品调用取得身份，注入租户/可见性过滤，并以事实库复核。缺失城市、超期、未来观测时间、停用/旧版本、摘要记录和违反显式排除条件的岗位均被排除。偏好只调整分数；不会覆盖硬约束。

城市解析 `city-intent-v1` 在四种检索方式的召回前统一执行。支持 `在深圳找算法工作`、`深圳或北京的岗位`、`jobs in Fontana` 和标题中的 `— Fontana, CA (Customer Site)`；城市名称来自当前用户可见的索引事实、常用中文城市词表及完整 `City, ST` 表达。英文大小写、中文“市”后缀、带州名城市的简称会映射到事实值。已识别的城市没有匹配岗位时返回空结果。

`不要深圳` / `not in Fontana` 写入 `excluded_cities`；多城市为任选其一，排除条件累积。与显式 `hard_constraints.cities` 同时存在时取交集，冲突返回无效请求，不会清空条件后跨城市补结果。`深圳优先` / `preferably in Fontana` 不会变成硬筛选；这版尚不把自然语言偏好转换成排序权重，排序偏好仍由 `soft_preferences` 显式传入。公司/大学名称、客户地点和出差地点不按支持的求职地点表达处理。

这是有边界的规则解析，不是通用地名识别。未覆盖的地名、别名及复杂句式仍应通过 `--city` 或 `hard_constraints.cities` 指定。结果和新评测逐例记录 `effective_hard_constraints`、`city_constraint_matches` 和 `constraint_parser_version`；评测按生效条件检查违规。审核时应同时检查解析是否正确，不能仅凭违规计数为零认定所有自然语言要求都已覆盖。

`score_components` 分开提供原始 BM25/dense/RRF 分数、reranker 与实际加权项。Job Evidence 保留原文、字段、条目位置、Job Version ID、源 URL 和 Source Artifact 哈希。`match_type=lexical` 表示字面命中；纯语义召回提供 `context` 原文引用，不伪称字面命中。源文本始终作为数据处理。

## 真实 BGE 模型

可选依赖与普通 Runtime 分开安装：

```sh
npm run search:setup:neural
```

模型身份固定为：

| 模型 | revision |
| --- | --- |
| `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` |
| `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |

下载到 `.agent-data/models` 后，适配器以 `local_files_only=True` 加载；缺少权重会明确失败，不用假向量代替。测试用的确定性向量与 reranker 只存在于测试模块。

以下下载命令可能需要数 GB 磁盘和较长网络等待：

```sh
HF_HUB_DISABLE_XET=1 uv run --project services/agent --locked --extra neural python - <<'PY'
from huggingface_hub import snapshot_download
models = {
    'BAAI/bge-m3': '5617a9f61b028005a4858fdac845db406aefb181',
    'BAAI/bge-reranker-v2-m3': '953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e',
}
for name, revision in models.items():
    snapshot_download(name, revision=revision, cache_dir='.agent-data/models',
        allow_patterns=['pytorch_model.bin', 'model.safetensors', '*.json',
                        'tokenizer.*', 'sentencepiece.bpe.model', '*.txt'])
PY

uv run --project services/agent --locked --extra neural getoffers-search build --neural
uv run --project services/agent --locked --extra neural getoffers-search \
  search "robot learning" --mode hybrid-rerank
```

默认设备为 CPU、截断长度 1024；在支持的机器上可在子命令前传 `--device mps` 或 `--device cuda`，也可显式修改 `--max-length`。设备、截断、归一化与模型 revision 共同构成 encoder 身份；查询配置必须与索引一致。截断影响长 JD 的排序，但返回的 Job Version 保留全文。

## 成对评测

```sh
# 词法基线，独立目录
npm run search -- --data-dir .agent-data/eval-lexical evaluate \
  datasets/evals/job-search-v1/official-draft.json \
  --out .agent-data/lexical-report.json

# 同一冻结语料、请求与标签上的四组对照
uv run --project services/agent --locked --extra neural getoffers-search \
  --data-dir .agent-data/eval-neural --device mps evaluate \
  datasets/evals/job-search-v1/official-draft.json --neural \
  --out .agent-data/neural-report.json
```

报告包含 Recall/Precision@K、MRR、nDCG、约束/过期/重复计数、公司多样性、各阶段时延、p50/p95、建索引时长、进程峰值内存、代码/依赖/语料/模型/配置身份和逐例配对差值。本地推理费用标为未定价，不能称为零成本。当前草稿中未判断的结果数可由 `result_count - judged_result_count` 得到；不可当成已确认负例。

`safety_passed` 只说明已执行的边界检查通过，退出码 0 也不代表生产发布通过。官方草稿的 `reviewed_dataset_ready` 与 `production_release_ready` 仍为 false。需要人工评审标签、增加真实查询与跨公司语料，再确定质量/资源阈值。

## 产品查询接口

`POST /api/job-search` 通过现有 ChatGPT 产品认证取得 userId，绑定 actor/tenant，再调用 Python `/search`。它不会转发浏览器提供的身份或权限。未配置时返回 503，不影响原 `/api/jobs`。

本地启动 Python 查询接口：

```sh
# 在本机环境设置一个至少 32 字符的 AGENT_SEARCH_TOKEN
uv run --project services/agent --locked getoffers-search serve --port 8766
```

产品层配置 `AGENT_SEARCH_URL` 与同一 `AGENT_SEARCH_TOKEN`。服务只监听 loopback；公网部署需要生产服务器和受保护传输。默认端口已占用时指定其他端口。当前未接入 Web 搜索界面，也未执行远程 D1 迁移或线上部署。

可选 Qdrant 服务模式：`docker compose -f services/agent/compose.yaml up -d`，然后给 CLI 传 `--qdrant-url http://127.0.0.1:6336`。使用独立 data directory；不要用 Qdrant local mode 的时延推断服务模式或大规模 ANN 性能。

验证命令（服务模式测试应指向专用测试实例）：

```sh
npm run agent:test
npm run agent:check

GETOFFERS_TEST_QDRANT_URL=http://127.0.0.1:6336 \
  uv run --project services/agent --locked pytest \
  services/agent/tests/test_job_search.py services/agent/tests/test_job_evaluation.py

GETOFFERS_NEURAL_INTEGRATION=1 GETOFFERS_NEURAL_DEVICE=mps \
  uv run --project services/agent --locked --extra neural pytest \
  services/agent/tests/test_neural_search.py
```

普通测试使用确定性测试向量；真实模型测试需要显式启用。服务模式测试只清理本次测试创建的 collection，并恢复此前的 active alias。

参考：[Qdrant 向量与索引](https://qdrant.tech/documentation/manage-data/indexing/)、[BGE-M3](https://huggingface.co/BAAI/bge-m3)、[BGE reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3)、[D1 migrations](https://developers.cloudflare.com/d1/reference/migrations/)。

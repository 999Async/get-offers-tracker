# Job Search v2：AI 全量复核实验

本版本审核了原始 150 条查询和冻结的 30 个完整 JD。134 条可判定查询进入四组实验，每条都对全部 30 个 Job Version 明确给出 0–3 分；16 条需求不明确的查询保留待确认，不进入指标分母。全表共 4,500 行，其中 4,020 行已评分，480 行保持空分。

这是 **Codex 的 AI 复核，不是人工金标**。数据集仍使用 `review_status="machine-proposed"`，`reviewer` 为 `Codex (AI review; not human)`；人工审核和上线门槛均保持未通过。这里的 Recall 仅表示冻结 30 岗位语料内、按本次 AI 判断得到的召回率。

## 文件

- `official-ai-reviewed.json`：最终冻结版本 `job-search-v2-ai-review-2026-09-06-r2`，保留原查询、请求、岗位全文与 as_of，仅改变标签、审核身份和实验入选集合。
- `label-review.csv`：完整 4,500 对，UTF-8 BOM；`reviewed_grade` 空白代表待确认，绝不当作 0。与 v1 目录下用户指定的审核表内容一致。
- `adjudications.json`：逐查询需求解释、待确认原因、约束检查与全量标签。
- `pending-queries.json`：16 条待确认查询的原文、请求与原因。
- `review-packet.json`：去掉模型名称、排名和原标签的查询与完整 JD，供下一位审核者独立评分。
- `review-manifest.json`：输入输出哈希、覆盖统计、审核身份及盲审边界。
- `build_review.py`：本次明确判断的生成记录。正例是逐职责判断，不由检索模型、关键词匹配或排名产生；其他岗位明确按职责不符记 0。
- `execution-dataset.json`：模型运行开始时的中间标签版本。执行期间的最终边界复核撤销了 16 个弱正例；所有岗位、查询、请求和时点保持相同。
- `score_run.py`：验证上述检索输入一致后，对本次四组新产生的排名按最终标签重新计算指标。保留原始执行报告、模型身份与耗时，并记录再计分来源。
- `historical-label-effect.json`：另将历史排名按相同 134 条查询重放，隔离标签修改的影响；它不是新执行结果。

原始 `../job-search-v1/official-draft.json` 未改写。两份审核 CSV 修改前的原始副本保存在 `../../../docs/experiments/review-snapshots/`。

## 判定规则与查询问题

| 分数 | 规则 |
| --- | --- |
| 3 | 主要职责直接符合查询，并无明确硬约束冲突 |
| 2 | 明显相关，工作方向或职责范围部分不同 |
| 1 | 有具体工作内容重合，但仅为子环节或弱相关 |
| 0 | 无明确职责重合，或违反明确硬约束；公司背景、通用技能和关键词碰撞不能构成正例 |
| 空白 | 意图、硬要求含义或关键事实不足，待确认 |

1–3 分都会被当前指标计算为相关。评估不套用用户个人求职偏好，亦不根据候选人未提供的经历推断资格。

150 条结构化请求均未指定城市、招聘类型或排除条件。缺失条件按未限制处理，不擅自添加；`max_age_days=90` 保留，30 条冻结岗位在评估时点均满足。`official-17-1/4` 在查询文本中明确 Fontana，但结构化城市列表为空，标签按文本要求执行，其他城市记 0。当前程序的硬约束违规计数只检查结构化请求，不能将其为 0 解读为已验证自然语言约束解析。

学历、通用工程基础、体能、出差意愿和无方向的年限片段不反推原岗位。`Data Strategy Associate` 的标题未明确数据运营还是数据分析/策略研究，保留待确认。`100B+ / 100k+ GPU` 查询需确认规模数字是硬要求还是示意，其他岗位缺少这一规模证据，不用低分替代未知。

完全相同的请求必须有完全相同的标签。原表存在 7 组相同请求但正例不同的冲突；本次已统一。无城市限制的两个 Helix Data Creator 和两地 Commercial Site Deployment Engineer 可以同时为正例。最终 134 条中有 126 个完全不同的请求，且标题、职责与包装文本仍高度重复，不能视作 134 条独立真实用户需求。

有些结构化 `requirements` 实际收进了职责，例如 State Estimation 的新传感模态评估、Connector 的环境验证、Demand Planner 的良率需求信号。本次按完整 `description` 解释，保留源数据，不在标签审查中默默重写冻结 JD。

## 审核边界

初始化时已看到原报告和原标签，因此本次**不是严格盲审**。后续职责判断不参考检索分数；无排名的独立复核材料已保存。下一轮可以让独立审核者先读 `review-packet.json`，再与本次标签比对，不能把已有判断说成无先验影响的金标。

本次没有编造城市、排除条件或真实用户查询以补足 150 条，也没有将未确认项设为负例。原文复制偏差、单一公司、英文为主以及缺少真实排除条件仍然存在。正式人工 benchmark 应先澄清待确认需求、增加真实查询，再独立复核。

## 复现

```sh
services/agent/.venv/bin/python datasets/evals/job-search-v2-ai-review/build_review.py

services/agent/.venv/bin/python -m getoffers_agent.job_search.cli \
  --data-dir .agent-data/reproduce-ai-review \
  --device mps --max-length 512 \
  evaluate datasets/evals/job-search-v2-ai-review/official-ai-reviewed.json --neural \
  --out .agent-data/reproduce-ai-review.json
```

需要已有环境及缓存的固定版 BGE 模型。复现请使用新的独立目录和输出路径，不覆盖本次冻结报告。该命令直接以最终标签运行，无需中间版本再计分。

结果与判断见 [复核报告](../../../docs/experiments/phase1-label-review.md)。

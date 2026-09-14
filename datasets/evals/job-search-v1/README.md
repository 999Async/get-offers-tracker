# Job Search v1 — official-source draft

This directory contains a frozen **draft** retrieval dataset. It is not a reviewed relevance benchmark.

- Source: Figure AI's public Greenhouse recruitment API.
- The captured response contains 112 jobs; the structural parser identifies 93 with both responsibilities and requirements.
- Thirty distinct, section-complete jobs were selected, prioritizing AI/data/software roles and retaining other roles as distractors.
- Five seed queries per job produce 150 cases. Some queries directly reuse source wording. Each currently proposes one positive job label; unjudged jobs are **not confirmed negatives**.
- All labels are `machine-proposed`. No case has been marked human-reviewed by the implementation agent.
- This single-company, mostly English corpus validates the engineering path. It does not represent Chinese campus recruitment or establish production relevance quality.

`official-draft.json` contains normalized full text, source identity, capture time, hard constraints, preferences, immutable Job Version IDs and draft labels. `source-manifest.json` identifies the original capture and content hash. `sources/` preserves the public source bytes for re-parsing. The snapshot is historical; it does not claim these jobs remain open.

## Review workflow

审核 CSV 使用 **UTF-8 with BOM（UTF-8 签名）**，便于 Excel/WPS 打开时正确识别中文。编码修复后请重新打开文件；已经打开的窗口可能仍显示旧的解码结果。后续用 Python 读写这些审核 CSV 时使用 `encoding="utf-8-sig"` 和 `newline=""`，避免首列表头带入 BOM 或再次导出成无编码标记的文件。

如果 Excel 显示文本导入向导，使用 `Unicode (UTF-8)`、`分隔符号`、`逗号`；若提示将大数字转为科学表示法，选择 `请勿转换`，保留岗位版本标识。已用原生 Excel 验证：旧窗口的 B9 显示乱码，补上编码标记的同内容副本自动识别为 UTF-8，B9 正确显示“岗位职责匹配：”。编码修复当时两份文件各 150 行，所有单元格内容与修复前逐项一致；下述 AI 标签复核随后扩充了标签表。

The current `label-review.csv` has been expanded to 4,500 pairs by [the AI review experiment](../job-search-v2-ai-review/README.md): 4,020 scored pairs and 480 pending pairs. These are AI judgments, not human sign-off; the original draft JSON and pre-review CSV snapshots are preserved.

Start with `label-review.csv`. Fill the reviewed grade (0–3), reviewer identity and notes after checking the complete JD. Add other relevant/irrelevant Job Version IDs to a case when appropriate; a single proposed positive is not exhaustive annotation. Replace copy-heavy seed queries with realistic job-search needs and introduce explicit negative-role, location and recruitment-type cases.

Publish reviewed labels under a **new dataset version**, preserving the original draft. Set `review_status` to `human-reviewed` only for cases actually reviewed and include `reviewer`. The Runner refuses unknown Job Version IDs and duplicate case IDs. Its readiness check requires at least 150 reviewed cases; a reviewed count alone never establishes production release readiness, which also needs agreed quality/resource thresholds and broader coverage.

## Run

From the repository root:

```sh
npm run agent:setup
npm run search -- --data-dir .agent-data/search-eval evaluate \
  datasets/evals/job-search-v1/official-draft.json \
  --out .agent-data/search-eval-report.json
```

Use a dedicated evaluation data directory so unrelated jobs cannot contaminate the frozen corpus. See [the Search guide](../../../services/agent/SEARCH.md) for the real BGE ablations and service integration.

# knowledge-v1：合成工程评测集

`cases.json` 包含 12 份人工构造的 Markdown/TXT 文档和 24 个检索问题，没有真实个人信息。每条问题标记一个预期原文片段，由 Canonical Document / Evidence Unit 转换为稳定 Evidence ID。

这是工程冒烟数据，不是人工审核 Parsing Gold 或真实求职检索基准。问题通常重复原文词汇，难度很低；满分不能推断真实文档质量。不要将未审核标签计入正式质量门禁。

运行方法和限制见 `services/agent/KNOWLEDGE.md`。PDF/DOCX 的真实解析用独立集成测试验证，不计入这里的 12 份文档。已有 `job-search-v2-ai-review` 数据集保持原样。

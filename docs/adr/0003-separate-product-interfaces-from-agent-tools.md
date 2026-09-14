# Separate product interfaces from Agent tools

The TypeScript application owns authentication, user-facing workflows, Application Plans, and application facts, while the Python Agent Runtime owns orchestration, search, retrieval, evaluation, and Run Trace. Agent tools are policy-aware adapters over selected product interfaces rather than a one-to-one exposure of every product endpoint.

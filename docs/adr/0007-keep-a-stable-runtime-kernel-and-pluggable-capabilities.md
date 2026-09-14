# Keep a stable Runtime kernel and pluggable capabilities

The Agent Runtime kernel owns run and event semantics, tool registration, policy and approval, budgets, cancellation, checkpoints, and replay. Model providers, tool providers, retrievers, trace exporters, and framework adapters may plug into that kernel, while Job Search, tenant permissions, knowledge data, and evaluation records remain product-owned rather than plugin-private state.

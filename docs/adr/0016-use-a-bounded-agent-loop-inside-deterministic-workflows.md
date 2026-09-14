# Use a bounded Agent loop inside deterministic workflows

Workflow code controls task stages, model-visible tools, approval points, and termination conditions, while the model selects permitted tools and produces grounded reasoning within each stage. Every Agent Run has explicit step, deadline, token, cost, parallelism, cancellation, and no-progress limits so autonomous execution cannot become an unbounded loop.

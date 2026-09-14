# Use an append-only Run Event ledger

Every workflow records immutable lifecycle, model, retrieval, tool, approval, delegation, usage, and outcome events under the hierarchy `Session → WorkflowRun → AgentRun → Step`. Events use a versioned envelope with monotonic run sequence, causation and correlation identifiers, sensitivity classification, and typed payload; replayable state, Run Trace views, cost reports, and trajectory evaluations are derived from this ledger instead of relying on the final answer or mutable runtime state as the execution record.

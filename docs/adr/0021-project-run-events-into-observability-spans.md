# Project Run Events into observability spans

The append-only Run Event ledger remains the execution fact source, while OpenTelemetry and other observability spans are disposable projections for operational analysis. Loss or replacement of an observability backend cannot prevent a workflow from completing or remove the evidence required for replay and evaluation.

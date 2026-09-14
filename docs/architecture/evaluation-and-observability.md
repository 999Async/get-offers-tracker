# Evaluation and Observability

## Objective

Evaluation and observability form one closed loop:

```text
production or evaluation Run
→ append immutable events
→ project Run Trace and operational spans
→ calculate deterministic and model-based scores
→ classify Bad Cases
→ create reviewed Evaluation Cases
→ run paired Baseline/Challenger experiment
→ apply release gates
→ deploy, monitor, or roll back
```

Observability answers what happened. Evaluation judges whether it was good enough. Neither replaces the other.

## Event and span model

Run Events are the execution fact source. OpenTelemetry-compatible spans are derived operational views:

```text
Workflow span
├── Agent span
│   ├── Context assembly span
│   ├── Model span
│   ├── Job Search span
│   │   ├── BM25 span
│   │   ├── Dense span
│   │   ├── Fusion span
│   │   └── Rerank span
│   ├── Evidence Retrieval span
│   ├── Tool span
│   └── Approval span
└── Outcome span
```

An observability exporter may fail without blocking the workflow. A trace backend is not used to reconstruct approval state or repeat side effects.

## Storage and access

- In-memory Event Store: Runtime tests.
- SQLite Event Store: local reproducible development.
- D1 Event Store: deployed event envelopes, indexes, and low-sensitivity payloads.
- R2 Trace Payload Store: large restricted payload snapshots.
- OpenTelemetry exporter: redacted operational spans, logs, and metrics.

Ordinary users do not receive full Trace or Evaluation access. They see their own Decision Explanations, citations, document processing status, and approval history.

Suggested capabilities:

```text
explanation:read:self
trace:read:redacted
trace:read:restricted
metrics:read
evaluation:read
evaluation:run
evaluation:manage
```

Developer Operators receive redacted access by default. Restricted content access, if implemented, is time-limited, justified, and audited. Hidden model reasoning is not collected or exposed.

## Experiment identity

```python
class ExperimentConfig(BaseModel):
    experiment_id: str
    baseline_or_challenger: str
    dataset_version: str
    lockbox_version: str | None
    corpus_snapshot: str
    candidate_profile_version: str
    parser_version: str
    chunker_version: str
    search_config_version: str
    embedding_version: str
    reranker_version: str
    model_version: str
    prompt_version: str
    toolset_hash: str
    runtime_version: str
    grader_versions: dict[str, str]
    pricing_version: str
    random_seed: int | None
```

Paired experiments use the same Evaluation Case, source data, and scoring contract. A change to query instruction or vector dimension is a configuration change, not merely a model-name change.

## Evaluation datasets

### Core Set

Realistic tasks with human-reviewed labels. This is the primary quality source.

### Edge Set

Stale and duplicate jobs, conflicting Candidate Facts, missing evidence, negative constraints, cross-industry transfer, malformed documents, approval interruption, deletion, and prompt injection.

### Synthetic Set

Language variations, typographical errors, paraphrases, and adversarial inputs. Synthetic data expands coverage but does not replace reviewed Core or Lockbox cases.

### Frozen Lockbox

A stable subset excluded from everyday tuning. Access and repeated inspection are restricted so it remains a credible release signal.

## Grader hierarchy

### Deterministic graders

- Hard Constraint violation.
- Relevant Job Version hit.
- Recall@K, Precision@K, MRR, nDCG.
- Expected Evidence Unit hit.
- Citation identity and locator validity.
- Expected/forbidden tool and parameter checks.
- Approval and idempotency checks.
- Tenant isolation and prompt-injection authorization checks.
- Token, cost, latency, timeout, retry, and error calculations.

### Mixed rule/model graders

- Claim support by cited evidence.
- Completeness of key match and gap explanation.
- Unsupported conversion of tentative evidence into completed experience.
- Actionability and task relevance.

### Human calibration

Human reviewers sample model-graded results, record disagreement, measure consistency, and maintain Judge Bad Cases. The evaluated Agent is not the only judge of its own output. Grader prompts and models are versioned.

## Metric catalogue

### Ingestion and data quality

```text
capture_success_rate
parse_success_rate
field_completeness
freshness_lag_seconds
stale_job_rate
dedup_precision / dedup_recall
locator_coverage
semantic_unit_break_rate
cross_section_contamination_rate
```

### Job Search

```text
recall_at_20 / 50 / 100
precision_at_k
mrr
ndcg_at_5 / 10
hard_constraint_violation_rate
negative_role_intrusion_rate
stale_result_rate
duplicate_result_rate
result_diversity
```

### Evidence Retrieval and generation

```text
evidence_recall_at_k
evidence_mrr / ndcg
citation_coverage
citation_precision
claim_support_rate
unsupported_claim_rate
answer_relevance
evidence_completeness
```

### Agent and workflow

```text
workflow_success_rate
partial_completion_rate
tool_selection_accuracy
tool_argument_accuracy
invalid_action_rate
steps_per_run
no_progress_stop_rate
human_intervention_rate
approval_accept/edit/reject_rate
delegation_accuracy
duplicate_delegation_rate
```

### Reliability and performance

```text
error_rate
timeout_rate
retry_rate
resume_success_rate
e2e_duration_ms p50/p95/p99
ttft_ms p50/p95
intent_parse_ms
job_search_ms
bm25_ms / dense_ms / fusion_ms / rerank_ms
evidence_retrieval_ms
model_generation_ms
tool_wait_ms
approval_wait_ms
```

System-compute latency and end-to-end user waiting time are both retained. Human approval wait is excluded from compute p95 but included in user-perceived workflow duration.

### Usage and cost

```text
input_tokens
output_tokens
cached_input_tokens
reasoning_tokens
embedding_tokens
judge_tokens
model_cost
embedding_cost
rerank_compute_cost
evaluation_cost
cost_per_run
cost_per_successful_workflow
```

Every monetary value includes currency, provider, pricing version, and whether it is measured or estimated. Local models record machine identity, duration, throughput, and peak memory; they are not labelled zero-cost.

## Release gates

### Zero-tolerance gates

```text
cross_tenant_leak = 0
unapproved_write = 0
prompt_injection_privilege_escalation = 0
hard_constraint_violation = 0 on mandatory gate cases
```

### Quality and resource gates

Thresholds are set only after the first Baseline. A Challenger must meet the agreed non-regression floors for core retrieval and answer metrics, remain inside error/timeout budgets, and meet p95 and cost-per-success limits.

A gain in one headline metric cannot compensate for a safety regression. Results report distributions and confidence or paired differences where possible, not only averages.

## Champion-Challenger workflow

1. Register a Challenger with exactly identified changed factors.
2. Run fast development cases.
3. Run full paired Core and Edge cases.
4. Run frozen Lockbox at the release checkpoint.
5. Compare quality, safety, latency, cost, and failure categories.
6. Approve or reject the release with recorded gate evidence.
7. Deploy behind a reversible configuration or index alias.
8. Monitor drift and production Bad Cases.
9. Roll back when a release gate is violated.

## Multi-Agent evaluation

Multi-Agent experiments add three evaluation layers:

- Outcome: final job quality, evidence, constraints, and action correctness.
- Collaboration: whether delegation was justified, specialist selected correctly, input contract complete, output faithfully synthesized, and redundant delegation avoided.
- Resources: child count, tokens, cost, critical-path latency, timeout, cancellation, and partial failure.

The default remains single Agent until paired evaluation establishes a worthwhile gain.

## Developer UI

### Trace view

- Workflow/Agent/Step timeline.
- Search candidates and before/after reranking.
- Retrieval evidence and locators.
- Tool lifecycle and approval.
- Context Manifest identities.
- Tokens, cost, latency, retries, and stop reason.
- Sensitivity-aware redaction.

### Evaluation view

- Dataset and experiment versions.
- Baseline/Challenger paired differences.
- Metric distributions and gate status.
- Bad Case taxonomy and filters.
- Case-level side-by-side Trace.
- Current Champion and release history.

These routes and their backing interfaces enforce developer capabilities server-side. Hiding a navigation item is not authorization.

## Production feedback

Save, dismiss, Application Plan, submitted application, interview, and offer events are Feedback Signals, not immediate ground truth. They are used for analysis and sample discovery; they enter evaluation or training only after review and provenance recording.

## Primary references

- [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/)
- [Langfuse observability and evaluation](https://langfuse.com/docs)
- [Ragas metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
- [OpenAI agent evaluations](https://platform.openai.com/docs/guides/agent-evals)
- [OpenAI trace grading](https://platform.openai.com/docs/guides/trace-grading)

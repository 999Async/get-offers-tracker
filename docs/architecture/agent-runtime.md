# Agent Runtime

## Goal

The Agent Runtime is a small Python Harness built to make execution bounded, inspectable, replayable, and framework-independent. It borrows ideas rather than product code:

- Codex: explicit run/item lifecycle, tool registration, approval, and observe-first Run Trace.
- DeepSeek Harness: append-only Session Events, capability seams, reversible plugin lifecycle, and headless execution.
- nanobot: readable bounded Agent loop, hooks, tool registry, checkpoint, and explicit session identity.

GetOffers does not fork those applications and does not make their memory, UI, RAG, or evaluation models product dependencies.

## Public interface

```python
class AgentRuntime(Protocol):
    def run(self, request: RunRequest) -> AsyncIterator[RunEvent]: ...
    def resume(self, request: ResumeRequest) -> AsyncIterator[RunEvent]: ...
    def replay(self, workflow_run_id: str) -> RunProjection: ...
```

`run` and `resume` stream immutable facts. A final `WorkflowOutcome` is a projection over those facts, not a special untraced return path. `replay` never calls a model, tool, or external system.

## Run hierarchy

```text
Session
└── WorkflowRun
    ├── AgentRun: career_agent
    │   ├── Step
    │   │   ├── ModelCall
    │   │   ├── Retrieval
    │   │   └── ToolCall
    │   ├── Approval
    │   └── Delegation
    └── WorkflowOutcome
```

- `Session`: continuous user conversation.
- `WorkflowRun`: one bounded requested task.
- `AgentRun`: one Agent's participation in a workflow.
- `Step`: one model request and resulting tool activity before the next model request.
- `WorkflowOutcome`: terminal business result with status and evidence.

## Event envelope

```python
class RunEvent(BaseModel):
    event_id: UUID
    schema_version: int
    sequence: int
    occurred_at: datetime
    event_type: str
    session_id: UUID
    workflow_run_id: UUID
    agent_run_id: UUID | None
    parent_agent_run_id: UUID | None
    causation_id: UUID | None
    correlation_id: UUID
    sensitivity: Literal["operational", "restricted"]
    payload: dict[str, Any]
```

Invariants:

- `sequence` is monotonic within a Workflow Run.
- An appended event is immutable.
- Payload interpretation is controlled by `event_type` and `schema_version`.
- Parent/child execution is represented with identifiers, not inferred from text.
- Provider usage and configuration versions are recorded even on failure.
- Restricted payloads are referenced by opaque identity when not stored in the main event record.

## Initial event vocabulary

```text
workflow.started
workflow.completed
workflow.failed
workflow.cancelled

agent.started
agent.delegated
agent.completed
agent.failed

step.started
step.completed

context.assembled
model.requested
model.completed
model.failed

retrieval.requested
retrieval.completed
retrieval.failed

tool.requested
tool.rejected
tool.started
tool.completed
tool.failed

approval.requested
approval.granted
approval.rejected
approval.expired

checkpoint.created
budget.exhausted
```

The vocabulary should stay small. Domain modules may add typed payloads, but they must not create alternative lifecycle semantics.

## Bounded Agent loop

```text
assemble versioned context
→ request model
→ validate model output
→ execute permitted read tools or request approval
→ append results
→ stop, continue, wait, cancel, or fail
```

Each Agent Run includes:

```python
class RunBudget(BaseModel):
    max_steps: int
    deadline_at: datetime
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_cost: Decimal | None
    max_parallel_tools: int
    max_no_progress_steps: int
```

The Runtime owns budget enforcement and emits a precise stop reason. A model cannot extend its own budget or expose an additional tool.

## Context manifest

The Runtime assembles model-visible context in a fixed policy order:

1. Runtime policy.
2. Workflow instructions.
3. Current model-visible Tool Specs.
4. trusted Candidate Facts, Hard Constraints, and Application Facts.
5. explicitly marked untrusted Job/User Evidence.
6. bounded Session context and current request.

Every model call records a manifest containing policy, workflow prompt, toolset, user-state, corpus, evidence, summary, model, and tokenizer versions or hashes. Conversation may be compacted; authoritative facts and evidence are reloaded from their sources.

## Tool contract

```python
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    effect: Literal["read", "write", "external"]
    exposure: Literal["direct", "deferred", "hidden"]

class ToolHandler(Protocol):
    async def execute(self, context: ToolContext, arguments: dict) -> ToolResult: ...

class ToolPolicy(Protocol):
    async def authorize(self, context: ToolContext, request: ToolRequest) -> PolicyDecision: ...
```

The Registry maps a Tool Spec to a Handler and Policy. Runtime validation happens before Handler execution. Tool Policies bind tenant identity server-side, classify side effects, request approval, supply or validate idempotency, and create a redacted trace representation.

Tool exposure changes by workflow stage. The model never receives upload plumbing, trace persistence, index administration, or deletion internals as ordinary Career Agent tools.

## Approval protocol

```python
class PendingApproval(BaseModel):
    action_id: UUID
    user_id: str
    tool_name: str
    canonical_arguments: dict
    arguments_hash: str
    reason: str
    expires_at: datetime
    idempotency_key: str
```

Approval authorizes one exact canonical payload. Changing the job, resume version, note, user, tool, or any material argument invalidates it. `create_application_plan` is a write tool and always follows this protocol. Browser autofill remains user-initiated and is not executed by the Runtime.

## Event Store and checkpointing

```python
class EventStore(Protocol):
    async def append(self, events: Sequence[RunEvent]) -> None: ...
    async def read(self, workflow_run_id: UUID, after_sequence: int = 0) -> AsyncIterator[RunEvent]: ...
    async def list_runs(self, query: RunQuery) -> Page[RunSummary]: ...
```

Adapters:

- `InMemoryEventStore` for unit and contract tests.
- `SQLiteEventStore` for local reproducible runs.
- `D1EventStore` for deployed event envelopes and indexes.
- `R2TracePayloadStore` for large restricted payloads.

A checkpoint is a disposable projection created after a completed Step. State can always be rebuilt from events. Resume appends new events; it does not edit history. Replay does not repeat side effects. A deliberate re-execution creates a linked new Workflow Run.

## Provider interfaces

The initial real seams are:

```python
ModelProvider.complete(request) -> ModelResponse
EventStore.append/read/list_runs
ProductPort.get_candidate_state/create_application_plan
TraceExporter.export(spans)
```

Every seam has at least a production and test adapter. Internal algorithms should remain normal implementation details until two real alternatives exist.

## Multi-Agent extension

V1 records one Career Agent Run. The same event and budget model supports later delegation:

```text
agent.delegated
├── child AgentRun A
├── child AgentRun B
└── parent synthesis Step
```

Child Runs inherit explicit tenant, evidence scope, deadline, and budget. They are read-only by default. A parent must be able to cancel outstanding children and record partial failure. Handoff adds an `active_agent` projection but does not create a second authorization model.

## Observability rule

Run Events are the fact source. OpenTelemetry/Langfuse-style traces are projections for operations and analysis. Operational telemetry contains identifiers, versions, usage, latency, status, and redacted attributes; restricted payloads remain under product-controlled access and retention.

The Runtime records model requests and outputs needed for allowed debugging, tool and retrieval activity, and concise decision summaries. It does not attempt to collect or expose hidden model chain of thought.

## Reference implementations

- [OpenAI Codex App Server lifecycle](https://github.com/openai/codex/blob/076f17c114b0a82d7235552ccec5ff2d69f3266a/codex-rs/app-server/README.md)
- [OpenAI Codex rollout trace](https://github.com/openai/codex/blob/076f17c114b0a82d7235552ccec5ff2d69f3266a/codex-rs/rollout-trace/README.md)
- [DeepSeek Harness architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md)
- [nanobot architecture](https://github.com/HKUDS/nanobot/blob/649e3958c58bbf12342d2b254f3c40dea4d42f07/docs/architecture.md)

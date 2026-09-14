"""Typed event vocabulary and a pure, disposable checkpoint projection."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from getoffers_agent.domain.contracts import (
    ContextManifest,
    Contract,
    ErrorCategory,
    ModelRequest,
    ModelResponse,
    PendingApproval,
    RunRequest,
    RuntimeFault,
    Step,
    ToolCall,
    ToolResult,
    Usage,
    WorkflowOutcome,
    utcnow,
)


class Started(Contract):
    request: RunRequest
    config_hash: str
    initial_stage: str


class Empty(Contract):
    pass


class ContextAssembled(Contract):
    manifest: ContextManifest


class ModelRequested(Contract):
    request: ModelRequest


class ModelCompleted(Contract):
    response: ModelResponse
    duration_ms: float = Field(ge=0, allow_inf_nan=False)


class Failure(Contract):
    category: ErrorCategory
    duration_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    usage: Usage = Field(default_factory=lambda: Usage(source="unknown"))


class ToolRequested(Contract):
    call: ToolCall


class ToolStarted(Contract):
    call_id: UUID


class ToolCompleted(Contract):
    call_id: UUID
    result: ToolResult
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    reconciled: bool = False


class ApprovalRequested(Contract):
    approval: PendingApproval


class ApprovalResolved(Contract):
    action_id: UUID
    arguments_hash: str


class StepCompleted(Contract):
    step: Step
    next_stage: str
    progress_hash: str
    no_progress_steps: int = Field(ge=0)


class Checkpoint(Contract):
    through_sequence: int = Field(ge=1)


class Outcome(Contract):
    outcome: WorkflowOutcome


# The boolean marks restricted payloads. No free-form exception text is accepted.
VOCABULARY: dict[str, tuple[type[Contract], bool]] = {
    "workflow.started": (Started, True),
    "agent.started": (Empty, False),
    "step.started": (Step, True),
    "context.assembled": (ContextAssembled, True),
    "model.requested": (ModelRequested, True),
    "model.completed": (ModelCompleted, True),
    "model.failed": (Failure, False),
    "tool.requested": (ToolRequested, True),
    "tool.rejected": (Failure, False),
    "tool.started": (ToolStarted, False),
    "tool.completed": (ToolCompleted, True),
    "tool.failed": (Failure, False),
    "approval.requested": (ApprovalRequested, True),
    "approval.granted": (ApprovalResolved, False),
    "approval.rejected": (ApprovalResolved, False),
    "approval.expired": (ApprovalResolved, False),
    "step.completed": (StepCompleted, True),
    "checkpoint.created": (Checkpoint, False),
    "budget.exhausted": (Failure, False),
    "agent.completed": (Empty, False),
    "agent.failed": (Failure, False),
    "workflow.completed": (Outcome, True),
    "workflow.failed": (Outcome, True),
    "workflow.cancelled": (Outcome, True),
}


class RunEvent(Contract):
    event_id: UUID = Field(default_factory=uuid4)
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime = Field(default_factory=utcnow)
    event_type: str
    session_id: UUID
    workflow_run_id: UUID
    agent_run_id: UUID
    parent_agent_run_id: UUID | None = None
    causation_id: UUID | None = None
    correlation_id: UUID
    sensitivity: Literal["operational", "restricted"]
    payload: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_payload(self):
        if self.event_type not in VOCABULARY:
            raise ValueError("unknown event type")
        model, restricted = VOCABULARY[self.event_type]
        model.model_validate(self.payload)
        if self.sensitivity != ("restricted" if restricted else "operational"):
            raise ValueError("incorrect event sensitivity")
        return self


class RunProjection(Contract):
    request: RunRequest
    config_hash: str
    sequence: int
    stage: str
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: str = "0"
    usage_unknown: bool = False
    no_progress_steps: int = 0
    progress_hash: str = ""
    pending_call: ToolCall | None = None
    pending_approval: PendingApproval | None = None
    approval_granted: bool = False
    tool_started: bool = False
    completed_tool: ToolCompleted | None = None
    model_response: ModelResponse | None = None
    model_inflight: bool = False
    step_open: bool = False
    history: tuple[dict[str, JsonValue], ...] = ()
    outcome: WorkflowOutcome | None = None

    @property
    def status(self) -> str:
        if self.outcome:
            return "terminal"
        if self.pending_call and self.tool_started:
            return "awaiting_reconciliation"
        if self.pending_approval and not self.approval_granted:
            return "awaiting_approval"
        return "running"


def validate_sequence(events: list[RunEvent]) -> None:
    if not events or events[0].event_type != "workflow.started":
        raise RuntimeFault(ErrorCategory.INVALID_EVENTS)
    first = events[0]
    start = Started.model_validate(first.payload)
    if (
        start.request.workflow_run_id != first.workflow_run_id
        or start.request.session.session_id != first.session_id
        or start.request.agent_run_id != first.agent_run_id
        or start.request.parent_agent_run_id != first.parent_agent_run_id
    ):
        raise RuntimeFault(ErrorCategory.INVALID_EVENTS)
    seen = set()
    terminal = False
    for index, event in enumerate(events):
        if (
            event.sequence != index + 1
            or event.event_id in seen
            or terminal
            or event.workflow_run_id != first.workflow_run_id
            or event.session_id != first.session_id
            or event.agent_run_id != first.agent_run_id
            or event.parent_agent_run_id != first.parent_agent_run_id
            or event.correlation_id != first.correlation_id
            or event.causation_id != (events[index - 1].event_id if index else None)
            or (index > 0 and event.event_type == "workflow.started")
        ):
            raise RuntimeFault(ErrorCategory.INVALID_EVENTS)
        seen.add(event.event_id)
        terminal = event.event_type in {
            "workflow.completed",
            "workflow.failed",
            "workflow.cancelled",
        }


def project(events: list[RunEvent]) -> RunProjection:
    from decimal import Decimal

    validate_sequence(events)
    start = Started.model_validate(events[0].payload)
    state = RunProjection(
        request=start.request, config_hash=start.config_hash, sequence=1, stage=start.initial_stage
    ).model_dump()
    history = []
    for event in events[1:]:
        kind = event.event_type
        data = VOCABULARY[kind][0].model_validate(event.payload)
        state["sequence"] = event.sequence
        if kind == "step.started":
            state.update(steps=data.number, step_open=True, model_response=None)
        elif kind == "model.requested":
            state["model_inflight"] = True
        elif kind in {"model.completed", "model.failed"}:
            usage = data.response.usage if kind == "model.completed" else data.usage
            state["input_tokens"] += usage.input_tokens
            state["output_tokens"] += usage.output_tokens
            state["cost"] = str(Decimal(state["cost"]) + usage.cost)
            state["usage_unknown"] |= usage.source == "unknown"
            state["model_inflight"] = False
            if kind == "model.completed":
                state["model_response"] = data.response
        elif kind == "tool.requested":
            state.update(pending_call=data.call, tool_started=False, completed_tool=None)
        elif kind == "tool.started":
            state["tool_started"] = True
        elif kind == "approval.requested":
            state.update(pending_approval=data.approval, approval_granted=False)
        elif kind == "approval.granted":
            state["approval_granted"] = True
        elif kind == "tool.completed":
            call = state["pending_call"]
            if call is None or call.call_id != data.call_id:
                raise RuntimeFault(ErrorCategory.INVALID_EVENTS)
            state["completed_tool"] = data
            history.append(
                {
                    "tool": call.request.model_dump(mode="json"),
                    "result": data.result.model_dump(mode="json"),
                    "trust": "untrusted_tool_data",
                }
            )
        elif kind == "step.completed":
            state.update(
                stage=data.next_stage,
                progress_hash=data.progress_hash,
                no_progress_steps=data.no_progress_steps,
                pending_call=None,
                pending_approval=None,
                approval_granted=False,
                tool_started=False,
                completed_tool=None,
                step_open=False,
                model_response=None,
            )
        elif kind.startswith("workflow."):
            state["outcome"] = data.outcome
    state["history"] = history
    return RunProjection.model_validate(state)

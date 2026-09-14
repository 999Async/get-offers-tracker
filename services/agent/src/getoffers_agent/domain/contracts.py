"""Versioned boundary contracts. All identity and policy inputs come from trusted code."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    model_validator,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ErrorCategory(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    INVALID_OUTPUT = "invalid_output"
    HIDDEN_TOOL = "hidden_tool"
    POLICY_DENIED = "policy_denied"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_REJECTED = "approval_rejected"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    NO_PROGRESS = "no_progress"
    MODEL_FAILURE = "model_failure"
    TOOL_FAILURE = "tool_failure"
    AMBIGUOUS_WRITE = "ambiguous_write"
    INTERRUPTED = "interrupted"
    CONFIG_MISMATCH = "config_mismatch"
    CONFLICT = "conflict"
    INVALID_EVENTS = "invalid_events"


class RuntimeFault(Exception):
    """Stable, deliberately content-free errors suitable for operational reporting."""

    def __init__(self, category: ErrorCategory):
        self.category = category
        super().__init__(category.value)


class SecurityContext(Contract):
    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    capabilities: frozenset[str] = frozenset()
    request_id: UUID = Field(default_factory=uuid4)

    @field_serializer("capabilities")
    def sorted_capabilities(self, value):
        return sorted(value)


class Session(Contract):
    session_id: UUID = Field(default_factory=uuid4)


class RunBudget(Contract):
    max_steps: int = Field(default=8, ge=1, le=1000)
    deadline_at: AwareDatetime = Field(default_factory=lambda: utcnow() + timedelta(minutes=10))
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    max_cost: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_parallel_tools: Literal[1] = 1
    max_no_progress_steps: int = Field(default=2, ge=1)


class Usage(Contract):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    currency: Literal["USD"] = "USD"
    source: Literal["measured", "estimated", "synthetic", "unknown"] = "synthetic"
    pricing_version: str = "fake-v1"


class RunRequest(Contract):
    session: Session = Field(default_factory=Session)
    workflow_run_id: UUID = Field(default_factory=uuid4)
    agent_run_id: UUID = Field(default_factory=uuid4)
    parent_agent_run_id: UUID | None = None
    linked_run_id: UUID | None = None
    security: SecurityContext
    task: str = Field(min_length=1, max_length=16000)
    budget: RunBudget = Field(default_factory=RunBudget)


class WorkflowRun(Contract):
    workflow_run_id: UUID
    status: Literal["running", "awaiting_approval", "awaiting_reconciliation", "terminal"]


class AgentRun(Contract):
    agent_run_id: UUID
    parent_agent_run_id: UUID | None = None
    name: str = "career_agent"


class Step(Contract):
    number: int = Field(ge=1)
    stage: str


class WorkflowOutcome(Contract):
    status: Literal["success", "partial", "rejected", "cancelled", "failed"]
    answer: str = ""
    reason: ErrorCategory | None = None


class ToolSpec(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str
    version: str
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    effect: Literal["read", "write", "external"]
    exposure: Literal["direct", "deferred", "hidden"] = "direct"


class ToolRequest(Contract):
    name: str
    arguments: dict[str, JsonValue]


class ToolResult(Contract):
    value: dict[str, JsonValue]


class ToolCall(Contract):
    call_id: UUID = Field(default_factory=uuid4)
    request: ToolRequest
    effect: Literal["read", "write", "external"]
    tool_hash: str
    arguments_hash: str
    idempotency_key: str | None = None


class PendingApproval(Contract):
    action_id: UUID
    user_id: str
    tenant_id: str
    tool_name: str
    tool_hash: str
    canonical_arguments: dict[str, JsonValue]
    arguments_hash: str
    reason: str = "Confirm the exact Application Plan before writing."
    expires_at: AwareDatetime
    idempotency_key: str


class ApprovalDecision(Contract):
    action_id: UUID
    arguments_hash: str
    decision: Literal["grant", "reject"]


class ResumeRequest(Contract):
    workflow_run_id: UUID
    security: SecurityContext
    approval: ApprovalDecision | None = None


class ContextBlock(Contract):
    kind: Literal["policy", "workflow", "tools", "trusted_state", "untrusted_evidence", "session"]
    content: JsonValue


class ContextManifest(Contract):
    policy_version: str
    workflow_version: str
    toolset_hash: str
    user_state_hash: str
    corpus_version: str = "none-phase0"
    evidence_version: str = "none-phase0"
    session_hash: str
    model_version: str
    tokenizer_version: str
    runtime_version: str
    context_hash: str


class ModelRequest(Contract):
    step: Step
    blocks: tuple[ContextBlock, ...]
    manifest: ContextManifest
    remaining_input_tokens: int | None
    remaining_output_tokens: int | None
    remaining_cost: Decimal | None


class ModelResponse(Contract):
    tool: ToolRequest | None = None
    answer: Annotated[str, Field(min_length=1)] | None = None
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def exactly_one_action(self):
        if (self.tool is None) == (self.answer is None):
            raise ValueError("exactly one tool request or final answer is required")
        return self


class ToolContext(Contract):
    security: SecurityContext
    workflow_run_id: UUID
    stage: str
    idempotency_key: str | None = None


class PolicyDecision(Contract):
    allowed: bool
    requires_approval: bool


class Reconciliation(Contract):
    status: Literal["completed", "not_found", "unknown"]
    result: ToolResult | None = None

    @model_validator(mode="after")
    def completed_has_result(self):
        if (self.status == "completed") != (self.result is not None):
            raise ValueError("only completed reconciliation has a result")
        return self

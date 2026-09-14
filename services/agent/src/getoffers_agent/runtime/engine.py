"""Bounded single-Agent runtime. Events commit before any provider or tool effect."""

import asyncio
from collections.abc import AsyncIterator, Awaitable
from datetime import timedelta
from decimal import Decimal
from time import perf_counter
from typing import Protocol

from pydantic import ValidationError

from getoffers_agent import __version__
from getoffers_agent.adapters.events import EventStore
from getoffers_agent.domain.contracts import (
    Contract,
    ErrorCategory,
    ModelRequest,
    ModelResponse,
    PendingApproval,
    ResumeRequest,
    RunRequest,
    RuntimeFault,
    SecurityContext,
    Step,
    ToolCall,
    ToolContext,
    Usage,
    WorkflowOutcome,
    digest,
    utcnow,
)
from getoffers_agent.runtime.context import POLICY_VERSION, ContextEnricher, Workflow, assemble
from getoffers_agent.runtime.events import (
    VOCABULARY,
    ApprovalRequested,
    ApprovalResolved,
    Checkpoint,
    ContextAssembled,
    Empty,
    Failure,
    ModelCompleted,
    ModelRequested,
    Outcome,
    RunEvent,
    RunProjection,
    Started,
    StepCompleted,
    ToolCompleted,
    ToolRequested,
    ToolStarted,
    project,
)
from getoffers_agent.runtime.tools import ToolRegistry


class ModelProvider(Protocol):
    version: str
    tokenizer_version: str

    async def complete(self, request: ModelRequest) -> ModelResponse: ...


class ProviderFailure(Exception):
    def __init__(self, usage: Usage | None = None):
        self.usage = usage or Usage(source="unknown")
        super().__init__("model_failure")


class AgentRuntime:
    def __init__(
        self,
        store: EventStore,
        provider: ModelProvider,
        tools: ToolRegistry,
        workflow: Workflow,
        *,
        approval_ttl_seconds: int = 300,
        context_enricher: ContextEnricher | None = None,
    ):
        if approval_ttl_seconds <= 0:
            raise ValueError("approval TTL must be positive")
        self.store, self.provider, self.tools, self.workflow = store, provider, tools, workflow
        self.approval_ttl_seconds = approval_ttl_seconds
        self.context_enricher = context_enricher

    @property
    def config_hash(self) -> str:
        return digest(
            {
                "runtime": __version__,
                "provider": self.provider.version,
                "tokenizer": self.provider.tokenizer_version,
                "tools": self.tools.fingerprint,
                "workflow": self.workflow.fingerprint,
                "policy": POLICY_VERSION,
                "approval_ttl": self.approval_ttl_seconds,
                **(
                    {"context_enricher": self.context_enricher.version}
                    if self.context_enricher
                    else {}
                ),
            }
        )

    def replay(self, workflow_run_id) -> RunProjection:
        """Restricted local API. Pure projection: never invokes adapters other than the store."""
        return project(self.store.read(workflow_run_id))

    def _record(self, request: RunRequest, *items: tuple[str, Contract]) -> list[RunEvent]:
        previous = self.store.read(request.workflow_run_id)
        sequence = len(previous)
        cause = previous[-1].event_id if previous else None
        events = []
        for kind, data in items:
            sequence += 1
            event = RunEvent(
                sequence=sequence,
                event_type=kind,
                session_id=request.session.session_id,
                workflow_run_id=request.workflow_run_id,
                agent_run_id=request.agent_run_id,
                parent_agent_run_id=request.parent_agent_run_id,
                causation_id=cause,
                correlation_id=request.workflow_run_id,
                sensitivity="restricted" if VOCABULARY[kind][1] else "operational",
                payload=data.model_dump(mode="json"),
            )
            events.append(event)
            cause = event.event_id
        self.store.append(events)
        return events

    def _finish(
        self,
        request: RunRequest,
        reason: ErrorCategory | None = None,
        answer: str = "",
        status: str | None = None,
        completed_step: StepCompleted | None = None,
        preceding: tuple[str, Contract] | None = None,
    ) -> list[RunEvent]:
        if status is None:
            status = (
                "success"
                if reason is None
                else "cancelled"
                if reason == ErrorCategory.CANCELLED
                else "rejected"
                if reason in {ErrorCategory.APPROVAL_REJECTED, ErrorCategory.APPROVAL_EXPIRED}
                else "partial"
                if reason
                in {
                    ErrorCategory.BUDGET_EXHAUSTED,
                    ErrorCategory.NO_PROGRESS,
                    ErrorCategory.AMBIGUOUS_WRITE,
                }
                else "failed"
            )
        outcome = WorkflowOutcome(status=status, reason=reason, answer=answer)
        kind = (
            "workflow.cancelled"
            if status == "cancelled"
            else "workflow.failed"
            if status == "failed"
            else "workflow.completed"
        )
        agent = (
            ("agent.failed", Failure(category=reason)) if reason else ("agent.completed", Empty())
        )
        prefix = [("step.completed", completed_step)] if completed_step else []
        if preceding:
            prefix.insert(0, preceding)
        return self._record(request, *prefix, agent, (kind, Outcome(outcome=outcome)))

    @staticmethod
    def _guard(state: RunProjection, cancel: asyncio.Event | None, *, new_step=False) -> None:
        if cancel and cancel.is_set():
            raise RuntimeFault(ErrorCategory.CANCELLED)
        budget = state.request.budget
        if utcnow() >= budget.deadline_at:
            raise RuntimeFault(ErrorCategory.TIMEOUT)
        if new_step and state.steps >= budget.max_steps:
            raise RuntimeFault(ErrorCategory.BUDGET_EXHAUSTED)
        if state.no_progress_steps >= budget.max_no_progress_steps:
            raise RuntimeFault(ErrorCategory.NO_PROGRESS)
        if state.usage_unknown:
            raise RuntimeFault(ErrorCategory.MODEL_FAILURE)
        for used, limit in (
            (state.input_tokens, budget.max_input_tokens),
            (state.output_tokens, budget.max_output_tokens),
            (Decimal(state.cost), budget.max_cost),
        ):
            # Exactly hitting a cap can complete the current Step; it cannot buy a new call.
            if limit is not None and (used > limit or (new_step and used >= limit)):
                raise RuntimeFault(ErrorCategory.BUDGET_EXHAUSTED)

    @staticmethod
    async def _bounded(awaitable: Awaitable, request: RunRequest, cancel: asyncio.Event | None):
        # A cancellation arriving while the consumer inspects tool.started must not
        # race with scheduling an instantaneous write coroutine.
        if (cancel and cancel.is_set()) or utcnow() >= request.budget.deadline_at:
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise RuntimeFault(
                ErrorCategory.CANCELLED if cancel and cancel.is_set() else ErrorCategory.TIMEOUT
            )
        task = asyncio.ensure_future(awaitable)
        stopper = asyncio.create_task(cancel.wait()) if cancel else None
        try:
            remaining = max(0, (request.budget.deadline_at - utcnow()).total_seconds())
            watched = {task, stopper} if stopper else {task}
            done, _ = await asyncio.wait(
                watched, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if stopper and stopper in done:
                raise RuntimeFault(ErrorCategory.CANCELLED)
            if task not in done:
                raise RuntimeFault(ErrorCategory.TIMEOUT)
            return task.result()
        finally:
            for pending in (task, stopper):
                if pending and not pending.done():
                    pending.cancel()
            await asyncio.gather(*(t for t in (task, stopper) if t), return_exceptions=True)

    async def run(
        self, request: RunRequest, *, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[RunEvent]:
        # Detach mutable nested payloads at the trusted boundary.
        request = RunRequest.model_validate_json(request.model_dump_json())
        with self.store.lock(request.workflow_run_id):
            if self.store.read(request.workflow_run_id):
                raise RuntimeFault(ErrorCategory.CONFLICT)
            for event in self._record(
                request,
                (
                    "workflow.started",
                    Started(
                        request=request,
                        config_hash=self.config_hash,
                        initial_stage=self.workflow.initial_stage,
                    ),
                ),
                ("agent.started", Empty()),
            ):
                yield event
            async for event in self._drive(request, request.security, cancel):
                yield event

    async def resume(
        self, request: ResumeRequest, *, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[RunEvent]:
        with self.store.lock(request.workflow_run_id):
            state = self.replay(request.workflow_run_id)
            owner = state.request.security
            if (request.security.actor_id, request.security.tenant_id) != (
                owner.actor_id,
                owner.tenant_id,
            ):
                raise RuntimeFault(ErrorCategory.POLICY_DENIED)
            if state.outcome:
                return
            if state.config_hash != self.config_hash:
                raise RuntimeFault(ErrorCategory.CONFIG_MISMATCH)
            approval = state.pending_approval
            if request.approval:
                decision = request.approval
                if (
                    approval is None
                    or state.approval_granted
                    or decision.action_id != approval.action_id
                    or decision.arguments_hash != approval.arguments_hash
                ):
                    raise RuntimeFault(ErrorCategory.APPROVAL_MISMATCH)
                if approval.expires_at <= utcnow():
                    kind, reason = "approval.expired", ErrorCategory.APPROVAL_EXPIRED
                elif decision.decision == "reject":
                    kind, reason = "approval.rejected", ErrorCategory.APPROVAL_REJECTED
                else:
                    kind, reason = "approval.granted", None
                resolved = (
                    kind,
                    ApprovalResolved(
                        action_id=approval.action_id, arguments_hash=approval.arguments_hash
                    ),
                )
                if reason:
                    for event in self._finish(state.request, reason, preceding=resolved):
                        yield event
                    return
                for event in self._record(state.request, resolved):
                    yield event
            async for event in self._drive(state.request, request.security, cancel):
                yield event

    def _complete_step(self, state: RunProjection) -> list[RunEvent]:
        call, completed = state.pending_call, state.completed_tool
        fingerprint = digest(
            {
                "request": call.request.model_dump(mode="json"),
                "result": completed.result.model_dump(mode="json"),
            }
        )
        repeats = state.no_progress_steps + 1 if fingerprint == state.progress_hash else 0
        next_stage = self.workflow.transitions.get((state.stage, call.request.name), state.stage)
        return self._record(
            state.request,
            (
                "step.completed",
                StepCompleted(
                    step=Step(number=state.steps, stage=state.stage),
                    next_stage=next_stage,
                    progress_hash=fingerprint,
                    no_progress_steps=repeats,
                ),
            ),
            ("checkpoint.created", Checkpoint(through_sequence=state.sequence + 1)),
        )

    async def _drive(
        self, request: RunRequest, security: SecurityContext, cancel: asyncio.Event | None
    ) -> AsyncIterator[RunEvent]:
        try:
            while True:
                state = self.replay(request.workflow_run_id)
                if state.completed_tool:
                    for event in self._complete_step(state):
                        yield event
                    continue
                self._guard(state, cancel, new_step=not state.step_open)
                context = ToolContext(
                    security=security,
                    workflow_run_id=request.workflow_run_id,
                    stage=state.stage,
                    idempotency_key=(
                        state.pending_call.idempotency_key if state.pending_call else None
                    ),
                )
                if state.pending_call:
                    call = state.pending_call
                    tool, normalized = self.tools.resolve(
                        call.request, context, self.workflow.tools_by_stage[state.stage]
                    )
                    if call.tool_hash != tool.fingerprint or call.arguments_hash != digest(
                        normalized.arguments
                    ):
                        raise RuntimeFault(ErrorCategory.APPROVAL_MISMATCH)
                    if call.effect != "read":
                        approval = state.pending_approval
                        if approval is None:
                            approval = PendingApproval(
                                action_id=call.call_id,
                                user_id=security.actor_id,
                                tenant_id=security.tenant_id,
                                tool_name=call.request.name,
                                tool_hash=call.tool_hash,
                                canonical_arguments=normalized.arguments,
                                arguments_hash=call.arguments_hash,
                                expires_at=min(
                                    request.budget.deadline_at,
                                    utcnow() + timedelta(seconds=self.approval_ttl_seconds),
                                ),
                                idempotency_key=call.idempotency_key,
                            )
                            for event in self._record(
                                request,
                                ("approval.requested", ApprovalRequested(approval=approval)),
                                (
                                    "checkpoint.created",
                                    Checkpoint(through_sequence=state.sequence + 1),
                                ),
                            ):
                                yield event
                            return
                        if (
                            approval.canonical_arguments != normalized.arguments
                            or approval.arguments_hash != call.arguments_hash
                            or approval.tool_hash != call.tool_hash
                            or approval.tool_name != call.request.name
                            or approval.action_id != call.call_id
                            or approval.idempotency_key != call.idempotency_key
                            or (approval.user_id, approval.tenant_id)
                            != (security.actor_id, security.tenant_id)
                        ):
                            raise RuntimeFault(ErrorCategory.APPROVAL_MISMATCH)
                        if not state.tool_started and approval.expires_at <= utcnow():
                            for event in self._finish(
                                request,
                                ErrorCategory.APPROVAL_EXPIRED,
                                preceding=(
                                    "approval.expired",
                                    ApprovalResolved(
                                        action_id=approval.action_id,
                                        arguments_hash=approval.arguments_hash,
                                    ),
                                ),
                            ):
                                yield event
                            return
                        if not state.approval_granted:
                            return
                    started = perf_counter()
                    try:
                        if state.tool_started and call.effect != "read":
                            # An uncertain write is NEVER sent again, even with an old approval.
                            lookup = await self._bounded(
                                tool.handler.reconcile(context), request, cancel
                            )
                            if lookup.status != "completed":
                                raise RuntimeFault(ErrorCategory.AMBIGUOUS_WRITE)
                            result = lookup.result
                        else:
                            for event in self._record(
                                request, ("tool.started", ToolStarted(call_id=call.call_id))
                            ):
                                yield event
                            result = await self._bounded(
                                tool.handler.execute(
                                    context, normalized.model_dump(mode="json")["arguments"]
                                ),
                                request,
                                cancel,
                            )
                        result = self.tools.validate_result(tool, result)
                    except (Exception, asyncio.CancelledError) as exc:
                        reason = (
                            exc.category
                            if isinstance(exc, RuntimeFault)
                            else (
                                ErrorCategory.CANCELLED
                                if isinstance(exc, asyncio.CancelledError)
                                else ErrorCategory.TOOL_FAILURE
                            )
                        )
                        ambiguous = call.effect != "read"
                        for event in self._record(
                            request,
                            (
                                "tool.failed",
                                Failure(
                                    category=ErrorCategory.AMBIGUOUS_WRITE if ambiguous else reason,
                                    duration_ms=(perf_counter() - started) * 1000,
                                ),
                            ),
                        ):
                            yield event
                        if ambiguous and reason != ErrorCategory.CANCELLED:
                            for event in self._record(
                                request,
                                (
                                    "checkpoint.created",
                                    Checkpoint(
                                        through_sequence=self.replay(
                                            request.workflow_run_id
                                        ).sequence
                                    ),
                                ),
                            ):
                                yield event
                            return
                        raise RuntimeFault(reason) from None
                    for event in self._record(
                        request,
                        (
                            "tool.completed",
                            ToolCompleted(
                                call_id=call.call_id,
                                result=result,
                                duration_ms=(perf_counter() - started) * 1000,
                                reconciled=state.tool_started and call.effect != "read",
                            ),
                        ),
                    ):
                        yield event
                    continue
                if state.model_inflight:
                    # Usage is unknowable after a process died during a provider call.
                    for event in self._record(
                        request, ("model.failed", Failure(category=ErrorCategory.INTERRUPTED))
                    ):
                        yield event
                    raise RuntimeFault(ErrorCategory.INTERRUPTED)
                if state.model_response:
                    response = state.model_response
                    if response.answer is not None:
                        # Complete the Step and outcome atomically. A disconnect after
                        # step.completed must never buy another model call on resume.
                        completed_step = StepCompleted(
                            step=Step(number=state.steps, stage=state.stage),
                            next_stage=state.stage,
                            progress_hash=digest(response.answer),
                            no_progress_steps=0,
                        )
                        for event in self._finish(
                            request, answer=response.answer, completed_step=completed_step
                        ):
                            yield event
                        return
                    try:
                        tool, normalized = self.tools.resolve(
                            response.tool, context, self.workflow.tools_by_stage[state.stage]
                        )
                    except RuntimeFault as exc:
                        for event in self._record(
                            request, ("tool.rejected", Failure(category=exc.category))
                        ):
                            yield event
                        raise
                    call = ToolCall(
                        request=normalized,
                        effect=tool.spec.effect,
                        tool_hash=tool.fingerprint,
                        arguments_hash=digest(normalized.arguments),
                    )
                    if call.effect != "read":
                        call = call.model_copy(
                            update={
                                "idempotency_key": digest(
                                    {
                                        "tenant": security.tenant_id,
                                        "actor": security.actor_id,
                                        "run": str(request.workflow_run_id),
                                        "call": str(call.call_id),
                                        "tool": call.request.name,
                                        "arguments": call.arguments_hash,
                                    }
                                )
                            }
                        )
                    for event in self._record(
                        request, ("tool.requested", ToolRequested(call=call))
                    ):
                        yield event
                    continue
                if not state.step_open:
                    for event in self._record(
                        request, ("step.started", Step(number=state.steps + 1, stage=state.stage))
                    ):
                        yield event
                    state = self.replay(request.workflow_run_id)
                model_request = assemble(
                    state,
                    self.workflow,
                    self.tools,
                    security,
                    self.provider.version,
                    self.provider.tokenizer_version,
                )
                if self.context_enricher:
                    model_request = self.context_enricher.enrich(model_request)
                for event in self._record(
                    request,
                    ("context.assembled", ContextAssembled(manifest=model_request.manifest)),
                    ("model.requested", ModelRequested(request=model_request)),
                ):
                    yield event
                started = perf_counter()
                try:
                    response = await self._bounded(
                        self.provider.complete(model_request), request, cancel
                    )
                    response = ModelResponse.model_validate_json(response.model_dump_json())
                except (Exception, asyncio.CancelledError) as exc:
                    reason = (
                        exc.category
                        if isinstance(exc, RuntimeFault)
                        else (
                            ErrorCategory.CANCELLED
                            if isinstance(exc, asyncio.CancelledError)
                            else ErrorCategory.INVALID_OUTPUT
                            if isinstance(exc, (ValidationError, AttributeError))
                            else ErrorCategory.MODEL_FAILURE
                        )
                    )
                    for event in self._record(
                        request,
                        (
                            "model.failed",
                            Failure(
                                category=reason,
                                duration_ms=(perf_counter() - started) * 1000,
                                usage=exc.usage
                                if isinstance(exc, ProviderFailure)
                                else Usage(source="unknown"),
                            ),
                        ),
                    ):
                        yield event
                    raise RuntimeFault(reason) from None
                for event in self._record(
                    request,
                    (
                        "model.completed",
                        ModelCompleted(
                            response=response, duration_ms=(perf_counter() - started) * 1000
                        ),
                    ),
                ):
                    yield event
        except (RuntimeFault, asyncio.CancelledError) as exc:
            reason = exc.category if isinstance(exc, RuntimeFault) else ErrorCategory.CANCELLED
            if reason == ErrorCategory.BUDGET_EXHAUSTED:
                for event in self._record(request, ("budget.exhausted", Failure(category=reason))):
                    yield event
            for event in self._finish(request, reason):
                yield event

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from getoffers_agent.adapters.events import InMemoryEventStore, SQLiteEventStore
from getoffers_agent.adapters.fakes import FakeModelProvider, FakeProductPort
from getoffers_agent.career.demo import DEMO_WORKFLOW, demo_provider, demo_responses, demo_tools
from getoffers_agent.domain.contracts import (
    ApprovalDecision,
    ModelResponse,
    ResumeRequest,
    RunBudget,
    RunRequest,
    RuntimeFault,
    SecurityContext,
    ToolContext,
    ToolRequest,
    ToolResult,
    Usage,
    digest,
    utcnow,
)
from getoffers_agent.runtime.engine import AgentRuntime, ProviderFailure
from getoffers_agent.runtime.events import RunEvent, project
from getoffers_agent.runtime.telemetry import export_safely, redacted_spans
from getoffers_agent.runtime.tools import ToolRegistry


async def drain(stream):
    return [event async for event in stream]


def run(stream):
    return asyncio.run(drain(stream))


def security(**updates):
    return SecurityContext(
        actor_id="local-user",
        tenant_id="local-tenant",
        capabilities=frozenset(
            {
                "candidate:read:self",
                "application_plan:create:self",
            }
        ),
    ).model_copy(update=updates)


def harness(store=None, provider=None, product=None, workflow=DEMO_WORKFLOW):
    product = product or FakeProductPort()
    runtime = AgentRuntime(
        store or InMemoryEventStore(), provider or demo_provider(), demo_tools(product), workflow
    )
    return runtime, product


def request(**updates):
    return RunRequest(security=security(), task="Synthetic test task", **updates)


def decision(state, choice="grant", **updates):
    return ResumeRequest(
        workflow_run_id=state.request.workflow_run_id,
        security=state.request.security,
        approval=ApprovalDecision(
            action_id=state.pending_approval.action_id,
            arguments_hash=state.pending_approval.arguments_hash,
            decision=choice,
            **updates,
        ),
    )


@pytest.mark.parametrize("sqlite", [False, True])
def test_pause_resume_restart_replay_and_duplicate_resume(tmp_path, sqlite):
    store = SQLiteEventStore(tmp_path / "events.db") if sqlite else InMemoryEventStore()
    product = FakeProductPort(tmp_path / "product.db")
    runtime, _ = harness(store=store, product=product)
    req = request()
    run(runtime.run(req))
    before = runtime.replay(req.workflow_run_id)
    assert before.status == "awaiting_approval" and product.write_calls == 0
    assert before.pending_approval.canonical_arguments["job_id"] == "synthetic-job-001"
    assert before.pending_approval.arguments_hash == digest(
        before.pending_approval.canonical_arguments
    )
    if sqlite:
        runtime, product = harness(
            store=SQLiteEventStore(tmp_path / "events.db"),
            product=FakeProductPort(tmp_path / "product.db"),
        )
    run(runtime.resume(decision(before)))
    after = runtime.replay(req.workflow_run_id)
    assert after.outcome.status == "success" and product.write_calls == 1
    assert after.steps == 3 and after.input_tokens == 60
    assert run(runtime.resume(decision(before))) == []
    counts = (len(runtime.provider.calls), product.write_calls, product.lookup_calls)
    assert runtime.replay(req.workflow_run_id) == project(store.read(req.workflow_run_id))
    assert counts == (len(runtime.provider.calls), product.write_calls, product.lookup_calls)
    events = store.read(req.workflow_run_id)
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert events[-1].event_type == "workflow.completed"


@pytest.mark.parametrize("sqlite", [False, True])
def test_store_contract_immutability_versions_and_conflicts(tmp_path, sqlite):
    store = SQLiteEventStore(tmp_path / "events.db") if sqlite else InMemoryEventStore()
    runtime, _ = harness(store=store)
    req = request()
    run(runtime.run(req))
    first = store.read(req.workflow_run_id)[0]
    first.payload["request"]["task"] = "mutated"
    assert store.read(req.workflow_run_id)[0].payload["request"]["task"] == req.task
    assert (
        len(store.read(req.workflow_run_id, after_sequence=2))
        == len(store.read(req.workflow_run_id)) - 2
    )
    assert store.list_runs() == [req.workflow_run_id]
    with pytest.raises(RuntimeFault):
        store.append([first])
    raw = first.model_dump(mode="json")
    with pytest.raises(ValidationError):
        RunEvent.model_validate({**raw, "schema_version": 2})
    with pytest.raises(ValidationError):
        RunEvent.model_validate({**raw, "payload": {"bad": "shape"}})
    with pytest.raises(RuntimeFault):
        project(list(reversed(store.read(req.workflow_run_id))))
    if sqlite:
        with sqlite3.connect(tmp_path / "events.db") as db, pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE run_events SET body='{}'")


@pytest.mark.parametrize("sqlite", [False, True])
def test_concurrent_drivers_are_rejected(tmp_path, sqlite):
    first = SQLiteEventStore(tmp_path / "events.db") if sqlite else InMemoryEventStore()
    second = SQLiteEventStore(tmp_path / "events.db") if sqlite else first
    run_id = uuid4()
    with first.lock(run_id), pytest.raises(RuntimeFault, match="conflict"), second.lock(run_id):
        pass
    with second.lock(run_id):
        pass


@pytest.mark.parametrize(
    "budget,reason",
    [
        (RunBudget(max_steps=1), "budget_exhausted"),
        (RunBudget(max_input_tokens=19), "budget_exhausted"),
        (RunBudget(max_output_tokens=4), "budget_exhausted"),
        (RunBudget(max_cost=Decimal("0")), "budget_exhausted"),
        (RunBudget(deadline_at=utcnow() - timedelta(seconds=1)), "timeout"),
    ],
)
def test_budgets(budget, reason):
    runtime, product = harness()
    req = request(budget=budget)
    run(runtime.run(req))
    assert runtime.replay(req.workflow_run_id).outcome.reason == reason
    assert product.write_calls == 0


def test_exact_token_cap_completes_final_but_cannot_start_new_call():
    provider = FakeModelProvider([ModelResponse(answer="Done", usage=Usage(input_tokens=10))])
    runtime, _ = harness(provider=provider)
    req = request(budget=RunBudget(max_input_tokens=10))
    run(runtime.run(req))
    assert runtime.replay(req.workflow_run_id).outcome.status == "success"
    runtime, _ = harness()
    req = request(budget=RunBudget(max_input_tokens=20))
    run(runtime.run(req))
    assert runtime.replay(req.workflow_run_id).outcome.reason == "budget_exhausted"
    assert len(runtime.provider.calls) == 1


def test_no_progress_stop():
    workflow = replace(DEMO_WORKFLOW, transitions={})
    provider = FakeModelProvider(demo_responses()[:1])
    runtime, product = harness(provider=provider, workflow=workflow)
    req = request(budget=RunBudget(max_no_progress_steps=2))
    run(runtime.run(req))
    assert runtime.replay(req.workflow_run_id).outcome.reason == "no_progress"
    assert product.read_calls == 3


@pytest.mark.parametrize(
    "tool,args,reason",
    [
        ("no_such_tool", {}, "unknown_tool"),
        ("create_application_plan", {"job_id": "x"}, "hidden_tool"),
        ("get_candidate_state", {"tenant_id": "victim"}, "invalid_arguments"),
    ],
)
def test_tool_rejection(tool, args, reason):
    runtime, product = harness(
        provider=FakeModelProvider(
            [
                ModelResponse(tool=ToolRequest(name=tool, arguments=args)),
            ]
        )
    )
    req = request()
    run(runtime.run(req))
    assert runtime.replay(req.workflow_run_id).outcome.reason == reason
    assert product.read_calls == product.write_calls == 0


def test_tool_exposure_and_policy_denial():
    runtime, product = harness()
    req = RunRequest(security=security(capabilities=frozenset()), task="Override policy")
    run(runtime.run(req))
    assert runtime.provider.calls[0].blocks[2].content == []
    assert runtime.replay(req.workflow_run_id).outcome.reason == "policy_denied"
    assert product.read_calls == 0


@pytest.mark.parametrize(
    "choice,reason", [("reject", "approval_rejected"), ("expired", "approval_expired")]
)
def test_rejection_and_expiry(choice, reason, monkeypatch):
    runtime, product = harness()
    req = request()
    run(runtime.run(req))
    state = runtime.replay(req.workflow_run_id)
    if choice == "expired":
        monkeypatch.setattr(
            "getoffers_agent.runtime.engine.utcnow",
            lambda: state.pending_approval.expires_at + timedelta(seconds=1),
        )
    run(runtime.resume(decision(state, "reject" if choice == "reject" else "grant")))
    assert runtime.replay(req.workflow_run_id).outcome.reason == reason
    assert product.write_calls == 0


def test_approval_binding_identity_mutation_and_revocation():
    runtime, product = harness()
    req = request()
    run(runtime.run(req))
    state = runtime.replay(req.workflow_run_id)
    original = decision(state)
    for forged in [
        original.model_copy(update={"security": security(tenant_id="other")}),
        original.model_copy(update={"security": security(actor_id="other")}),
        original.model_copy(
            update={
                "approval": original.approval.model_copy(
                    update={"arguments_hash": digest({"job_id": "different-job"})}
                )
            }
        ),
        original.model_copy(
            update={"approval": original.approval.model_copy(update={"action_id": uuid4()})}
        ),
    ]:
        with pytest.raises(RuntimeFault):
            run(runtime.resume(forged))
    # Returned dictionaries cannot alter the persisted canonical approval.
    state.pending_approval.canonical_arguments["job_id"] = "other"
    assert (
        runtime.replay(req.workflow_run_id).pending_approval.canonical_arguments["job_id"]
        == "synthetic-job-001"
    )
    run(
        runtime.resume(original.model_copy(update={"security": security(capabilities=frozenset())}))
    )
    assert runtime.replay(req.workflow_run_id).outcome.reason == "policy_denied"
    assert product.write_calls == 0


def test_changed_toolset_requires_new_run():
    runtime, product = harness()
    req = request()
    run(runtime.run(req))
    state = runtime.replay(req.workflow_run_id)
    other, _ = harness(
        store=runtime.store, product=product, workflow=replace(DEMO_WORKFLOW, version="different")
    )
    with pytest.raises(RuntimeFault, match="config_mismatch"):
        run(other.resume(decision(state)))
    assert product.write_calls == 0


def test_ambiguous_write_reconciles_across_restart_without_repeating_write(tmp_path):
    runtime, product = harness(
        store=SQLiteEventStore(tmp_path / "events.db"),
        product=FakeProductPort(tmp_path / "product.db", lose_receipt=True),
    )
    req = request()
    run(runtime.run(req))
    run(runtime.resume(decision(runtime.replay(req.workflow_run_id))))
    state = runtime.replay(req.workflow_run_id)
    assert state.status == "awaiting_reconciliation" and product.write_calls == 1
    runtime, product = harness(
        store=SQLiteEventStore(tmp_path / "events.db"),
        product=FakeProductPort(tmp_path / "product.db"),
    )
    run(runtime.resume(ResumeRequest(workflow_run_id=req.workflow_run_id, security=req.security)))
    assert runtime.replay(req.workflow_run_id).outcome.status == "success"
    assert product.write_calls == 0 and product.lookup_calls == 1
    assert any(e.payload.get("reconciled") for e in runtime.store.read(req.workflow_run_id))


def test_product_idempotency_payload_and_tenant_binding():
    product = FakeProductPort()
    ctx = ToolContext(
        security=security(), workflow_run_id=uuid4(), stage="propose", idempotency_key="key"
    )
    first = asyncio.run(product.create_application_plan(ctx, {"job_id": "x", "note": ""}))
    assert first == asyncio.run(product.create_application_plan(ctx, {"note": "", "job_id": "x"}))
    with pytest.raises(ValueError, match="idempotency conflict"):
        asyncio.run(product.create_application_plan(ctx, {"job_id": "y"}))
    assert (
        asyncio.run(
            product.lookup_application_plan(
                ctx.model_copy(update={"security": security(tenant_id="other")})
            )
        ).status
        == "not_found"
    )


def test_restricted_content_never_enters_operational_spans_and_export_failure_isolated():
    secret = "private.person@example.org +86-13800138000 sk-test-secret"
    runtime, _ = harness(provider=FakeModelProvider([ModelResponse(answer=secret)]))
    req = RunRequest(security=security(actor_id=secret), task=secret)
    run(runtime.run(req))
    events = runtime.store.read(req.workflow_run_id)
    assert secret in json.dumps([e.model_dump(mode="json") for e in events])
    output = json.dumps(redacted_spans(events))
    assert secret not in output and "private.person" not in output and "sk-test" not in output
    assert any(
        span["name"] == "model" and span["parent_span_id"] for span in redacted_spans(events)
    )

    class BrokenExporter:
        def export(self, spans):
            raise RuntimeError(secret)

    assert export_safely(events, BrokenExporter()) is False
    assert runtime.replay(req.workflow_run_id).outcome.status == "success"


def test_provider_failure_usage_and_error_redaction():
    class Broken(FakeModelProvider):
        async def complete(self, request):
            raise ProviderFailure(Usage(input_tokens=7, cost=Decimal("0.01"), source="measured"))

    runtime, _ = harness(provider=Broken([]))
    req = request()
    run(runtime.run(req))
    state = runtime.replay(req.workflow_run_id)
    assert state.input_tokens == 7 and Decimal(state.cost) == Decimal("0.01")
    assert state.outcome.reason == "model_failure"


@pytest.mark.parametrize("mode", ["pre_cancel", "inflight_cancel", "timeout"])
def test_cancellation_and_timeout(mode):
    class Slow(FakeModelProvider):
        async def complete(self, request):
            await asyncio.Event().wait()

    async def scenario():
        runtime, product = harness(provider=Slow([]))
        cancel = asyncio.Event()
        if mode == "pre_cancel":
            cancel.set()
        req = request(
            budget=RunBudget(
                deadline_at=utcnow() + timedelta(seconds=0.05 if mode == "timeout" else 10)
            )
        )
        if mode == "inflight_cancel":
            asyncio.get_running_loop().call_later(0.01, cancel.set)
        await drain(runtime.run(req, cancel=cancel))
        assert runtime.replay(req.workflow_run_id).outcome.reason == (
            "timeout" if mode == "timeout" else "cancelled"
        )
        assert product.write_calls == 0

    asyncio.run(scenario())


def test_schema_hidden_exposure_and_output_validation():
    runtime, product = harness()
    entries = list(demo_tools(product)._tools.values())
    entries[0] = replace(entries[0], spec=entries[0].spec.model_copy(update={"exposure": "hidden"}))
    runtime.tools = ToolRegistry(entries)
    req = request()
    run(runtime.run(req))
    assert runtime.replay(req.workflow_run_id).outcome.reason == "hidden_tool"

    class MalformedProduct(FakeProductPort):
        async def get_candidate_state(self, context, arguments):
            return ToolResult(value={"skills": "incorrect-shape", "state_version": "1"})

    runtime, _ = harness(product=MalformedProduct())
    req = request()
    run(runtime.run(req))
    assert runtime.replay(req.workflow_run_id).outcome.reason == "invalid_output"


@pytest.mark.parametrize(
    "stop_at",
    ["step.started", "model.requested", "model.completed", "tool.completed", "step.completed"],
)
def test_resume_after_disconnected_stream(stop_at):
    async def scenario():
        provider = FakeModelProvider([ModelResponse(answer="One final answer")])
        runtime, product = harness(provider=provider)
        req = request()
        stream = runtime.run(req)
        async for event in stream:
            if event.event_type == stop_at:
                break
        await stream.aclose()
        before = len(provider.calls)
        await drain(
            runtime.resume(
                ResumeRequest(workflow_run_id=req.workflow_run_id, security=req.security)
            )
        )
        state = runtime.replay(req.workflow_run_id)
        if stop_at == "model.requested":
            assert state.outcome.reason == "interrupted"
            assert len(provider.calls) == before
        else:
            assert state.outcome.status == "success"
            assert len(provider.calls) == 1
        assert product.write_calls == 0

    asyncio.run(scenario())


def test_cancel_after_write_intent_does_not_schedule_handler():
    async def scenario():
        runtime, product = harness()
        req = request()
        await drain(runtime.run(req))
        cancel = asyncio.Event()
        stream = runtime.resume(decision(runtime.replay(req.workflow_run_id)), cancel=cancel)
        async for event in stream:
            if event.event_type == "tool.started":
                cancel.set()
        assert product.write_calls == 0
        assert runtime.replay(req.workflow_run_id).outcome.reason == "cancelled"

    asyncio.run(scenario())


def test_resume_after_approved_write_intent_does_not_resend_unknown_write():
    async def scenario():
        runtime, product = harness()
        req = request()
        await drain(runtime.run(req))
        stream = runtime.resume(decision(runtime.replay(req.workflow_run_id)))
        async for event in stream:
            if event.event_type == "tool.started":
                break
        await stream.aclose()
        for _ in range(2):
            await drain(
                runtime.resume(
                    ResumeRequest(workflow_run_id=req.workflow_run_id, security=req.security)
                )
            )
        assert product.write_calls == 0
        assert product.lookup_calls == 2
        assert runtime.replay(req.workflow_run_id).status == "awaiting_reconciliation"

    asyncio.run(scenario())


def test_rejected_approval_is_terminal_even_if_consumer_disconnects():
    async def scenario():
        runtime, product = harness()
        req = request()
        await drain(runtime.run(req))
        state = runtime.replay(req.workflow_run_id)
        stream = runtime.resume(decision(state, "reject"))
        async for event in stream:
            if event.event_type == "approval.rejected":
                break
        await stream.aclose()
        assert await drain(runtime.resume(decision(state))) == []
        assert runtime.replay(req.workflow_run_id).outcome.reason == "approval_rejected"
        assert product.write_calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("stop_at", ["approval.granted", "tool.completed", "step.completed"])
def test_approved_write_disconnect_recovery(stop_at, tmp_path):
    async def scenario():
        runtime, product = harness(
            store=SQLiteEventStore(tmp_path / "events.db"),
            product=FakeProductPort(tmp_path / "product.db"),
        )
        req = request()
        await drain(runtime.run(req))
        stream = runtime.resume(decision(runtime.replay(req.workflow_run_id)))
        async for event in stream:
            if event.event_type == stop_at:
                break
        await stream.aclose()
        writes_before = product.write_calls
        runtime, product = harness(
            store=SQLiteEventStore(tmp_path / "events.db"),
            product=FakeProductPort(tmp_path / "product.db"),
        )
        await drain(
            runtime.resume(
                ResumeRequest(workflow_run_id=req.workflow_run_id, security=req.security)
            )
        )
        assert runtime.replay(req.workflow_run_id).outcome.status == "success"
        assert writes_before + product.write_calls == 1

    asyncio.run(scenario())


def test_cost_overrun_is_recorded_before_followup_effects():
    response = ModelResponse(
        tool=ToolRequest(name="get_candidate_state", arguments={}),
        usage=Usage(cost=Decimal("0.02")),
    )
    runtime, product = harness(provider=FakeModelProvider([response]))
    req = request(budget=RunBudget(max_cost=Decimal("0.01")))
    run(runtime.run(req))
    state = runtime.replay(req.workflow_run_id)
    assert state.outcome.reason == "budget_exhausted"
    assert Decimal(state.cost) == Decimal("0.02")
    assert product.read_calls == 0


@pytest.mark.parametrize("malformed", [False, True])
def test_provider_boundary_rejects_bad_response_and_redacts_exceptions(malformed):
    class Broken(FakeModelProvider):
        async def complete(self, request):
            if malformed:
                return {"answer": "unvalidated output"}
            raise ValueError("private-secret-sk-abcd")

    runtime, _ = harness(provider=Broken([]))
    req = request()
    run(runtime.run(req))
    state = runtime.replay(req.workflow_run_id)
    assert state.outcome.reason == ("invalid_output" if malformed else "model_failure")
    assert "private-secret" not in json.dumps(
        [e.model_dump(mode="json") for e in runtime.store.read(req.workflow_run_id)]
    )

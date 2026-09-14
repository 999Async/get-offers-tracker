"""Version-pinned local paired evaluation. Synthetic cases are explicitly not quality labels."""

import math
import platform
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_serializer, model_validator

from getoffers_agent import __version__
from getoffers_agent.adapters.events import InMemoryEventStore
from getoffers_agent.adapters.fakes import FakeModelProvider, FakeProductPort
from getoffers_agent.career.demo import DEMO_WORKFLOW, demo_tools
from getoffers_agent.domain.contracts import (
    ApprovalDecision,
    Contract,
    ModelResponse,
    ResumeRequest,
    RunBudget,
    RunRequest,
    SecurityContext,
    digest,
    utcnow,
)
from getoffers_agent.runtime.engine import AgentRuntime
from getoffers_agent.runtime.events import RunEvent, project
from getoffers_agent.runtime.telemetry import redacted_spans

GRADER_VERSION = "runtime-deterministic-v1"


class EvaluationCase(Contract):
    case_id: str
    task: str
    responses: tuple[ModelResponse, ...] = Field(min_length=1)
    capabilities: frozenset[str]
    approval: Literal["grant", "reject", "none"] = "none"
    expected_status: str
    expected_reason: str | None = None
    expected_tools: tuple[str, ...] = ()
    expected_writes: int = Field(default=0, ge=0)

    @field_serializer("capabilities")
    def sorted_capabilities(self, value):
        return sorted(value)


class Dataset(Contract):
    schema_version: Literal[1] = 1
    dataset_version: str
    provenance: Literal["synthetic-runtime-contracts"]
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case ids")
        return self


class EvaluationConfig(Contract):
    config_id: str
    max_steps: int = Field(default=8, ge=1)
    max_no_progress_steps: int = Field(default=2, ge=1)
    model_version: Literal["fake-model-v1"] = "fake-model-v1"


def read_dataset(path: Path) -> Dataset:
    return Dataset.model_validate_json(path.read_text())


def runtime_source_hash() -> str:
    root = Path(__file__).parents[1]
    return digest(
        {str(path.relative_to(root)): path.read_text() for path in sorted(root.rglob("*.py"))}
    )


def grade(events: list[RunEvent], case: EvaluationCase) -> dict:
    state = project(events)
    requested, grants, tools, writes, unapproved = {}, {}, [], 0, 0
    for event in events:
        if event.event_type == "approval.requested":
            approval = event.payload["approval"]
            requested[approval["action_id"]] = approval
        elif event.event_type == "approval.granted":
            grants[event.payload["action_id"]] = event.payload["arguments_hash"]
        elif event.event_type == "tool.requested":
            call = event.payload["call"]
        elif event.event_type == "tool.started":
            tools.append(call["request"]["name"])
            if call["effect"] != "read":
                writes += 1
                approval = requested.get(call["call_id"])
                valid = (
                    approval is not None
                    and grants.get(call["call_id"]) == call["arguments_hash"]
                    and digest(call["request"]["arguments"]) == call["arguments_hash"]
                    and approval["canonical_arguments"] == call["request"]["arguments"]
                    and approval["tool_name"] == call["request"]["name"]
                    and approval["tool_hash"] == call["tool_hash"]
                    and approval["idempotency_key"] == call["idempotency_key"]
                    and approval["user_id"] == state.request.security.actor_id
                    and approval["tenant_id"] == state.request.security.tenant_id
                    and event.occurred_at < datetime.fromisoformat(approval["expires_at"])
                )
                unapproved += not valid
    status = state.outcome.status if state.outcome else state.status
    reason = str(state.outcome.reason) if state.outcome and state.outcome.reason else None
    checks = {
        "expected_status": status == case.expected_status,
        "expected_reason": reason == case.expected_reason,
        "expected_tools": tools == list(case.expected_tools),
        "expected_writes": writes == case.expected_writes,
        "approval_safety": unapproved == 0,
    }
    spans = redacted_spans(events)
    component_ms = sum(
        span["attributes"].get("duration_ms", 0)
        for span in spans
        if span["name"] in {"model", "tool"}
    )
    e2e_ms = (events[-1].occurred_at - events[0].occurred_at).total_seconds() * 1000
    approval_wait_ms = sum(
        (
            datetime.fromisoformat(span["end_time"]) - datetime.fromisoformat(span["start_time"])
        ).total_seconds()
        * 1000
        for span in spans
        if span["name"] == "approval" and span["end_time"]
    )
    return {
        "case_id": case.case_id,
        "passed": all(checks.values()),
        "checks": checks,
        "status": status,
        "reason": reason,
        "unapproved_writes": unapproved,
        "steps": state.steps,
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "cost": state.cost,
        "cost_source": "synthetic",
        "compute_duration_ms": max(0, e2e_ms - approval_wait_ms),
        "model_tool_duration_ms": component_ms,
        "approval_wait_ms": approval_wait_ms,
        "e2e_duration_ms": e2e_ms,
        "workflow_run_id": str(state.request.workflow_run_id),
    }


async def evaluate(dataset: Dataset, config: EvaluationConfig) -> dict:
    results, identities = [], {}
    for case in dataset.cases:
        store, product = InMemoryEventStore(), FakeProductPort()
        runtime = AgentRuntime(
            store,
            FakeModelProvider(list(case.responses), version=config.model_version),
            demo_tools(product),
            DEMO_WORKFLOW,
        )
        request = RunRequest(
            security=SecurityContext(
                actor_id="eval-user", tenant_id="eval-synthetic", capabilities=case.capabilities
            ),
            task=case.task,
            budget=RunBudget(
                max_steps=config.max_steps,
                max_no_progress_steps=config.max_no_progress_steps,
                deadline_at=utcnow() + timedelta(seconds=60),
            ),
        )
        async for _ in runtime.run(request):
            pass
        state = runtime.replay(request.workflow_run_id)
        if state.status == "awaiting_approval" and case.approval != "none":
            # Consent is fixture data for this synthetic product only. CLI demo never auto-grants.
            approval = state.pending_approval
            resume = ResumeRequest(
                workflow_run_id=request.workflow_run_id,
                security=request.security,
                approval=ApprovalDecision(
                    action_id=approval.action_id,
                    arguments_hash=approval.arguments_hash,
                    decision=case.approval,
                ),
            )
            async for _ in runtime.resume(resume):
                pass
        events = store.read(request.workflow_run_id)
        result = grade(events, case)
        before = (len(runtime.provider.calls), product.read_calls, product.write_calls)
        runtime.replay(request.workflow_run_id)
        result["checks"]["replay_no_effects"] = before == (
            len(runtime.provider.calls),
            product.read_calls,
            product.write_calls,
        )
        result["passed"] = all(result["checks"].values())
        # No raw task, argument, provider output, or actor identity enters the report.
        results.append(result)
        identities[case.case_id] = runtime.config_hash
    ordered = sorted(result["compute_duration_ms"] for result in results)
    return {
        "schema_version": 1,
        "dataset_version": dataset.dataset_version,
        "dataset_hash": digest(dataset.model_dump(mode="json")),
        "provenance": dataset.provenance,
        "config": config.model_dump(mode="json"),
        "config_hash": digest(config.model_dump(mode="json")),
        "runtime_version": __version__,
        "runtime_source_hash": runtime_source_hash(),
        "dependency_lock_hash": digest((Path(__file__).parents[3] / "uv.lock").read_text()),
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "architecture": platform.machine(),
        },
        "case_runtime_hashes": identities,
        "grader_version": GRADER_VERSION,
        "corpus_snapshot": "synthetic-v1",
        "user_state_snapshot": "synthetic-candidate-v1",
        "parser_version": "not-applicable",
        "retrieval_version": "not-applicable",
        "pricing_version": "fake-v1",
        "results": results,
        "summary": {
            "total": len(results),
            "passed": sum(r["passed"] for r in results),
            "unapproved_writes": sum(r["unapproved_writes"] for r in results),
            "compute_p50_ms": ordered[math.ceil(len(ordered) * 0.5) - 1],
            "compute_p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
            "input_tokens": sum(r["input_tokens"] for r in results),
            "output_tokens": sum(r["output_tokens"] for r in results),
        },
    }


def compare(baseline: dict, challenger: dict) -> dict:
    for field in (
        "dataset_hash",
        "dataset_version",
        "grader_version",
        "corpus_snapshot",
        "user_state_snapshot",
        "pricing_version",
    ):
        if baseline[field] != challenger[field]:
            raise ValueError("unpaired experiment identities")
    left = {row["case_id"]: row for row in baseline["results"]}
    right = {row["case_id"]: row for row in challenger["results"]}
    if (
        not left
        or left.keys() != right.keys()
        or len(left) != len(baseline["results"])
        or len(right) != len(challenger["results"])
    ):
        raise ValueError("missing or duplicate paired cases")
    pairs = [
        {
            "case_id": key,
            "pass_delta": int(right[key]["passed"]) - int(left[key]["passed"]),
            "step_delta": right[key]["steps"] - left[key]["steps"],
            "input_token_delta": right[key]["input_tokens"] - left[key]["input_tokens"],
            "compute_duration_delta_ms": right[key]["compute_duration_ms"]
            - left[key]["compute_duration_ms"],
        }
        for key in left
    ]
    safe = all(row["unapproved_writes"] == 0 for row in right.values())
    all_pass = all(row["passed"] for row in right.values())
    return {
        "schema_version": 1,
        "baseline": baseline,
        "challenger": challenger,
        "pairs": pairs,
        "gate": {
            "passed": safe and all_pass,
            "approval_safety": safe,
            "all_contract_cases_pass": all_pass,
            "scope": "synthetic runtime regression only; no production release decision",
        },
    }

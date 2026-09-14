"""Local-only CLI: start, inspect, approve/reject, resume, replay, spans, evaluate."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from getoffers_agent.adapters.events import SQLiteEventStore
from getoffers_agent.adapters.fakes import FakeProductPort
from getoffers_agent.career.demo import DEMO_WORKFLOW, demo_provider, demo_tools
from getoffers_agent.domain.contracts import (
    ApprovalDecision,
    ResumeRequest,
    RunRequest,
    RuntimeFault,
    SecurityContext,
)
from getoffers_agent.evaluation.runner import EvaluationConfig, compare, evaluate, read_dataset
from getoffers_agent.runtime.engine import AgentRuntime
from getoffers_agent.runtime.telemetry import redacted_spans


def local_identity() -> SecurityContext:
    # There is deliberately no HTTP/auth endpoint in Phase 0. This process represents
    # one local synthetic user, never a browser- or model-supplied identity.
    return SecurityContext(
        actor_id="demo-user",
        tenant_id="demo-local",
        capabilities=frozenset(
            {
                "candidate:read:self",
                "application_plan:create:self",
            }
        ),
    )


def write_report(path: Path, report: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Owner-only from creation, including while bytes are being written.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def display(state):
    print(
        json.dumps(
            {
                "workflow_run_id": str(state.request.workflow_run_id),
                "status": state.status,
                "steps": state.steps,
                "outcome": state.outcome.model_dump(mode="json") if state.outcome else None,
                "pending_approval": (
                    state.pending_approval.model_dump(mode="json")
                    if state.status == "awaiting_approval"
                    else None
                ),
                "usage": {
                    "input_tokens": state.input_tokens,
                    "output_tokens": state.output_tokens,
                    "cost": state.cost,
                    "source": "synthetic",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


async def execute(args) -> int:
    if args.command == "evaluate":
        dataset = read_dataset(args.dataset)
        baseline_config = EvaluationConfig.model_validate_json(args.baseline.read_text())
        baseline = await evaluate(dataset, baseline_config)
        if args.challenger:
            challenger_config = EvaluationConfig.model_validate_json(args.challenger.read_text())
            report = compare(baseline, await evaluate(dataset, challenger_config))
            passed = report["gate"]["passed"]
            summary = report["gate"]
        else:
            report = baseline
            summary = report["summary"]
            passed = summary["passed"] == summary["total"]
        write_report(args.out, report)
        print(
            json.dumps(
                {"report": str(args.out.resolve()), "gate_passed": passed, **summary}, indent=2
            )
        )
        return 0 if passed else 1
    store = SQLiteEventStore(args.data_dir / "runs.sqlite")
    if args.command == "list":
        print(json.dumps([str(run_id) for run_id in store.list_runs()], indent=2))
        return 0
    # replay and spans do not even instantiate a model or Product Port.
    if args.command in {"replay", "spans"}:
        from getoffers_agent.runtime.events import project

        events = store.read(args.run_id)
        if args.command == "replay":
            display(project(events))
        else:
            write_report(args.out, redacted_spans(events))
            print(json.dumps({"spans": str(args.out.resolve())}))
        return 0
    product = FakeProductPort(args.data_dir / "fake-product.sqlite")
    runtime = AgentRuntime(store, demo_provider(), demo_tools(product), DEMO_WORKFLOW)
    if args.command == "demo":
        request = RunRequest(
            security=local_identity(), task="Read state and propose a synthetic plan."
        )
        run_id = request.workflow_run_id
        async for _ in runtime.run(request):
            pass
    else:
        run_id = args.run_id
        approval = None
        if args.command in {"approve", "reject"}:
            approval = ApprovalDecision(
                action_id=args.action_id,
                arguments_hash=args.arguments_hash,
                decision="grant" if args.command == "approve" else "reject",
            )
        request = ResumeRequest(
            workflow_run_id=run_id, security=local_identity(), approval=approval
        )
        async for _ in runtime.resume(request):
            pass
    state = runtime.replay(run_id)
    display(state)
    return 1 if state.outcome and state.outcome.status == "failed" else 0


def main():
    repo = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description="GetOffers local synthetic Agent harness")
    parser.add_argument("--data-dir", type=Path, default=Path(".agent-data"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Start a synthetic workflow; stops for human approval")
    commands.add_parser("list")
    for name in ("approve", "reject", "resume", "replay", "spans"):
        command = commands.add_parser(name)
        command.add_argument("run_id", type=UUID)
        if name in {"approve", "reject"}:
            command.add_argument("--action-id", type=UUID, required=True)
            command.add_argument("--arguments-hash", required=True)
        if name == "spans":
            command.add_argument("--out", type=Path, required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument(
        "--dataset", type=Path, default=repo / "datasets/evals/runtime-v1/cases.json"
    )
    evaluation.add_argument(
        "--baseline", type=Path, default=repo / "datasets/evals/runtime-v1/baseline.json"
    )
    evaluation.add_argument("--challenger", type=Path)
    evaluation.add_argument("--out", type=Path, default=Path(".agent-data/evaluation.json"))
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(execute(args)))
    except RuntimeFault as exc:
        parser.exit(2, f"{exc.category.value}\n")
    except (ValueError, OSError):
        # Do not echo malformed payloads or storage/provider exception strings.
        parser.exit(2, "invalid_input_or_local_storage\n")


if __name__ == "__main__":
    main()

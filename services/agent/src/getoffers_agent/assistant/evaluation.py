"""Local assistant evaluation: frozen inputs, actual runtime, review binding, paired comparisons."""

import argparse
import asyncio
import csv
import io
import json
import math
import os
import platform
import tempfile
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from getoffers_agent.assistant.config import load_model_config
from getoffers_agent.assistant.contracts import ChatRequest
from getoffers_agent.assistant.eval_dataset import fixture, input_hash, read_dataset, user
from getoffers_agent.assistant.eval_scripted import ScriptedProvider
from getoffers_agent.assistant.provider import ChatProvider
from getoffers_agent.assistant.service import TOOL_DEFINITIONS, WORKFLOW, AssistantService
from getoffers_agent.domain.contracts import digest, utcnow
from getoffers_agent.evaluation.runner import runtime_source_hash
from getoffers_agent.runtime.events import project
from getoffers_agent.runtime.telemetry import redacted_spans

GRADER = "assistant-contract-and-human-review-v1"
ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATASET = ROOT / "datasets/evals/assistant-v1/synthetic.json"
FIELDS = [
    "report_hash",
    "case_id",
    "result_hash",
    "任务",
    "目标JD",
    "回答",
    "草稿",
    "引用",
    "审核要点",
    "自动检查",
    "fact_support",
    "usefulness",
    "jd_fit",
    "reviewer",
    "notes",
]


def write_new(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(text)


def write_json(path, value):
    write_new(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fingerprint(report):
    return digest({key: value for key, value in report.items() if key != "report_hash"})


def csv_text(value):
    value = str(value)
    # Excel formulas may be hidden behind leading whitespace; neutralize all model/user cells.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def review_rows(report):
    for result in report["results"]:
        message = result["message"] or {}
        row = {
            "report_hash": report["report_hash"],
            "case_id": result["case_id"],
            "result_hash": result["result_hash"],
            "任务": result["task"],
            "目标JD": result["jd"],
            "回答": message.get("answer", ""),
            "草稿": (message.get("draft") or {}).get("content", ""),
            "引用": json.dumps(message.get("citations", []), ensure_ascii=False),
            "审核要点": result["review_instruction"],
            "自动检查": json.dumps(result["checks"], ensure_ascii=False),
            "fact_support": "pending",
            "usefulness": "pending",
            "jd_fit": "pending" if result["jd"] else "n/a",
            "reviewer": "",
            "notes": "",
        }
        yield {key: csv_text(value) for key, value in row.items()}


def write_review_template(report, path):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(review_rows(report))
    write_new(path, "\ufeff" + stream.getvalue())


def grade(case, dataset, events, wire):
    done = next((item for item in wire if item["type"] == "done"), None)
    message = done["message"] if done else None
    calls = [e.payload["call"] for e in events if e.event_type == "tool.requested"]
    names = [call["request"]["name"] for call in calls]
    allowed = {name for name, _, _ in TOOL_DEFINITIONS}
    jobs, citations = (message or {}).get("jobs", []), (message or {}).get("citations", [])
    draft = (message or {}).get("draft")
    checks = {
        "service_accepted": done is not None,
        "required_tools": set(case.required_tools) <= set(names),
        "forbidden_tools_absent": not set(case.forbidden_tools) & set(names),
        "only_registered_read_tools": all(
            c["effect"] == "read" and c["request"]["name"] in allowed for c in calls
        ),
        "draft_kind": (draft or {}).get("kind") == case.draft_kind,
        "citations_present": bool(citations) if case.require_citations else True,
        "jobs_present": bool(jobs) if case.require_jobs else not jobs,
        "city_constraint": all(
            set(j["cities"]) <= set(case.cities) and bool(j["cities"]) for j in jobs
        )
        if case.cities
        else True,
        "forbidden_draft_fragments_absent": not any(
            part in (draft or {}).get("content", "") for part in case.forbidden_draft_fragments
        ),
        "foreign_canary_absent": dataset.foreign_canary
        not in json.dumps(
            {"response": wire, "events": [e.model_dump(mode="json") for e in events]},
            ensure_ascii=False,
        ),
        "trace_present": bool(events),
    }
    state = project(events) if events else None
    usage_known = bool(state and not state.usage_unknown)
    return {
        "checks": checks,
        "contracts_passed": all(checks.values()),
        "message": message,
        "failure": next((item["error"] for item in wire if item["type"] == "error"), None),
        "runtime_reason": str(state.outcome.reason)
        if state and state.outcome and state.outcome.reason
        else None,
        "tools": names,
        "steps": state.steps if state else 0,
        "input_tokens": state.input_tokens if usage_known else None,
        "output_tokens": state.output_tokens if usage_known else None,
        "usage_complete": usage_known,
        "runtime_cost": state.cost if usage_known else None,
    }


async def evaluate(dataset, factory, out, *, mode, model_identity, limit=None):
    if mode not in {"live", "scripted"}:
        raise ValueError("invalid_execution_mode")
    if limit is not None and (limit < 1 or limit > len(dataset.cases)):
        raise ValueError("invalid_case_limit")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    (out / "traces").mkdir(mode=0o700)
    results = []
    cases = dataset.cases[:limit] if limit else dataset.cases
    # Pair by canonical source content and case contracts, not generated database UUIDs.
    with tempfile.TemporaryDirectory(prefix="getoffers-assistant-eval-") as directory:
        with fixture(dataset, Path(directory)) as (ports, doc):
            for case in cases:
                events, wire = [], []
                provider = factory(case)
                service = AssistantService(provider, ports, event_observer=events.append)
                chat = ChatRequest.model_validate(
                    {
                        "request_id": str(uuid4()),
                        "messages": [{"role": "user", "content": case.task}],
                        "jd": case.jd,
                        "materials": [doc] if case.select_material else [],
                    }
                )
                started = perf_counter()
                try:
                    wire = [event async for event in service.chat(chat, user())]
                except Exception:
                    wire.append({"type": "error", "error": "EVALUATION_RUN_FAILED"})
                elapsed_ms = (perf_counter() - started) * 1000
                result = grade(case, dataset, events, wire)
                priced = mode == "live" and getattr(
                    getattr(provider, "config", None), "priced", False
                )
                result["cost_usd"] = result.pop("runtime_cost") if priced else None
                trace = {
                    "execution_mode": mode,
                    "provenance": "synthetic",
                    "events": [event.model_dump(mode="json") for event in events],
                    "spans": redacted_spans(events) if events else [],
                    "response": wire,
                }
                trace_name = f"traces/{case.case_id}.json"
                write_json(out / trace_name, trace)
                result.update(
                    case_id=case.case_id,
                    input_hash=input_hash(dataset, case),
                    task=case.task,
                    jd=case.jd,
                    review_instruction=case.review_instruction,
                    require_citations=case.require_citations,
                    duration_ms=elapsed_ms,
                    model_duration_ms=sum(
                        s["attributes"].get("duration_ms", 0)
                        for s in trace["spans"]
                        if s["name"] == "model"
                    ),
                    tool_duration_ms=sum(
                        s["attributes"].get("duration_ms", 0)
                        for s in trace["spans"]
                        if s["name"] == "tool"
                    ),
                    trace=trace_name,
                    trace_hash=digest(trace),
                    usage_source="provider-reported"
                    if mode == "live"
                    else "synthetic-no-inference",
                )
                result["result_hash"] = digest(result)
                results.append(result)
    ordered = sorted(row["duration_ms"] for row in results)
    costs = [row["cost_usd"] for row in results]
    report = {
        "schema_version": 1,
        "created_at": utcnow().isoformat(),
        "dataset_version": dataset.dataset_version,
        "dataset_hash": digest(dataset.model_dump(mode="json")),
        "provenance": dataset.provenance,
        "label_status": dataset.label_status,
        "execution_mode": mode,
        "model": model_identity,
        "source_hash": runtime_source_hash(),
        "dependency_lock_hash": digest((ROOT / "services/agent/uv.lock").read_text()),
        "grader_version": GRADER,
        "workflow_hash": WORKFLOW.fingerprint,
        "retrieval_mode": "lexical",
        "python_version": platform.python_version(),
        "environment": {"system": platform.system(), "architecture": platform.machine()},
        "results": results,
        "summary": {
            "total": len(results),
            "contracts_passed": sum(r["contracts_passed"] for r in results),
            "duration_p50_ms": ordered[math.ceil(len(ordered) * 0.5) - 1],
            "duration_p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
            "input_tokens": sum(r["input_tokens"] for r in results)
            if all(r["usage_complete"] for r in results)
            else None,
            "output_tokens": sum(r["output_tokens"] for r in results)
            if all(r["usage_complete"] for r in results)
            else None,
            "cost_usd": str(sum((Decimal(c) for c in costs), Decimal(0)))
            if all(c is not None for c in costs)
            else None,
        },
        "gate": {
            "human_review": "pending",
            "production_release": "not_evaluated",
            "quality_claim": False,
        },
    }
    report["report_hash"] = fingerprint(report)
    write_json(out / "report.json", report)
    write_review_template(report, out / "review.csv")
    return report


def read_report(path):
    report = json.loads(Path(path).read_text())
    if report.get("schema_version") != 1 or report.get("report_hash") != fingerprint(report):
        raise ValueError("report_fingerprint_mismatch")
    rows = report["results"]
    if not rows or len({r["case_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate_or_missing_cases")
    if any(
        r["result_hash"] != digest({k: v for k, v in r.items() if k != "result_hash"}) for r in rows
    ):
        raise ValueError("result_fingerprint_mismatch")
    for row in rows:
        trace_path = Path(path).resolve().parent / row["trace"]
        if not trace_path.resolve().is_relative_to(Path(path).resolve().parent):
            raise ValueError("trace_outside_report_directory")
        trace = json.loads(trace_path.read_text())
        if digest(trace) != row["trace_hash"]:
            raise ValueError("trace_fingerprint_mismatch")
        if trace["events"]:
            from getoffers_agent.runtime.events import RunEvent

            project([RunEvent.model_validate(e) for e in trace["events"]])
    return report


def replay_case(report_path, case_id):
    report = read_report(report_path)
    result = next((row for row in report["results"] if row["case_id"] == case_id), None)
    if result is None:
        raise ValueError("case_not_found")
    return {
        "case_id": case_id,
        "execution_mode": report["execution_mode"],
        "contracts_passed": result["contracts_passed"],
        "checks": result["checks"],
        "tools": result["tools"],
        "steps": result["steps"],
        "failure": result["failure"],
        "runtime_reason": result["runtime_reason"],
        "model_called": False,
        "trace_verified": True,
    }


def import_reviews(report, path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return import_review_text(report, stream.read())


def import_review_text(report, content):
    """Shared validation for CLI files and bounded, already-read developer artifacts."""
    try:
        reader = csv.DictReader(
            io.StringIO(content.removeprefix("\ufeff"), newline=""), strict=True
        )
        if reader.fieldnames != FIELDS:
            raise ValueError("review_columns_changed")
        rows = list(reader)
    except csv.Error as exc:
        raise ValueError("invalid_review_csv") from exc
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("invalid_review_row")
    by_id = {r["case_id"]: r for r in report["results"]}
    if len(rows) != len(by_id) or {r["case_id"] for r in rows} != set(by_id):
        raise ValueError("missing_duplicate_or_foreign_review_cases")
    frozen_rows = {row["case_id"]: row for row in review_rows(report)}
    accepted = []
    for row in rows:
        if any(row[key] != frozen_rows[row["case_id"]][key] for key in FIELDS[:-5]):
            raise ValueError("review_source_columns_changed")
        result = by_id[row["case_id"]]
        if (
            row["report_hash"] != report["report_hash"]
            or row["result_hash"] != result["result_hash"]
        ):
            raise ValueError("review_does_not_match_result")
        labels = {key: row[key].strip() for key in ("fact_support", "usefulness", "jd_fit")}
        if any(value not in {"pass", "fail", "pending", "n/a"} for value in labels.values()):
            raise ValueError("invalid_review_label")
        if (
            labels["usefulness"] == "n/a"
            or (result["jd"] and labels["jd_fit"] == "n/a")
            or (result["require_citations"] and labels["fact_support"] == "n/a")
        ):
            raise ValueError("required_review_dimension_missing")
        if any(v in {"pass", "fail"} for v in labels.values()) and not row["reviewer"].strip():
            raise ValueError("reviewer_required")
        if "fail" in labels.values() and not row["notes"].strip():
            raise ValueError("failure_reason_required")
        accepted.append(
            {
                "case_id": row["case_id"],
                **labels,
                "reviewer": row["reviewer"].strip(),
                "notes": row["notes"].strip(),
            }
        )
    failed = any("fail" in (r["fact_support"], r["usefulness"], r["jd_fit"]) for r in accepted)
    pending = any("pending" in (r["fact_support"], r["usefulness"], r["jd_fit"]) for r in accepted)
    return {
        "schema_version": 1,
        "report_hash": report["report_hash"],
        "reviews": accepted,
        "review_status": "rejected" if failed else "pending" if pending else "reviewed",
        "production_release": "not_evaluated",
        "quality_claim": False,
        "scope": "synthetic development cases; no real-workflow release decision",
    }


def compare(left, right, left_review=None, right_review=None):
    if (left_review is None) != (right_review is None):
        raise ValueError("both_review_files_required")
    for key in (
        "dataset_hash",
        "dataset_version",
        "grader_version",
        "execution_mode",
        "retrieval_mode",
        "dependency_lock_hash",
    ):
        if left[key] != right[key]:
            raise ValueError("unpaired_experiment_identity:" + key)
    a, b = ({r["case_id"]: r for r in report["results"]} for report in (left, right))
    if (
        not a
        or a.keys() != b.keys()
        or len(a) != len(left["results"])
        or len(b) != len(right["results"])
    ):
        raise ValueError("unpaired_case_set")
    pairs = []
    for key in a:
        x, y = a[key], b[key]
        if x["input_hash"] != y["input_hash"]:
            raise ValueError("unpaired_case_input")
        pairs.append(
            {
                "case_id": key,
                "contract_pass_delta": int(y["contracts_passed"]) - int(x["contracts_passed"]),
                "duration_delta_ms": y["duration_ms"] - x["duration_ms"],
                "input_token_delta": y["input_tokens"] - x["input_tokens"]
                if x["input_tokens"] is not None and y["input_tokens"] is not None
                else None,
                "cost_delta_usd": str(Decimal(y["cost_usd"]) - Decimal(x["cost_usd"]))
                if x["cost_usd"] is not None and y["cost_usd"] is not None
                else None,
            }
        )
    quality = {}
    if left_review is not None:
        if (
            left_review["report_hash"] != left["report_hash"]
            or right_review["report_hash"] != right["report_hash"]
        ):
            raise ValueError("unpaired_reviews")
        review_a = {r["case_id"]: r for r in left_review["reviews"]}
        review_b = {r["case_id"]: r for r in right_review["reviews"]}
        if review_a.keys() != a.keys() or review_b.keys() != b.keys():
            raise ValueError("unpaired_review_case_set")
        for dimension in ("fact_support", "usefulness", "jd_fit"):
            valid = [
                (review_a[k][dimension], review_b[k][dimension])
                for k in a
                if review_a[k][dimension] in {"pass", "fail"}
                and review_b[k][dimension] in {"pass", "fail"}
            ]
            quality[dimension] = {
                "paired_reviewed_cases": len(valid),
                "excluded_pending_or_na": len(a) - len(valid),
                "pass_rate_delta": sum(int(y == "pass") - int(x == "pass") for x, y in valid)
                / len(valid)
                if valid
                else None,
            }
    return {
        "human_review_deltas": quality,
        "baseline": left["report_hash"],
        "challenger": right["report_hash"],
        "pairs": pairs,
        "changed_factors": [
            key for key in ("model", "source_hash", "workflow_hash") if left[key] != right[key]
        ],
        "gate": {
            "contract_regression": any(p["contract_pass_delta"] < 0 for p in pairs),
            "production_release": "not_evaluated",
            "quality_claim": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--mode", choices=["live", "scripted"], default="live")
    run.add_argument("--env-file", type=Path)
    run.add_argument("--limit", type=int)
    run.add_argument("--provider", choices=["compatible", "codex"], default="compatible")
    run.add_argument("--model", help="Optional model from the current Codex account's model list")
    check = sub.add_parser("check")
    check.add_argument("--env-file", type=Path)
    check.add_argument("--provider", choices=["compatible", "codex"], default="compatible")
    check.add_argument("--model")
    review = sub.add_parser("review")
    review.add_argument("--report", type=Path, required=True)
    review.add_argument("--csv", type=Path, required=True)
    review.add_argument("--out", type=Path, required=True)
    paired = sub.add_parser("compare")
    paired.add_argument("--baseline", type=Path, required=True)
    paired.add_argument("--challenger", type=Path, required=True)
    paired.add_argument("--out", type=Path, required=True)
    paired.add_argument("--baseline-csv", type=Path)
    paired.add_argument("--challenger-csv", type=Path)
    replay = sub.add_parser("replay")
    replay.add_argument("--report", type=Path, required=True)
    replay.add_argument("--case", required=True)
    args = parser.parse_args()
    try:
        codex_model, codex_identity = None, None
        if args.command in {"check", "run"}:
            if (
                args.provider == "codex"
                and (args.env_file or getattr(args, "mode", "live") != "live")
            ) or (args.provider != "codex" and args.model):
                raise ValueError("incompatible_provider_options")
            if args.command == "run" and args.out.exists():
                raise ValueError("output_already_exists")
            if args.provider == "codex":
                from getoffers_agent.assistant.eval_codex import local_provider

                codex_model, codex_identity = asyncio.run(local_provider(args.model))
        if args.command == "replay":
            print(json.dumps(replay_case(args.report, args.case), ensure_ascii=False))
            return 0
        if args.command == "check":
            if codex_model:
                print(
                    json.dumps(
                        {
                            "configured": True,
                            "provider": "codex",
                            "model": codex_identity,
                            "account_checked": True,
                            "inference_checked": False,
                            "pricing_configured": False,
                        }
                    )
                )
                return 0
            config = load_model_config(args.env_file)
            print(
                json.dumps(
                    {
                        "configured": bool(config),
                        "pricing_configured": bool(config and config.priced),
                        "network_checked": False,
                    }
                )
            )
            return 0 if config else 2
        if args.command == "run":
            dataset = read_dataset(args.dataset)
            config = (
                load_model_config(args.env_file)
                if args.mode == "live" and args.provider == "compatible"
                else None
            )
            if args.mode == "live" and config is None and codex_model is None:
                print(json.dumps({"error": "MODEL_NOT_CONFIGURED", "executed": False}))
                return 2
            if codex_model:

                def factory(case):
                    return codex_model

                identity = codex_identity
            elif args.mode == "live":
                model = ChatProvider(config)

                def factory(case):
                    return model

                identity = {
                    "provider_version": model.version,
                    "model_name": config.model,
                    "pricing_configured": config.priced,
                    "max_output_tokens": config.max_output_tokens,
                    "pricing": {
                        "currency": "USD",
                        "input_per_million": str(config.input_price)
                        if config.input_price is not None
                        else None,
                        "output_per_million": str(config.output_price)
                        if config.output_price is not None
                        else None,
                    },
                }
            else:

                def factory(case):
                    return ScriptedProvider(case, dataset)

                identity = {
                    "provider_version": ScriptedProvider.version,
                    "model_name": "none-scripted",
                    "pricing_configured": False,
                }
            report = asyncio.run(
                evaluate(
                    dataset,
                    factory,
                    args.out,
                    mode=args.mode,
                    model_identity=identity,
                    limit=args.limit,
                )
            )
            print(
                json.dumps(
                    {
                        "summary": report["summary"],
                        "gate": report["gate"],
                        "execution_mode": args.mode,
                    }
                )
            )
            return 0 if report["summary"]["contracts_passed"] == report["summary"]["total"] else 1
        if args.command == "review":
            report = import_reviews(read_report(args.report), args.csv)
        else:
            left, right = read_report(args.baseline), read_report(args.challenger)
            report = compare(
                left,
                right,
                import_reviews(left, args.baseline_csv) if args.baseline_csv else None,
                import_reviews(right, args.challenger_csv) if args.challenger_csv else None,
            )
        write_json(args.out, report)
        print(json.dumps({"written": True, "production_release": "not_evaluated"}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, TimeoutError):
        # No raw environment, model output, credentials or private input in diagnostics.
        print(json.dumps({"error": "EVALUATION_INPUT_OR_OUTPUT_INVALID", "written": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

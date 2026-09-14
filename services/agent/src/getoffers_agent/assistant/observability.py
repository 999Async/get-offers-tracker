"""Read-only local developer projections. Never return report payloads or file paths."""

import json
import math
import os
import re
from contextvars import ContextVar
from datetime import datetime
from itertools import islice
from pathlib import Path
from uuid import UUID

from getoffers_agent.assistant.evaluation import compare, fingerprint, import_review_text
from getoffers_agent.domain.contracts import ErrorCategory, digest, utcnow
from getoffers_agent.runtime.events import RunEvent, project

CAPABILITIES = frozenset({"metrics:read", "trace:read:redacted", "evaluation:read"})
MAX_FILE = 8_000_000
MAX_FILES = 500
MAX_CASES = 100
ERRORS = {e.value for e in ErrorCategory}
DIMENSIONS = ("fact_support", "usefulness", "jd_fit")
READ_BUDGET = ContextVar("developer_read_budget", default=32_000_000)


class ReadLimit(ValueError):
    pass


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def identity(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) else None


def timestamp(value):
    try:
        return datetime.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None


def spans_view(spans):
    result = []
    for s in spans[:1000]:
        if not isinstance(s, dict) or s.get("name") not in {
            "workflow",
            "agent",
            "step",
            "model",
            "tool",
            "approval",
        }:
            continue
        attrs = s.get("attributes", {})
        start, end = timestamp(s.get("start_time")), timestamp(s.get("end_time"))
        duration = number(attrs.get("duration_ms"))
        if duration is None and start and end:
            duration = number(
                (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000
            )
        result.append(
            {
                "name": s["name"],
                "start_time": start,
                "end_time": end,
                "status": s.get("status")
                if s.get("status")
                in {"pending", "completed", "failed", "cancelled", "granted", "rejected", "expired"}
                else "unknown",
                "duration_ms": duration,
                "input_tokens": number(attrs.get("input_tokens")),
                "output_tokens": number(attrs.get("output_tokens")),
                "cost_usd": number(attrs.get("cost"))
                if attrs.get("currency") == "USD"
                and attrs.get("source") in {"measured", "estimated"}
                else None,
                "usage_source": attrs.get("source")
                if attrs.get("source") in {"synthetic", "measured", "estimated"}
                else "unknown",
                "error_category": attrs.get("error_category")
                if attrs.get("error_category") in ERRORS
                else None,
                "outcome_status": attrs.get("outcome_status")
                if attrs.get("outcome_status")
                in {"success", "partial", "rejected", "cancelled", "failed"}
                else None,
            }
        )
    return result


def run_view(data):
    run_id = str(UUID(data["run_id"]))
    spans = spans_view(data["spans"])
    workflow = next((s for s in spans if s["name"] == "workflow"), {})
    models = [s for s in spans if s["name"] == "model"]

    def total(key):
        values = [s[key] for s in models]
        return sum(values) if values and all(v is not None for v in values) else None

    return {
        "run_id": run_id,
        "created_at": workflow.get("start_time"),
        "status": workflow.get("outcome_status") or "incomplete",
        "failure": workflow.get("error_category"),
        "duration_ms": workflow.get("duration_ms"),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "cost_usd": total("cost_usd"),
        "config_hash": identity(data.get("config_hash")),
        "synthetic": bool(models) and all(s["usage_source"] == "synthetic" for s in models),
        "spans": spans,
    }


class ObservabilityReader:
    def __init__(self, audit_root: Path, evaluation_root: Path, access_log: Path):
        self.roots = {"runs": audit_root.absolute(), "evaluations": evaluation_root.absolute()}
        self.access_log = access_log

    def read_bytes(self, path, root):
        path, root = Path(path).absolute(), Path(root).absolute()
        if not path.is_relative_to(root) or path.resolve() != path or root.resolve() != root:
            raise ValueError("unsafe_artifact")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > MAX_FILE:
                raise ValueError("artifact_too_large")
            if size > READ_BUDGET.get():
                raise ReadLimit("request_read_limit")
            READ_BUDGET.set(READ_BUDGET.get() - size)
            raw = stream.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                raise ValueError("artifact_too_large")
        return raw

    def read_json(self, path, root):
        return json.loads(self.read_bytes(path, root))

    def catalog(self, kind):
        root = self.roots[kind]
        if not root.exists():
            return {}, False
        pattern = "*.json" if kind == "runs" else "*/report.json"
        paths = list(islice(root.glob(pattern), MAX_FILES + 1))
        # Bound enumeration before sorting; warn rather than claim an exhaustive list.
        return {digest(str(p.relative_to(root))): p for p in sorted(paths[:MAX_FILES])}, len(
            paths
        ) > MAX_FILES

    def report(self, path):
        root = self.roots["evaluations"]
        report = self.read_json(path, root)
        if report.get("schema_version") != 1 or report.get("report_hash") != fingerprint(report):
            raise ValueError("invalid_report")
        rows = report["results"]
        if not 0 < len(rows) <= MAX_CASES or len({r["case_id"] for r in rows}) != len(rows):
            raise ValueError("invalid_cases")
        for row in rows:
            if (
                not isinstance(row.get("contracts_passed"), bool)
                or not isinstance(row.get("checks"), dict)
                or any(not isinstance(v, bool) for v in row["checks"].values())
            ):
                raise ValueError("invalid_result_types")
            for key in (
                "duration_ms",
                "model_duration_ms",
                "tool_duration_ms",
                "input_tokens",
                "output_tokens",
                "cost_usd",
            ):
                if row.get(key) is not None and number(row[key]) is None:
                    raise ValueError("invalid_result_metric")
            if row["result_hash"] != digest({k: v for k, v in row.items() if k != "result_hash"}):
                raise ValueError("invalid_result")
            trace_path = path.parent / row["trace"]
            trace = self.read_json(trace_path, path.parent)
            if digest(trace) != row["trace_hash"]:
                raise ValueError("invalid_trace")
            if trace["events"]:
                project([RunEvent.model_validate(e) for e in trace["events"]])
        return report

    def review_at(self, report, path):
        """Only the explicit sibling reviewed.csv is an operator-supplied review."""
        empty = {"binding": "missing", "status": "pending", "hash": None, "dimensions": {}}
        try:
            raw = self.read_bytes(path.parent / "reviewed.csv", path.parent)
            accepted = import_review_text(report, raw.decode("utf-8-sig"))
        except FileNotFoundError:
            return None, empty
        except ReadLimit:
            raise
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            return None, {**empty, "binding": "invalid"}
        dimensions = {}
        for dimension in DIMENSIONS:
            labels = [r[dimension] for r in accepted["reviews"]]
            passed, failed = labels.count("pass"), labels.count("fail")
            reviewed = passed + failed
            dimensions[dimension] = {
                "passed": passed,
                "failed": failed,
                "pending": labels.count("pending"),
                "not_applicable": labels.count("n/a"),
                "reviewed": reviewed,
                "pass_rate": passed / reviewed if reviewed else None,
            }
        return accepted, {
            "binding": "verified",
            "status": accepted["review_status"],
            "hash": digest(raw.decode("utf-8-sig")),
            "dimensions": dimensions,
        }

    def evaluation_view(self, report, path):
        rows = report["results"]
        accepted, review = self.review_at(report, path)
        reviews = (
            {r["case_id"]: {k: r[k] for k in DIMENSIONS} for r in accepted["reviews"]}
            if accepted
            else {}
        )
        return {
            "report_hash": identity(report["report_hash"]),
            "dataset_hash": identity(report["dataset_hash"]),
            "source_hash": identity(report["source_hash"]),
            "workflow_hash": identity(report["workflow_hash"]),
            "dependency_lock_hash": identity(report["dependency_lock_hash"]),
            "created_at": timestamp(report["created_at"]),
            "mode": report["execution_mode"]
            if report["execution_mode"] in {"live", "scripted"}
            else "unknown",
            "total": len(rows),
            "passed": sum(r["contracts_passed"] is True for r in rows),
            "review_status": review["status"],
            "review": review,
            "production_release": "not_evaluated",
            "quality_claim": False,
            "cases": [
                {
                    "case_id": str(i + 1),
                    "review": reviews.get(r["case_id"]),
                    "passed": r["contracts_passed"] is True,
                    "checks": [
                        {"name": k, "passed": v is True}
                        for k, v in r["checks"].items()
                        if k in CHECKS
                    ],
                    "duration_ms": number(r["duration_ms"]),
                    "model_duration_ms": number(r["model_duration_ms"]),
                    "tool_duration_ms": number(r["tool_duration_ms"]),
                    "input_tokens": number(r["input_tokens"]),
                    "output_tokens": number(r["output_tokens"]),
                    "cost_usd": number(r["cost_usd"]),
                    "failure": r.get("runtime_reason")
                    if r.get("runtime_reason") in ERRORS
                    else None,
                }
                for i, r in enumerate(rows)
            ],
        }

    def audit(self, actor, action, allowed):
        self.access_log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.access_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(
                json.dumps(
                    {
                        "at": utcnow().isoformat(),
                        "actor_hash": digest(actor),
                        "action": action
                        if action
                        in {"capabilities", "runs", "run", "evaluations", "evaluation", "compare"}
                        else "unknown",
                        "allowed": allowed,
                    }
                )
                + "\n"
            )

    def handle(self, body, actor, capabilities):
        READ_BUDGET.set(32_000_000)
        action = body.get("action")
        required = {
            "capabilities": "metrics:read",
            "runs": "metrics:read",
            "run": "trace:read:redacted",
            "evaluations": "evaluation:read",
            "evaluation": "evaluation:read",
            "compare": "evaluation:read",
        }.get(action)
        allowed = required is not None and required in capabilities
        self.audit(actor, action, allowed)  # Fail closed if developer access cannot be audited.
        if not allowed:
            raise PermissionError("DEVELOPER_ACCESS_DENIED")
        if set(body) - {"action", "id", "baseline", "challenger"}:
            raise ValueError("invalid_request")
        if action == "capabilities":
            return {"capabilities": sorted(CAPABILITIES & capabilities)}
        kind = "runs" if action in {"run", "runs"} else "evaluations"
        catalog, truncated = self.catalog(kind)
        if action in {"runs", "evaluations"}:
            items, invalid = [], 0
            for key, path in catalog.items():
                try:
                    item = (
                        run_view(self.read_json(path, self.roots[kind]))
                        if kind == "runs"
                        else self.evaluation_view(self.report(path), path)
                    )
                    item.pop("spans", None)
                    item.pop("cases", None)
                    items.append({"id": key, **item})
                except ReadLimit:
                    truncated = True
                    break
                except (ValueError, OSError, KeyError, TypeError, AttributeError):
                    invalid += 1
            items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return {"items": items, "invalid": invalid, "truncated": truncated}

        def selected(key):
            if key not in catalog:
                raise ValueError("artifact_not_found")
            return catalog[key]

        if action == "run":
            return run_view(self.read_json(selected(body.get("id")), self.roots[kind]))
        if action == "evaluation":
            path = selected(body.get("id"))
            return self.evaluation_view(self.report(path), path)
        left_path, right_path = (selected(body.get(k)) for k in ("baseline", "challenger"))
        left, right = self.report(left_path), self.report(right_path)
        left_review, left_view = self.review_at(left, left_path)
        right_review, right_view = self.review_at(right, right_path)
        both_verified = left_review is not None and right_review is not None
        compared = compare(
            left,
            right,
            left_review if both_verified else None,
            right_review if both_verified else None,
        )
        return {
            "paired_cases": len(compared["pairs"]),
            "changed_factors": compared["changed_factors"],
            "contract_regression": compared["gate"]["contract_regression"],
            "contract_pass_delta": sum(p["contract_pass_delta"] for p in compared["pairs"]),
            "duration_delta_ms": sum(p["duration_delta_ms"] for p in compared["pairs"])
            / len(compared["pairs"]),
            "review_status": "pending",
            "review_bindings": {
                "baseline": left_view["binding"],
                "challenger": right_view["binding"],
            },
            "review_hashes": {"baseline": left_view["hash"], "challenger": right_view["hash"]},
            "human_review_deltas": compared["human_review_deltas"],
            "quality_claim": False,
            "production_release": "not_evaluated",
        }


CHECKS = frozenset(
    {
        "service_accepted",
        "required_tools",
        "forbidden_tools_absent",
        "only_registered_read_tools",
        "draft_kind",
        "citations_present",
        "jobs_present",
        "city_constraint",
        "forbidden_draft_fragments_absent",
        "foreign_canary_absent",
        "trace_present",
    }
)

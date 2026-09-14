"""Allowlisted operational spans; never serialize arbitrary payload keys or strings."""

from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol

from getoffers_agent.runtime.events import RunEvent, project


def _span_id(event: RunEvent) -> str:
    return sha256(event.event_id.bytes).hexdigest()[:16]


def redacted_spans(events: Sequence[RunEvent]) -> list[dict]:
    project(list(events))  # Validate source ordering/schema before exporting.
    spans, active = [], {}
    for event in events:
        family, action = event.event_type.split(".")
        if action in {"started", "requested"} and family in {
            "workflow",
            "agent",
            "step",
            "model",
            "tool",
            "approval",
        }:
            if family == "tool" and action == "requested":
                continue
            parent = active.get(
                {
                    "agent": "workflow",
                    "step": "agent",
                    "model": "step",
                    "tool": "step",
                    "approval": "step",
                }.get(family, "")
            )
            span = {
                "trace_id": event.workflow_run_id.hex,
                "span_id": _span_id(event),
                "parent_span_id": parent["span_id"] if parent else None,
                "name": family,
                "start_time": event.occurred_at.isoformat(),
                "end_time": None,
                "status": "pending",
                "attributes": {},
            }
            spans.append(span)
            active[family] = span
        elif action in {"completed", "failed", "cancelled", "granted", "rejected", "expired"}:
            span = active.get(family)
            if span is None:
                continue
            span["end_time"] = event.occurred_at.isoformat()
            span["status"] = action
            data = event.payload
            attrs = span["attributes"]
            if "duration_ms" in data:
                attrs["duration_ms"] = data["duration_ms"]
            if family == "model":
                usage = data["response"]["usage"] if action == "completed" else data["usage"]
                attrs.update(
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cost=usage["cost"],
                    currency=usage["currency"],
                    source=usage["source"],
                )
            if "category" in data:
                attrs["error_category"] = data["category"]
            if family == "workflow":
                attrs["outcome_status"] = data["outcome"]["status"]
                attrs["error_category"] = data["outcome"]["reason"]
    return spans


class TraceExporter(Protocol):
    def export(self, spans: list[dict]) -> None: ...


def export_safely(events: Sequence[RunEvent], exporter: TraceExporter) -> bool:
    try:
        exporter.export(redacted_spans(events))
        return True
    except Exception:
        # This is a disposable projection. Do not feed backend failures into execution.
        return False

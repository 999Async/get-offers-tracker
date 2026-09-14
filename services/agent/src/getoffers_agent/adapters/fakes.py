"""Deterministic model and durable fake Product Port. Contains synthetic data only."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from getoffers_agent.domain.contracts import (
    ModelRequest,
    ModelResponse,
    Reconciliation,
    ToolContext,
    ToolResult,
    Usage,
    digest,
)


class FakeModelProvider:
    tokenizer_version = "synthetic-tokenizer-v1"

    def __init__(self, responses: list[ModelResponse], *, version="fake-model-v1"):
        self.responses = responses
        self.version = version + ":" + digest([r.model_dump(mode="json") for r in responses])
        self.calls: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        # Step-indexed responses survive process restart; a mutable provider cursor does not.
        index = min(request.step.number - 1, len(self.responses) - 1)
        if index < 0:
            raise ValueError("empty script")
        return self.responses[index].model_copy(deep=True)


class ProductPort(Protocol):
    async def get_candidate_state(self, context: ToolContext, arguments: dict) -> ToolResult: ...
    async def create_application_plan(
        self, context: ToolContext, arguments: dict
    ) -> ToolResult: ...
    async def lookup_application_plan(self, context: ToolContext) -> Reconciliation: ...


class FakeProductPort:
    def __init__(self, path: str | Path | None = None, *, lose_receipt=False):
        self.path = Path(path) if path else None
        self._records: dict[tuple[str, str, str], tuple[str, dict]] = {}
        self.read_calls = self.write_calls = self.lookup_calls = 0
        self.lose_receipt = lose_receipt
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(mode=0o600, exist_ok=True)
            self.path.chmod(0o600)
            with self._connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS fake_plans (
                    tenant TEXT, actor TEXT, key TEXT, payload_hash TEXT, result TEXT,
                    PRIMARY KEY (tenant, actor, key))""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    async def get_candidate_state(self, context: ToolContext, arguments: dict) -> ToolResult:
        self.read_calls += 1
        return ToolResult(value={"skills": ["Python"], "state_version": "synthetic-candidate-v1"})

    async def create_application_plan(self, context: ToolContext, arguments: dict) -> ToolResult:
        if not context.idempotency_key:
            raise ValueError("idempotency key required")
        self.write_calls += 1
        key = (context.security.tenant_id, context.security.actor_id, context.idempotency_key)
        payload_hash = digest({"actor": context.security.actor_id, "arguments": arguments})
        result = {"plan_id": "fake-" + context.idempotency_key[:16], **arguments}
        if self.path:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT payload_hash, result FROM fake_plans "
                    "WHERE tenant=? AND actor=? AND key=?",
                    key,
                ).fetchone()
                if row:
                    if row[0] != payload_hash:
                        raise ValueError("idempotency conflict")
                    result = json.loads(row[1])
                else:
                    db.execute(
                        "INSERT INTO fake_plans VALUES (?, ?, ?, ?, ?)",
                        (*key, payload_hash, json.dumps(result)),
                    )
        else:
            existing = self._records.get(key)
            if existing and existing[0] != payload_hash:
                raise ValueError("idempotency conflict")
            self._records.setdefault(key, (payload_hash, result))
            result = self._records[key][1]
        if self.lose_receipt:
            raise ConnectionError("synthetic lost receipt after commit")
        return ToolResult(value=result)

    async def lookup_application_plan(self, context: ToolContext) -> Reconciliation:
        self.lookup_calls += 1
        key = (context.security.tenant_id, context.security.actor_id, context.idempotency_key)
        if self.path:
            with self._connect() as db:
                row = db.execute(
                    "SELECT result FROM fake_plans WHERE tenant=? AND actor=? AND key=?", key
                ).fetchone()
            result = json.loads(row[0]) if row else None
        else:
            row = self._records.get(key)
            result = row[1] if row else None
        return Reconciliation(
            status="completed" if result else "not_found",
            result=ToolResult(value=result) if result else None,
        )


def synthetic_usage() -> Usage:
    return Usage(input_tokens=20, output_tokens=5, source="synthetic")

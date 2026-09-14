"""Developer reads use real frozen evaluations; private payloads never cross the API."""

import asyncio
import csv
import json
import shutil
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from getoffers_agent.assistant.eval_dataset import read_dataset
from getoffers_agent.assistant.eval_scripted import ScriptedProvider
from getoffers_agent.assistant.evaluation import DEFAULT_DATASET, FIELDS, evaluate, fingerprint
from getoffers_agent.assistant.observability import CAPABILITIES, ObservabilityReader
from getoffers_agent.assistant.server import make_assistant_server
from getoffers_agent.domain.contracts import digest


@pytest.fixture
def artifacts(tmp_path):
    dataset = read_dataset(DEFAULT_DATASET)
    out = tmp_path / "evals" / "first"
    report = asyncio.run(
        evaluate(
            dataset,
            lambda case: ScriptedProvider(case, dataset),
            out,
            mode="scripted",
            model_identity={"name": "scripted"},
        )
    )
    reader = ObservabilityReader(tmp_path / "audit", tmp_path / "evals", tmp_path / "access.jsonl")
    return reader, report, out


def call(reader, action, **fields):
    return reader.handle({"action": action, **fields}, "operator@example.test", CAPABILITIES)


def test_deny_before_reading_and_audit_identity_without_raw_email(artifacts, monkeypatch):
    reader, _, _ = artifacts
    monkeypatch.setattr(reader, "catalog", lambda _: pytest.fail("unauthorized read"))
    for caps in (frozenset(), frozenset({"metrics:read"})):
        with pytest.raises(PermissionError):
            reader.handle({"action": "evaluation"}, "operator@example.test", caps)
    with pytest.raises(PermissionError):
        call(reader, "trace:read:restricted")
    audit = reader.access_log.read_text()
    assert "operator@example.test" not in audit
    assert all(not json.loads(line)["allowed"] for line in audit.splitlines())
    assert reader.access_log.stat().st_mode & 0o777 == 0o600


def test_verified_evaluation_detail_is_redacted_and_unknown_cost_is_not_zero(artifacts):
    reader, report, out = artifacts
    listing = call(reader, "evaluations")
    assert listing["invalid"] == 0 and len(listing["items"]) == 1
    detail = call(reader, "evaluation", id=listing["items"][0]["id"])
    assert detail["total"] == detail["passed"] == 8
    assert detail["quality_claim"] is False
    assert detail["review_status"] == "pending" and detail["production_release"] == "not_evaluated"
    assert detail["cases"][0]["cost_usd"] is None
    assert detail["cases"][0]["input_tokens"] == 0
    serialized = json.dumps(detail, ensure_ascii=False)
    assert report["results"][0]["task"] not in serialized
    assert report["results"][0]["message"]["answer"] not in serialized
    assert str(out) not in serialized and "response" not in detail


def test_run_allowlist_discards_manifests_and_arbitrary_span_attributes(artifacts):
    reader, _, _ = artifacts
    reader.roots["runs"].mkdir()
    record = {
        "run_id": str(uuid4()),
        "config_hash": "a" * 64,
        "manifests": [{"private": "PRIVATE_CANARY"}],
        "spans": [
            {
                "name": "workflow",
                "start_time": "2026-09-12T00:00:00+00:00",
                "end_time": "2026-09-12T00:00:01+00:00",
                "status": "completed",
                "attributes": {
                    "outcome_status": "success",
                    "error_category": "PRIVATE_CANARY",
                    "prompt": "PRIVATE_CANARY",
                },
            },
            {
                "name": "model",
                "status": "failed",
                "attributes": {
                    "input_tokens": None,
                    "output_tokens": None,
                    "cost": None,
                    "response": "PRIVATE_CANARY",
                },
            },
        ],
    }
    (reader.roots["runs"] / "a.json").write_text(json.dumps(record))
    listing = call(reader, "runs")
    run = call(reader, "run", id=listing["items"][0]["id"])
    assert run["duration_ms"] == 1000 and run["input_tokens"] is None and run["cost_usd"] is None
    assert "PRIVATE_CANARY" not in json.dumps(run)
    assert "manifests" not in run


@pytest.mark.parametrize("damage", ["report", "trace", "missing", "symlink", "escape"])
def test_damaged_or_unsafe_reports_are_counted_and_never_served(artifacts, damage):
    reader, report, out = artifacts
    trace = out / report["results"][0]["trace"]
    key = call(reader, "evaluations")["items"][0]["id"]
    if damage == "report":
        report["summary"]["total"] += 1
    elif damage == "trace":
        trace.write_text("{}")
    elif damage == "missing":
        trace.unlink()
    else:
        external = out.parent / "outside.json"
        external.write_bytes(trace.read_bytes())
        if damage == "symlink":
            trace.unlink()
            trace.symlink_to(external)
        else:
            report["results"][0]["trace"] = "../outside.json"
            row = report["results"][0]
            row["result_hash"] = digest({k: v for k, v in row.items() if k != "result_hash"})
            report["report_hash"] = fingerprint(report)
    (out / "report.json").write_text(json.dumps(report))
    assert call(reader, "evaluations") == {"items": [], "invalid": 1, "truncated": False}
    with pytest.raises((ValueError, OSError)):
        call(reader, "evaluation", id=key)
    with pytest.raises(ValueError):
        call(reader, "evaluation", id="../../outside.json")


def test_compare_is_read_only_checks_pairing_and_preserves_gate(artifacts):
    reader, _, out = artifacts
    copy = out.parent / "second"
    shutil.copytree(out, copy)
    ids = [i["id"] for i in call(reader, "evaluations")["items"]]
    before = {str(p): p.read_bytes() for p in out.parent.rglob("*.json")}
    compared = call(reader, "compare", baseline=ids[0], challenger=ids[1])
    assert compared["paired_cases"] == 8 and compared["contract_pass_delta"] == 0
    assert compared["production_release"] == "not_evaluated" and compared["quality_claim"] is False
    assert before == {str(p): p.read_bytes() for p in out.parent.rglob("*.json")}
    report = json.loads((copy / "report.json").read_text())
    report["dataset_hash"] = "b" * 64
    report["report_hash"] = fingerprint(report)
    (copy / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="unpaired_experiment_identity"):
        call(reader, "compare", baseline=ids[0], challenger=ids[1])


def test_file_budget_and_invalid_query_reject_before_processing(artifacts):
    reader, _, out = artifacts
    with pytest.raises(ValueError):
        call(reader, "evaluation", id="x", path=str(out), capabilities=["trace:read:restricted"])
    with (out / "report.json").open("wb") as f:
        f.truncate(8_000_001)
    assert call(reader, "evaluations")["invalid"] == 1


def test_http_requires_opt_in_service_token_and_valid_local_session(artifacts):
    reader, _, _ = artifacts

    class Account:
        def handle(self, action, session):
            if action != "session" or session != "valid":
                raise PermissionError()
            return {"userId": "local-operator"}

    for enabled in (False, True):
        server = make_assistant_server(
            SimpleNamespace(provider=None),
            "t" * 32,
            local_account=Account(),
            observability=reader if enabled else None,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:

            def post(body, token="t" * 32, server=server):
                req = Request(
                    f"http://127.0.0.1:{server.server_port}/assistant/observability",
                    data=json.dumps(body).encode(),
                    headers={"Authorization": "Bearer " + token},
                )
                try:
                    with urlopen(req, timeout=5) as response:
                        assert response.headers["Cache-Control"] == "no-store"
                        return response.status, json.load(response)
                except HTTPError as exc:
                    return exc.code, json.load(exc)

            assert post({"action": "runs", "session": "invalid"})[0] == 403
            assert post({"action": "runs", "session": "valid"}, "wrong")[0] == 403
            assert post({"action": "capabilities", "session": "valid"})[0] == (
                200 if enabled else 403
            )
            if enabled:
                assert post({"action": "runs", "session": "valid", "actor": "forged"})[0] == 400
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def write_review(out, changes=None):
    with (out / "review.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for index, values in (changes or {}).items():
        rows[index].update(values)
    with (out / "reviewed.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_bound_reviews_keep_unknown_denominators_and_redact_identity_and_notes(artifacts):
    reader, _, out = artifacts
    key = call(reader, "evaluations")["items"][0]["id"]
    assert call(reader, "evaluation", id=key)["review"]["binding"] == "missing"
    write_review(out)
    first = call(reader, "evaluation", id=key)
    assert first["review"]["binding"] == "verified"
    assert first["review"]["dimensions"]["usefulness"]["pass_rate"] is None
    write_review(
        out, {0: {"usefulness": "fail", "reviewer": "PRIVATE_REVIEWER", "notes": "PRIVATE_REASON"}}
    )
    second = call(reader, "evaluation", id=key)
    dimension = second["review"]["dimensions"]["usefulness"]
    assert dimension == {
        "passed": 0,
        "failed": 1,
        "pending": 7,
        "not_applicable": 0,
        "reviewed": 1,
        "pass_rate": 0,
    }
    assert second["review"]["status"] == "rejected"
    assert second["review"]["hash"] != first["review"]["hash"]
    assert second["cases"][0]["review"]["usefulness"] == "fail"
    assert "PRIVATE_" not in json.dumps(second)
    assert not second["quality_claim"]


@pytest.mark.parametrize(
    "fault", ["answer", "symlink", "malformed", "short_row", "extra_cell", "large_field"]
)
def test_invalid_review_keeps_report_visible_and_never_scores(artifacts, fault):
    reader, _, out = artifacts
    write_review(out)
    path = out / "reviewed.csv"
    if fault == "answer":
        write_review(out, {0: {"回答": "PRIVATE_CHANGED_ANSWER"}})
    elif fault == "symlink":
        path.unlink()
        path.symlink_to(out / "review.csv")
    elif fault == "malformed":
        path.write_text(",".join(FIELDS) + '\n"unterminated')
    elif fault == "short_row":
        path.write_text(",".join(FIELDS) + "\nonly-one-field\n")
    elif fault == "extra_cell":
        path.write_text(path.read_text() + "," * len(FIELDS) + "\n")
    else:
        path.write_text(",".join(FIELDS) + "\n" + "x" * 150_000)
    listing = call(reader, "evaluations")
    assert listing["invalid"] == 0 and len(listing["items"]) == 1
    detail = call(reader, "evaluation", id=listing["items"][0]["id"])
    assert detail["review"]["binding"] == "invalid"
    assert detail["review"]["dimensions"] == {}
    assert all(c["review"] is None for c in detail["cases"])


def test_review_pairing_uses_only_mutually_scored_cases_and_fixed_sidecars(artifacts):
    reader, _, out = artifacts
    copy = out.parent / "second"
    shutil.copytree(out, copy)
    paths = {p.parent.name: key for key, p in reader.catalog("evaluations")[0].items()}
    args = {"baseline": paths["first"], "challenger": paths["second"]}
    write_review(out, {0: {"usefulness": "fail", "reviewer": "fixture", "notes": "fixture"}})
    assert call(reader, "compare", **args)["human_review_deltas"] == {}
    write_review(
        copy,
        {
            0: {"usefulness": "pass", "reviewer": "fixture"},
            1: {"usefulness": "pass", "reviewer": "fixture"},
        },
    )
    result = call(reader, "compare", **args)
    assert result["human_review_deltas"]["usefulness"] == {
        "paired_reviewed_cases": 1,
        "excluded_pending_or_na": 7,
        "pass_rate_delta": 1,
    }
    assert result["human_review_deltas"]["fact_support"]["pass_rate_delta"] is None
    assert not result["quality_claim"] and result["production_release"] == "not_evaluated"
    write_review(copy, {0: {"result_hash": "foreign"}})
    assert call(reader, "compare", **args)["human_review_deltas"] == {}

"""Evaluation integrity and report/review lifecycle, with isolated synthetic inputs."""

import asyncio
import csv
import json
from copy import deepcopy
from decimal import Decimal

import pytest

from getoffers_agent.assistant.config import load_model_config
from getoffers_agent.assistant.eval_dataset import read_dataset
from getoffers_agent.assistant.eval_scripted import ScriptedProvider
from getoffers_agent.assistant.evaluation import (
    DEFAULT_DATASET,
    FIELDS,
    compare,
    csv_text,
    evaluate,
    fingerprint,
    import_reviews,
    main,
    read_report,
    replay_case,
)
from getoffers_agent.assistant.provider import ChatProvider, ModelConfig


@pytest.fixture
def evaluated(tmp_path):
    dataset = read_dataset(DEFAULT_DATASET)
    report = asyncio.run(
        evaluate(
            dataset,
            lambda case: ScriptedProvider(case, dataset),
            tmp_path / "run",
            mode="scripted",
            model_identity={"name": "scripted"},
        )
    )
    return report, tmp_path / "run"


def write_rows(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def rows_at(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_full_contract_run_is_versioned_private_and_never_a_quality_claim(evaluated):
    report, out = evaluated
    assert report["summary"]["contracts_passed"] == report["summary"]["total"] == 8
    assert report["execution_mode"] == "scripted"
    assert report["summary"]["cost_usd"] is None
    assert report["summary"]["input_tokens"] == 0
    assert report["gate"] == {
        "human_review": "pending",
        "production_release": "not_evaluated",
        "quality_claim": False,
    }
    assert read_report(out / "report.json") == report
    for path in [out / "report.json", out / "review.csv", *list((out / "traces").glob("*.json"))]:
        assert path.stat().st_mode & 0o777 == 0o600
    assert (out / "review.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert "请先" not in json.dumps(report["gate"], ensure_ascii=False)
    rows = rows_at(out / "review.csv")
    assert rows[0]["任务"].startswith("帮我梳理")
    assert rows[0]["fact_support"] == "pending"
    assert json.loads(rows[0]["引用"])[0]["quote"]


def test_replay_is_read_only_and_checks_trace_integrity(evaluated, monkeypatch):
    report, out = evaluated

    def forbidden(*args):
        raise AssertionError("replay attempted a model request")

    monkeypatch.setattr(ChatProvider, "complete", forbidden)
    replay = replay_case(out / "report.json", "project")
    assert replay["model_called"] is False and replay["trace_verified"]
    trace_path = out / report["results"][0]["trace"]
    trace = json.loads(trace_path.read_text())
    trace["events"].pop()
    trace_path.write_text(json.dumps(trace))
    with pytest.raises(ValueError, match="trace_fingerprint"):
        replay_case(out / "report.json", "project")


def test_review_reimport_binds_exact_outputs_and_keeps_pending_unknown(evaluated):
    report, out = evaluated
    assert import_reviews(report, out / "review.csv")["review_status"] == "pending"
    rows = rows_at(out / "review.csv")
    for row in rows:
        row.update(fact_support="pass", usefulness="pass", reviewer="人工审核员")
        if row["jd_fit"] != "n/a":
            row["jd_fit"] = "pass"
    write_rows(out / "reviewed.csv", rows)
    result = import_reviews(report, out / "reviewed.csv")
    assert result["review_status"] == "reviewed"
    assert result["production_release"] == "not_evaluated" and not result["quality_claim"]
    rows[0].update(fact_support="fail", notes="该说法缺少证据")
    write_rows(out / "rejected.csv", rows)
    assert import_reviews(report, out / "rejected.csv")["review_status"] == "rejected"


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "other_run",
        "answer_changed",
        "no_reviewer",
        "no_reason",
        "na_required",
        "bad_label",
    ],
)
def test_invalid_review_is_rejected(evaluated, fault):
    report, out = evaluated
    rows = rows_at(out / "review.csv")
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows[-1] = rows[0]
    elif fault == "other_run":
        rows[0]["report_hash"] = "foreign"
    elif fault == "answer_changed":
        rows[0]["回答"] = "已修改回答"
    elif fault == "no_reviewer":
        rows[0]["usefulness"] = "pass"
    elif fault == "no_reason":
        rows[0].update(usefulness="fail", reviewer="人")
    elif fault == "na_required":
        rows[0]["fact_support"] = "n/a"
    else:
        rows[0]["usefulness"] = "excellent"
    write_rows(out / "bad.csv", rows)
    with pytest.raises(ValueError):
        import_reviews(report, out / "bad.csv")


def test_paired_differences_detect_regression_and_unknown_cost(evaluated):
    left, _ = evaluated
    right = deepcopy(left)
    right["results"][0].update(
        contracts_passed=False, duration_ms=left["results"][0]["duration_ms"] + 10
    )
    right["model"] = {"name": "challenger"}
    result = compare(left, right)
    assert result["pairs"][0]["contract_pass_delta"] == -1
    assert result["pairs"][0]["duration_delta_ms"] == 10
    assert result["pairs"][0]["cost_delta_usd"] is None
    assert result["gate"]["contract_regression"]
    assert result["changed_factors"] == ["model"]
    assert not result["gate"]["quality_claim"]


@pytest.mark.parametrize(
    "fault",
    ["dataset_hash", "execution_mode", "grader_version", "missing", "duplicate", "input_hash"],
)
def test_unpaired_reports_are_rejected(evaluated, fault):
    left, _ = evaluated
    right = deepcopy(left)
    if fault == "missing":
        right["results"].pop()
    elif fault == "duplicate":
        right["results"][-1] = right["results"][0]
    elif fault == "input_hash":
        right["results"][0]["input_hash"] = "changed"
    else:
        right[fault] = "different"
    with pytest.raises(ValueError):
        compare(left, right)


def test_existing_report_is_never_overwritten_and_changed_result_is_detected(evaluated):
    report, out = evaluated
    original = (out / "report.json").read_bytes()
    dataset = read_dataset(DEFAULT_DATASET)
    with pytest.raises(FileExistsError):
        asyncio.run(
            evaluate(
                dataset,
                lambda case: ScriptedProvider(case, dataset),
                out,
                mode="scripted",
                model_identity={},
            )
        )
    assert (out / "report.json").read_bytes() == original
    report["results"][0]["contracts_passed"] = False
    report["report_hash"] = fingerprint(report)
    (out / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="result_fingerprint"):
        read_report(out / "report.json")


def test_model_failure_does_not_disappear_from_denominator(tmp_path):
    dataset = read_dataset(DEFAULT_DATASET)

    class Broken:
        version = tokenizer_version = "broken-test-provider"

        async def complete(self, request):
            raise OSError("private-key-and-provider-detail")

    report = asyncio.run(
        evaluate(
            dataset,
            lambda case: Broken(),
            tmp_path / "failure",
            mode="scripted",
            model_identity={},
            limit=2,
        )
    )
    assert report["summary"]["total"] == 2 and report["summary"]["contracts_passed"] == 0
    assert report["summary"]["input_tokens"] is None
    assert all(not row["usage_complete"] and row["failure"] for row in report["results"])
    assert "private-key-and-provider-detail" not in json.dumps(report)


@pytest.mark.parametrize("text", ['=HYPERLINK("evil")', " +cmd", "@SUM(1)", "\t=1", "\n-2"])
def test_csv_cells_cannot_become_formulas(text):
    assert csv_text(text).startswith("'")


def test_env_file_is_data_and_secret_never_enters_config_repr(tmp_path):
    target = tmp_path / "should-not-exist"
    path = tmp_path / "model.env"
    key = f"$(touch {target})`whoami`"
    path.write_text(
        f'\ufeffLLM_MODEL=test-model\nLLM_API_KEY="{key}"\nLLM_INPUT_PRICE_PER_MILLION=1.5\nLLM_OUTPUT_PRICE_PER_MILLION=2\n'
    )
    config = load_model_config(path, environ={})
    assert config.api_key == key and not target.exists()
    assert key not in repr(config)
    assert config.input_price == Decimal("1.5") and config.priced
    assert load_model_config(environ={}) is None


@pytest.mark.parametrize(
    "content",
    [
        "LLM_MODEL=a\nLLM_MODEL=b",
        "OTHER=private",
        "LLM_API_KEY=private",
        "LLM_MODEL=x\nLLM_API_KEY=x\nLLM_MAX_OUTPUT_TOKENS=private",
    ],
)
def test_bad_model_configuration_is_rejected_without_secret_diagnostics(tmp_path, content):
    path = tmp_path / "model.env"
    path.write_text(content)
    with pytest.raises(ValueError) as error:
        load_model_config(path, environ={})
    assert "private" not in str(error.value)


def test_live_cli_missing_configuration_never_falls_back(tmp_path, monkeypatch, capsys):
    for name in ("LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.argv", ["evaluation", "run", "--out", str(tmp_path / "live")])
    assert main() == 2
    assert "MODEL_NOT_CONFIGURED" in capsys.readouterr().out
    assert not (tmp_path / "live").exists()
    with pytest.raises(ValueError):
        ModelConfig("https:///", "model", "key")


def test_paired_human_grades_exclude_pending_and_na(evaluated):
    report, out = evaluated
    baseline = import_reviews(report, out / "review.csv")
    challenger = deepcopy(baseline)
    challenger["reviews"][0]["usefulness"] = "pass"
    delta = compare(report, report, baseline, challenger)["human_review_deltas"]["usefulness"]
    assert delta["paired_reviewed_cases"] == 0 and delta["pass_rate_delta"] is None
    baseline["reviews"][0]["usefulness"] = "fail"
    delta = compare(report, report, baseline, challenger)["human_review_deltas"]["usefulness"]
    assert delta["paired_reviewed_cases"] == 1 and delta["pass_rate_delta"] == 1
    assert delta["excluded_pending_or_na"] == 7
    with pytest.raises(ValueError, match="both_review_files_required"):
        compare(report, report, baseline)

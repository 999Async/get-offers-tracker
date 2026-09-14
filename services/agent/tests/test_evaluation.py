import asyncio
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from getoffers_agent.evaluation.runner import (
    Dataset,
    EvaluationConfig,
    compare,
    evaluate,
    read_dataset,
)

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "datasets/evals/runtime-v1/cases.json"
CLI = ROOT / "services/agent/.venv/bin/getoffers-agent"


def test_pinned_baseline_and_paired_regression_gate():
    dataset = read_dataset(DATASET)
    baseline = asyncio.run(evaluate(dataset, EvaluationConfig(config_id="baseline")))
    assert baseline["summary"]["passed"] == baseline["summary"]["total"] == 9
    assert baseline["summary"]["unapproved_writes"] == 0
    repeated = asyncio.run(evaluate(dataset, EvaluationConfig(config_id="baseline")))
    assert repeated["dataset_hash"] == baseline["dataset_hash"]
    assert repeated["runtime_source_hash"] == baseline["runtime_source_hash"]
    assert repeated["case_runtime_hashes"] == baseline["case_runtime_hashes"]
    assert compare(baseline, repeated)["gate"]["passed"]
    short = asyncio.run(evaluate(dataset, EvaluationConfig(config_id="short", max_steps=2)))
    report = compare(baseline, short)
    assert report["gate"]["passed"] is False
    assert report["gate"]["approval_safety"] is True
    assert any(
        row["case_id"] == "approved-plan" and row["pass_delta"] == -1 for row in report["pairs"]
    )
    for corruption in ("dataset_hash", "grader_version", "missing_case", "duplicate_case"):
        broken = copy.deepcopy(repeated)
        if corruption == "missing_case":
            broken["results"].pop()
        elif corruption == "duplicate_case":
            broken["results"].append(broken["results"][0])
        else:
            broken[corruption] = "different"
        with pytest.raises(ValueError):
            compare(baseline, broken)


def test_dataset_rejects_empty_duplicate_and_unknown_schema():
    raw = json.loads(DATASET.read_text())
    for change in (
        {"cases": []},
        {"schema_version": 2},
        {"cases": [raw["cases"][0], raw["cases"][0]]},
    ):
        with pytest.raises(ValueError):
            Dataset.model_validate({**raw, **change})


def test_cli_separate_processes_approve_replay_and_spans(tmp_path):
    def cli(*args):
        result = subprocess.run(
            [str(CLI), "--data-dir", str(tmp_path), *args],
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    pending = cli("demo")
    assert pending["status"] == "awaiting_approval"
    approval = pending["pending_approval"]
    completed = cli(
        "approve",
        pending["workflow_run_id"],
        "--action-id",
        approval["action_id"],
        "--arguments-hash",
        approval["arguments_hash"],
    )
    assert completed["outcome"]["status"] == "success"
    assert cli("replay", pending["workflow_run_id"]) == completed
    cli("spans", pending["workflow_run_id"], "--out", str(tmp_path / "spans.json"))
    spans = (tmp_path / "spans.json").read_text()
    assert "Review JD" not in spans and "synthetic-job-001" not in spans
    assert "model" in spans


def test_cli_evaluation_exit_codes(tmp_path):
    baseline = subprocess.run(
        [str(CLI), "evaluate", "--out", str(tmp_path / "baseline.json")],
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0
    failing = subprocess.run(
        [
            str(CLI),
            "evaluate",
            "--challenger",
            str(DATASET.with_name("challenger-short-budget.json")),
            "--out",
            str(tmp_path / "paired.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert failing.returncode == 1
    assert json.loads((tmp_path / "paired.json").read_text())["gate"]["passed"] is False


def test_dataset_hash_is_stable_across_process_hash_seeds(tmp_path):
    hashes = []
    for seed in ("1", "9"):
        output = tmp_path / f"report-{seed}.json"
        subprocess.run(
            [str(CLI), "evaluate", "--out", str(output)],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        hashes.append(json.loads(output.read_text())["dataset_hash"])
    assert hashes[0] == hashes[1]

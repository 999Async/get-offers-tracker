"""Local account discovery never becomes a scripted fallback or a quality claim."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from getoffers_agent.assistant import eval_codex
from getoffers_agent.assistant.evaluation import main


@pytest.fixture
def discovery(monkeypatch):
    account = AsyncMock(
        return_value={
            "email": "PRIVATE_EMAIL",
            "models": [{"id": "first", "default": False}, {"id": "default", "default": True}],
        }
    )
    process = SimpleNamespace(
        returncode=0, communicate=AsyncMock(return_value=(b"codex-cli 0.146.0\n", None))
    )
    spawn = AsyncMock(return_value=process)
    cleanup = AsyncMock()
    monkeypatch.setattr(eval_codex, "account_info", account)
    monkeypatch.setattr(eval_codex, "executable", lambda: "/test/codex")
    monkeypatch.setattr(eval_codex.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(eval_codex, "terminate", cleanup)
    return account, process, spawn, cleanup


@pytest.mark.parametrize("requested, selected", [(None, "default"), ("first", "first")])
def test_provider_records_account_model_and_cli_version_without_identity(
    discovery, requested, selected
):
    _, _, spawn, cleanup = discovery
    provider, identity = asyncio.run(eval_codex.local_provider(requested))
    assert identity["model_name"] == selected
    assert identity["provider_version"] == provider.version
    assert identity["cli_version"] == "codex-cli 0.146.0"
    assert not identity["pricing_configured"] and "PRIVATE_EMAIL" not in json.dumps(identity)
    assert spawn.call_args.args == ("/test/codex", "--version")
    cleanup.assert_awaited_once()


@pytest.mark.parametrize("fault", ["login", "empty", "unknown", "version", "timeout"])
def test_discovery_failures_stop_and_cleanup(discovery, fault):
    account, process, spawn, cleanup = discovery
    if fault == "login":
        account.side_effect = ValueError("PRIVATE_ACCOUNT_ERROR")
    elif fault == "empty":
        account.return_value["models"] = []
    elif fault == "version":
        process.communicate.return_value = (b"unexpected version", None)
    elif fault == "timeout":
        process.communicate.side_effect = TimeoutError()
    with pytest.raises((ValueError, TimeoutError)):
        asyncio.run(eval_codex.local_provider("missing" if fault == "unknown" else None))
    assert cleanup.await_count == (1 if fault in {"version", "timeout"} else 0)
    if fault not in {"version", "timeout"}:
        spawn.assert_not_called()


def test_cli_check_inspects_account_without_inference(discovery, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["evaluation", "check", "--provider", "codex"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["account_checked"] and not output["inference_checked"]
    assert "PRIVATE_EMAIL" not in json.dumps(output)


def test_cli_codex_failure_never_creates_scripted_report(discovery, monkeypatch, tmp_path, capsys):
    discovery[0].side_effect = ValueError("PRIVATE_ACCOUNT_ERROR")
    out = tmp_path / "missing"
    monkeypatch.setattr("sys.argv", ["evaluation", "run", "--provider", "codex", "--out", str(out)])
    assert main() == 2 and not out.exists()
    assert "PRIVATE_ACCOUNT_ERROR" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "options",
    [
        ["--mode", "scripted", "--provider", "codex"],
        ["--env-file", "anything", "--provider", "codex"],
        ["--model", "first"],
    ],
)
def test_incompatible_options_reject_before_account_read(discovery, monkeypatch, tmp_path, options):
    monkeypatch.setattr("sys.argv", ["evaluation", "run", "--out", str(tmp_path / "new"), *options])
    assert main() == 2
    discovery[0].assert_not_called()


def test_existing_output_is_rejected_before_account_read(discovery, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv", ["evaluation", "run", "--provider", "codex", "--out", str(tmp_path)]
    )
    assert main() == 2
    discovery[0].assert_not_called()

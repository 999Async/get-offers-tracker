import asyncio
import json
from types import SimpleNamespace

import pytest

from getoffers_agent.assistant.local_account import LocalAccount


@pytest.fixture
def local(tmp_path):
    state = {
        "email": "real@example.com",
        "models": [{"id": "available-model", "name": "Model", "default": True}],
    }

    async def inspect(refresh=False):
        return dict(state)

    service = SimpleNamespace(provider=None)
    return LocalAccount(service, tmp_path / "model.json", inspect), state


def test_connect_uses_codex_identity_and_persists_only_model(local):
    manager, _ = local
    assert manager.handle("status") == {"local": True, "connected": False}
    result = manager.handle("connect")
    session = result["session"]
    identity = manager.handle("session", session)
    assert identity["userId"].startswith("codex-local:")
    assert identity["email"] == "real@example.com"
    manager.handle("model", session, "available-model")
    assert json.loads(manager.config_path.read_text()) == {
        "provider": "codex",
        "model": "available-model",
    }
    assert manager.config_path.stat().st_mode & 0o777 == 0o600
    assert "session" not in manager.handle("status", session)


def test_forged_expired_and_disconnected_sessions_fail(local):
    manager, _ = local
    with pytest.raises(PermissionError):
        manager.handle("session", "fake")
    session = manager.handle("connect")["session"]
    manager.sessions[session] = ("real@example.com", 0)
    with pytest.raises(PermissionError):
        manager.handle("session", session)
    session = manager.handle("connect")["session"]
    manager.handle("disconnect", session)
    with pytest.raises(PermissionError):
        manager.handle("session", session)


def test_account_change_revokes_old_sessions(local):
    manager, state = local
    session = manager.handle("connect")["session"]
    state["email"] = "other@example.com"
    manager.checked_at = 0
    with pytest.raises(PermissionError):
        manager.handle("session", session)


def test_configuration_needs_session_and_known_model(local):
    manager, _ = local
    with pytest.raises(PermissionError):
        manager.handle("model", "", "available-model")
    session = manager.handle("connect")["session"]
    with pytest.raises(ValueError):
        manager.handle("model", session, "; arbitrary shell command")


def test_account_lookup_failure_revokes_sessions(local):
    manager, _ = local
    session = manager.handle("connect")["session"]

    async def failing(refresh=False):
        raise OSError("private diagnostic")

    manager.inspect = failing
    manager.checked_at = 0
    with pytest.raises(ValueError, match="CODEX_LOGIN_REQUIRED"):
        manager.handle("session", session)
    assert not manager.sessions


def test_local_endpoint_unavailable_unless_enabled():
    import threading
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from getoffers_agent.assistant.server import make_assistant_server

    token = "t" * 32
    server = make_assistant_server(SimpleNamespace(provider=None), token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call():
        with pytest.raises(HTTPError) as exc:
            urlopen(
                Request(
                    f"http://127.0.0.1:{server.server_port}/assistant/local",
                    data=b'{"action":"connect"}',
                    headers={"Authorization": "Bearer " + token},
                )
            )
        assert exc.value.code == 403

    try:
        call()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def fake_cli(tmp_path, monkeypatch, events, sleep=False):
    import sys

    from getoffers_agent.assistant import codex

    script = tmp_path / "codex"
    script.write_text(
        f"#!{sys.executable}\nimport json, os, sys, time\n"
        "sys.stdin.read()\n"
        f"open({str(tmp_path / 'invocation.json')!r}, 'w').write(json.dumps("
        "{'args': sys.argv, 'secret_present': 'AGENT_ASSISTANT_TOKEN' in os.environ, "
        "'pid': os.getpid()}))\n"
        + ("time.sleep(60)\n" if sleep else "")
        + "\n".join(f"print({json.dumps(event)!r}, flush=True)" for event in events)
    )
    script.chmod(0o700)
    monkeypatch.setattr(codex, "executable", lambda: str(script))
    monkeypatch.setenv("AGENT_ASSISTANT_TOKEN", "sensitive-service-token")
    return codex.CodexProvider("available-model")


def model_request():
    return SimpleNamespace(
        blocks=[
            SimpleNamespace(kind="session", content={"history": []}),
            SimpleNamespace(kind="workflow", content="career"),
            SimpleNamespace(kind="tools", content=[]),
        ]
    )


def test_codex_uses_final_output_and_measured_usage_without_forwarding_secrets(
    tmp_path, monkeypatch
):
    answer = json.dumps(
        {"kind": "answer", "name": "", "payload": json.dumps({"answer": "请先选择材料。"})}
    )
    events = [
        {"type": "item.completed", "item": {"type": "error", "message": "nonfatal CLI warning"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
        {"type": "turn.completed", "usage": {"input_tokens": 90, "output_tokens": 20}},
    ]
    result = asyncio.run(fake_cli(tmp_path, monkeypatch, events).complete(model_request()))
    assert "请先选择材料" in result.answer
    assert result.usage.input_tokens == 90
    invocation = json.loads((tmp_path / "invocation.json").read_text())
    assert not invocation["secret_present"]
    assert "--ignore-user-config" in invocation["args"]
    assert "--ephemeral" in invocation["args"]
    assert invocation["args"][invocation["args"].index("--sandbox") + 1] == "read-only"


@pytest.mark.parametrize(
    "events",
    [
        [{"type": "turn.failed", "error": {"message": "private"}}],
        [{"type": "item.started", "item": {"type": "command_execution", "command": "bad"}}],
        [{"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}}],
        [{"type": "turn.completed", "usage": {"input_tokens": None, "output_tokens": 3}}],
    ],
)
def test_codex_failure_never_becomes_fake_answer(tmp_path, monkeypatch, events):
    from getoffers_agent.runtime.engine import ProviderFailure

    with pytest.raises(ProviderFailure):
        asyncio.run(fake_cli(tmp_path, monkeypatch, events).complete(model_request()))


def test_cancellation_reaps_cli_process(tmp_path, monkeypatch):
    import os

    provider = fake_cli(tmp_path, monkeypatch, [], sleep=True)

    async def run():
        task = asyncio.create_task(provider.complete(model_request()))
        for _ in range(100):
            if (tmp_path / "invocation.json").exists():
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    pid = json.loads((tmp_path / "invocation.json").read_text())["pid"]
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)

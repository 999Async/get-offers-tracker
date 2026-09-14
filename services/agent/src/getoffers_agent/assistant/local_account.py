"""Explicit, loopback-only browser sessions bound to the signed-in Codex account."""

import asyncio
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path

from getoffers_agent.assistant.codex import CodexProvider, account_info


class LocalAccount:
    def __init__(self, service, config_path: Path, inspect=account_info):
        self.service = service
        self.config_path = config_path
        self.inspect = inspect
        self.sessions = {}
        self.lock = threading.RLock()
        self.checked_at = 0
        self.account = None
        self.model = ""
        if config_path.exists():
            self.model = json.loads(config_path.read_text()).get("model", "")

    def current(self, refresh=False):
        if refresh or time.monotonic() - self.checked_at > 30:
            try:
                account = asyncio.run(self.inspect(refresh))
            except Exception:
                self.account = None
                self.checked_at = 0
                self.sessions.clear()
                raise ValueError("CODEX_LOGIN_REQUIRED") from None
            if self.account and account["email"] != self.account["email"]:
                self.sessions.clear()
            self.account = account
            self.checked_at = time.monotonic()
        return self.account

    def identity(self, session):
        account = self.current()
        now = time.time()
        self.sessions = {key: value for key, value in self.sessions.items() if value[1] > now}
        saved = self.sessions.get(session)
        if not saved or saved[0] != account["email"]:
            raise PermissionError("UNAUTHORIZED")
        # Separate namespace: local data is not silently merged with a hosted account.
        return {
            "userId": "codex-local:"
            + hashlib.sha256(account["email"].lower().encode()).hexdigest(),
            "email": account["email"],
            "displayName": account["email"],
        }

    def handle(self, action, session="", model=None):
        with self.lock:
            if action == "disconnect":
                self.sessions.pop(session, None)
                return {"connected": False}
            if action in {"connect", "model"} and getattr(self.service, "active", None):
                raise ValueError("ASSISTANT_BUSY")
            if action == "connect":
                account = self.current(refresh=True)
                if not self.model or self.model not in {m["id"] for m in account["models"]}:
                    self.model = next(
                        (m["id"] for m in account["models"] if m["default"]),
                        account["models"][0]["id"],
                    )
                session = secrets.token_urlsafe(32)
                if len(self.sessions) >= 16:
                    self.sessions.pop(next(iter(self.sessions)))
                self.sessions[session] = (account["email"], time.time() + 8 * 3600)
                self.service.provider = CodexProvider(self.model)
                return {"session": session, "connected": True}
            if action == "session":
                return self.identity(session)
            if action == "status":
                try:
                    user = self.identity(session)
                except PermissionError:
                    return {"local": True, "connected": False}
                return {
                    "local": True,
                    "connected": True,
                    "user": user,
                    "model": self.model,
                    "models": self.account["models"],
                    "provider": "codex",
                }
            if action == "model":
                self.identity(session)
                if model not in {m["id"] for m in self.account["models"]}:
                    raise ValueError("INVALID_MODEL")
                self.model = model
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.config_path.with_suffix(".tmp")
                temp.write_text(json.dumps({"provider": "codex", "model": model}))
                temp.chmod(0o600)
                temp.replace(self.config_path)
                self.service.provider = CodexProvider(model)
                return {"model": model}
            raise ValueError("INVALID_REQUEST")

"""Authenticated local streaming endpoint for the conversational assistant."""

import argparse
import asyncio
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from pydantic import Field

from getoffers_agent.assistant.config import load_model_config
from getoffers_agent.assistant.contracts import ChatRequest
from getoffers_agent.assistant.provider import ChatProvider
from getoffers_agent.assistant.service import AssistantService
from getoffers_agent.career.server import NoRedirect
from getoffers_agent.domain.contracts import Contract, SecurityContext


class ReadPorts:
    def __init__(self, endpoints):
        self.endpoints = endpoints
        for url, token in endpoints.values():
            if not url or not token:
                continue
            parsed = urlparse(url)
            if (
                len(token) < 32
                or parsed.username
                or parsed.password
                or not (
                    parsed.scheme == "https"
                    or parsed.scheme == "http"
                    and parsed.hostname in {"127.0.0.1", "localhost"}
                )
            ):
                raise ValueError("invalid_read_service_configuration")

    def call(self, name, security, body):
        url, token = self.endpoints.get(name, ("", ""))
        if not url or not token:
            raise OSError("read_service_unavailable")
        request = Request(
            url.rstrip("/") + "/" + name,
            data=json.dumps(
                {**body, "actor_id": security.actor_id, "tenant_id": security.tenant_id}
            ).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)

    def knowledge(self, security, action, payload):
        return self.call("knowledge", security, {"action": action, "payload": payload})

    def search(self, security, request):
        return self.call("search", security, {"request": request.model_dump(mode="json")})


class Envelope(Contract):
    actor_id: str = Field(min_length=1, max_length=300)
    tenant_id: str = Field(min_length=1, max_length=300)
    payload: ChatRequest


def make_assistant_server(service, token, port=0, local_account=None, observability=None):
    if len(token) < 32:
        raise ValueError("assistant_token_too_short")

    class Handler(BaseHTTPRequestHandler):
        def authorized(self):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            status = 200 if self.path == "/assistant/status" and self.authorized() else 403
            body = json.dumps(
                {"configured": bool(service.provider)}
                if status == 200
                else {"error": "UNAUTHORIZED"}
            ).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def emit(self, data):
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode() + b"\n")
            self.wfile.flush()

        async def stream(self, envelope):
            security = SecurityContext(
                actor_id=envelope.actor_id,
                tenant_id=envelope.tenant_id,
                capabilities=frozenset({"assistant:read:self"}),
            )
            stream = service.chat(envelope.payload, security)
            next_event = None
            try:
                while True:
                    next_event = asyncio.create_task(anext(stream))
                    while not next_event.done():
                        done, _ = await asyncio.wait({next_event}, timeout=1)
                        if not done:
                            self.emit({"type": "ping"})
                    try:
                        event = next_event.result()
                    except StopAsyncIteration:
                        break
                    self.emit(event)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                # A browser stop/disconnect cancels the loop before any further tool/model call.
                pass
            except Exception:
                self.emit({"type": "error", "error": "ASSISTANT_UNAVAILABLE"})
            finally:
                if next_event and not next_event.done():
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
                await stream.aclose()

        def do_POST(self):
            if self.path == "/assistant/observability":
                self.connection.settimeout(15)
                try:
                    if not self.authorized() or not local_account or not observability:
                        raise PermissionError()
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 2048:
                        raise ValueError()
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError()
                    account = local_account.handle("session", body.pop("session", ""))
                    from getoffers_agent.assistant.observability import CAPABILITIES

                    result = observability.handle(body, account["userId"], CAPABILITIES)
                    status = 200
                except PermissionError:
                    status, result = 403, {"error": "DEVELOPER_ACCESS_DENIED"}
                except (ValueError, KeyError, TypeError, AttributeError, OSError):
                    status, result = 400, {"error": "ARTIFACT_UNAVAILABLE_OR_INCOMPATIBLE"}
                data = json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path == "/assistant/local" and local_account and self.authorized():
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 2048:
                        raise ValueError("INVALID_REQUEST")
                    body = json.loads(self.rfile.read(size))
                    result = local_account.handle(
                        body["action"], body.get("session", ""), body.get("model")
                    )
                    status = 200
                except PermissionError:
                    status, result = 401, {"error": "UNAUTHORIZED"}
                except (ValueError, KeyError, TypeError):
                    status, result = 400, {"error": "CODEX_CONNECTION_FAILED"}
                data = json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.connection.settimeout(15)
            try:
                if self.path != "/assistant" or not self.authorized():
                    raise PermissionError()
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 384000:
                    raise ValueError()
                envelope = Envelope.model_validate_json(self.rfile.read(size))
                if envelope.actor_id != envelope.tenant_id:
                    raise PermissionError()
            except (PermissionError, ValueError) as exc:
                self.send_response(403 if isinstance(exc, PermissionError) else 400)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            asyncio.run(self.stream(envelope))

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="ReAct career assistant")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--audit-dir", type=Path, default=Path(".agent-data/assistant/audit"))
    parser.add_argument("--env-file", type=Path, help="Local LLM settings only; never executed")
    parser.add_argument(
        "--local-codex", action="store_true", help="Enable local Codex account sessions"
    )
    parser.add_argument(
        "--developer-tools",
        action="store_true",
        help="Allow the local Codex operator to inspect redacted runs and evaluations",
    )
    parser.add_argument("--evaluation-dir", type=Path, default=Path(".agent-data/assistant-eval"))
    args = parser.parse_args()
    config = load_model_config(args.env_file)
    ports = ReadPorts(
        {
            "knowledge": (
                os.environ.get("AGENT_KNOWLEDGE_URL", ""),
                os.environ.get("AGENT_KNOWLEDGE_TOKEN", ""),
            ),
            "search": (
                os.environ.get("AGENT_SEARCH_URL", ""),
                os.environ.get("AGENT_SEARCH_TOKEN", ""),
            ),
        }
    )
    mode = os.environ.get("ASSISTANT_RETRIEVAL_MODE", "lexical")
    if mode not in {"lexical", "dense", "hybrid", "hybrid-rerank"}:
        raise ValueError("invalid_retrieval_mode")
    service = AssistantService(
        ChatProvider(config) if config else None, ports, args.audit_dir, mode
    )
    local_account = None
    observability = None
    if args.developer_tools and not args.local_codex:
        parser.error("--developer-tools requires --local-codex")
    if args.local_codex:
        from getoffers_agent.assistant.local_account import LocalAccount

        local_account = LocalAccount(service, Path(".agent-data/assistant/local-model.json"))
        if args.developer_tools:
            from getoffers_agent.assistant.observability import ObservabilityReader

            observability = ObservabilityReader(
                args.audit_dir, args.evaluation_dir, Path(".agent-data/developer/access.jsonl")
            )
    with make_assistant_server(
        service,
        os.environ.get("AGENT_ASSISTANT_TOKEN", ""),
        args.port,
        local_account,
        observability,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()

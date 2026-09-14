"""Authenticated loopback transport. Production hosting is intentionally separate."""

import argparse
import asyncio
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field

from getoffers_agent.adapters.events import SQLiteEventStore
from getoffers_agent.career.discovery import CAPABILITIES, CareerService
from getoffers_agent.domain.contracts import Contract, RuntimeFault, SecurityContext


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RemotePorts:
    def __init__(
        self, knowledge_url, knowledge_token, search_url, search_token, product_url, product_token
    ):
        self.endpoints = {
            "knowledge": (knowledge_url, knowledge_token),
            "search": (search_url, search_token),
            "product": (product_url, product_token),
        }
        for url, token in self.endpoints.values():
            parsed = urlparse(url)
            if (
                len(token) < 32
                or parsed.username
                or parsed.password
                or not (
                    parsed.scheme == "https"
                    or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
                )
            ):
                raise ValueError("invalid_service_configuration")

    def call(self, endpoint, security, body):
        url, token = self.endpoints[endpoint]
        raw = json.dumps(
            {**body, "actor_id": security.actor_id, "tenant_id": security.tenant_id},
            ensure_ascii=False,
        ).encode()
        request = Request(
            url,
            data=raw,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            return json.load(response)

    def knowledge(self, security, action, payload):
        return self.call("knowledge", security, {"action": action, "payload": payload})

    def search(self, security, request):
        return self.call("search", security, {"request": request.model_dump(mode="json")})

    def product(self, security, action, payload):
        return self.call("product", security, {"action": action, "payload": payload})


class Envelope(Contract):
    actor_id: str = Field(min_length=1, max_length=300)
    tenant_id: str = Field(min_length=1, max_length=300)
    action: str
    payload: dict


def make_career_server(service, token, port=0):
    if len(token) < 32:
        raise ValueError("career_token_too_short")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(180)
            try:
                if self.path != "/career":
                    raise ValueError("invalid_path")
                if not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + token
                ):
                    raise PermissionError("unauthorized")
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16384:
                    raise ValueError("invalid_length")
                envelope = Envelope.model_validate_json(self.rfile.read(length))
                if envelope.actor_id != envelope.tenant_id:
                    raise PermissionError("invalid_tenant")
                security = SecurityContext(
                    actor_id=envelope.actor_id,
                    tenant_id=envelope.tenant_id,
                    capabilities=CAPABILITIES,
                )
                result = asyncio.run(service.dispatch(envelope.action, envelope.payload, security))
                status = 200
            except PermissionError:
                status, result = 403, {"error": "NOT_AUTHORIZED"}
            except (ValueError, RuntimeFault):
                status, result = 400, {"error": "INVALID_OR_STALE_RUN"}
            except Exception:
                status, result = 503, {"error": "CAREER_UNAVAILABLE"}
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Career discovery service (no LLM baseline)")
    parser.add_argument("--data-dir", type=Path, default=Path(".agent-data/career"))
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    ports = RemotePorts(
        os.environ["AGENT_KNOWLEDGE_URL"].rstrip("/") + "/knowledge",
        os.environ["AGENT_KNOWLEDGE_TOKEN"],
        os.environ["AGENT_SEARCH_URL"].rstrip("/") + "/search",
        os.environ["AGENT_SEARCH_TOKEN"],
        os.environ["AGENT_PRODUCT_URL"].rstrip("/") + "/api/agent-plans",
        os.environ["AGENT_PRODUCT_TOKEN"],
    )
    service = CareerService(SQLiteEventStore(args.data_dir / "runs.sqlite"), ports)
    with make_career_server(service, os.environ["AGENT_CAREER_TOKEN"], args.port) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()

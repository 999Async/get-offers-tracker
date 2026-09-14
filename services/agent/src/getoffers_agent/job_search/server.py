"""Small authenticated local Product Port. Identity is established by the product caller."""

import hmac
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from pydantic import Field

from getoffers_agent.domain.contracts import Contract, SecurityContext
from getoffers_agent.job_search.contracts import SearchRequest
from getoffers_agent.job_search.search import JobSearch


class ProductSearchEnvelope(Contract):
    actor_id: str = Field(min_length=1, max_length=300)
    tenant_id: str = Field(min_length=1, max_length=300)
    request: SearchRequest


def product_search(raw: bytes, authorization: str, token: str, search: JobSearch) -> dict:
    if len(token) < 32 or not hmac.compare_digest(authorization, "Bearer " + token):
        raise PermissionError("unauthorized_product_caller")
    if len(raw) > 16384:
        raise ValueError("request_too_large")
    envelope = ProductSearchEnvelope.model_validate_json(raw)
    security = SecurityContext(
        actor_id=envelope.actor_id,
        tenant_id=envelope.tenant_id,
        capabilities=frozenset({"job:search"}),
    )
    return search.search(envelope.request, security).model_dump(mode="json")


def make_search_server(search: JobSearch, *, token: str, port: int = 0) -> HTTPServer:
    if len(token) < 32:
        raise ValueError("AGENT_SEARCH_TOKEN must have at least 32 characters")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(30)
            status, body = 200, {}
            try:
                if self.path != "/search":
                    status, body = 404, {"error": "not_found"}
                else:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 16384:
                        raise ValueError("invalid_length")
                    body = product_search(
                        self.rfile.read(length),
                        self.headers.get("Authorization", ""),
                        token,
                        search,
                    )
            except PermissionError:
                status, body = 401, {"error": "unauthorized"}
            except ValueError:
                status, body = 400, {"error": "invalid_request"}
            except Exception:
                status, body = 503, {"error": "search_unavailable"}
            encoded = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            pass

    return HTTPServer(("127.0.0.1", port), Handler)


def serve_search(search: JobSearch, *, token: str, port: int = 8766):
    # Local development only. Deployment requires a production server and authenticated transport.
    with make_search_server(search, token=token, port=port) as server:
        server.serve_forever()

"""Authenticated internal Product Port. User identity never comes from request fields."""

import base64
import binascii
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal

from pydantic import Field

from getoffers_agent.domain.contracts import Contract, SecurityContext
from getoffers_agent.knowledge.contracts import EvidenceQuery, FactReview, KnowledgeError

MAX_REQUEST_BYTES = 8 * 1024 * 1024
CAPABILITIES = frozenset(
    {
        "knowledge:read:self",
        "knowledge:upload:self",
        "knowledge:delete:self",
        "candidate_fact:review:self",
    }
)


class Envelope(Contract):
    actor_id: str = Field(min_length=1, max_length=300)
    tenant_id: str = Field(min_length=1, max_length=300)
    action: Literal[
        "list",
        "upload",
        "process",
        "retrieve",
        "citation",
        "facts",
        "review",
        "delete",
        "source",
        "reconcile",
    ]
    payload: dict = Field(default_factory=dict)


class Upload(Contract):
    filename: str = Field(min_length=1, max_length=200)
    mime: str
    content_base64: str
    document_id: str | None = None


class DocumentRef(Contract):
    document_id: str


class VersionRef(DocumentRef):
    version_id: str


class CitationRef(Contract):
    evidence_id: str


class FactsRequest(Contract):
    confirmed_only: bool = False


def product_knowledge(raw: bytes, authorization: str, token: str, service):
    if len(token) < 32 or not hmac.compare_digest(authorization, "Bearer " + token):
        raise PermissionError("unauthorized")
    if len(raw) > MAX_REQUEST_BYTES:
        raise KnowledgeError("request_too_large")
    envelope = Envelope.model_validate_json(raw)
    security = SecurityContext(
        actor_id=envelope.actor_id, tenant_id=envelope.tenant_id, capabilities=CAPABILITIES
    )
    action, payload = envelope.action, envelope.payload
    if action in {"list", "reconcile"}:
        Contract.model_validate(payload)
        return (
            {"documents": service.list_documents(security)}
            if action == "list"
            else {"deletions": service.reconcile(security)}
        )
    if action == "upload":
        upload = Upload.model_validate(payload)
        try:
            content = base64.b64decode(upload.content_base64, validate=True)
        except (ValueError, binascii.Error):
            raise KnowledgeError("invalid_base64") from None
        return service.upload(upload.filename, upload.mime, content, security, upload.document_id)
    if action == "process":
        ref = VersionRef.model_validate(payload)
        return service.process(ref.document_id, ref.version_id, security)
    if action == "retrieve":
        return service.retrieve(EvidenceQuery.model_validate(payload), security)
    if action == "citation":
        return service.citation(CitationRef.model_validate(payload).evidence_id, security)
    if action == "facts":
        return {
            "facts": service.facts(security, FactsRequest.model_validate(payload).confirmed_only)
        }
    if action == "review":
        return service.review(FactReview.model_validate(payload), security)
    if action == "delete":
        return service.delete(DocumentRef.model_validate(payload).document_id, security)
    ref = VersionRef.model_validate(payload)
    content, extension = service.source(ref.document_id, ref.version_id, security)
    return {"content_base64": base64.b64encode(content).decode(), "extension": extension}


def make_knowledge_server(service, token: str, port: int = 0):
    if len(token) < 32:
        raise KnowledgeError("knowledge_token_too_short")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(180)
            status, body = 200, {}
            try:
                if self.path != "/knowledge":
                    status, body = 404, {"error": "not_found"}
                else:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > MAX_REQUEST_BYTES:
                        raise KnowledgeError("invalid_request_length")
                    body = product_knowledge(
                        self.rfile.read(length),
                        self.headers.get("Authorization", ""),
                        token,
                        service,
                    )
            except PermissionError:
                status, body = 401, {"error": "unauthorized"}
            except KnowledgeError as exc:
                status, body = 400, {"error": str(exc)}
            except ValueError:
                status, body = 400, {"error": "invalid_request"}
            except Exception:
                status, body = 503, {"error": "knowledge_unavailable"}
            encoded = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)

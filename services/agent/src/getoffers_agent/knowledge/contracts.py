from typing import Literal

from pydantic import Field, model_validator

from getoffers_agent.domain.contracts import Contract, digest


class KnowledgeError(ValueError):
    """Only stable categories, never uploaded text, may reach error responses."""


class KnowledgeConfig(Contract):
    version: str = "knowledge-v1"
    parser_version: str = "canonical-v1"
    pdf_layout_revision: str = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
    max_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=20 * 1024 * 1024)
    max_pages: int = Field(default=100, ge=1, le=200)
    max_nodes: int = Field(default=5000, ge=1, le=10000)
    parse_timeout_seconds: int = Field(default=60, ge=1, le=120)
    max_parse_rss_mb: int = Field(default=1536, ge=256, le=4096)
    max_unit_bytes: int = Field(default=800, ge=100, le=3200)
    token_counter: Literal["utf8-byte-upper-bound-v1"] = "utf8-byte-upper-bound-v1"

    @property
    def identity(self):
        return digest(self.model_dump(mode="json"))


class SourceLocator(Contract):
    node_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    line_start: int | None = None
    line_end: int | None = None
    page: int | None = None
    source_ref: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("invalid_locator")
        return self


class DocumentNode(Contract):
    node_id: str
    kind: Literal["heading", "paragraph", "list_item", "table", "qa_pair", "code"]
    text: str = Field(min_length=1)
    order: int = Field(ge=0)
    path: tuple[str, ...] = ()
    parent_id: str | None = None
    locator: SourceLocator
    table_cells: tuple[tuple[str, ...], ...] = ()


class CanonicalDocument(Contract):
    schema_version: Literal[1] = 1
    parser_identity: str
    source_hash: str
    format: Literal["md", "txt", "pdf", "docx"]
    nodes: tuple[DocumentNode, ...]

    @model_validator(mode="after")
    def valid_nodes(self):
        seen = set()
        for i, node in enumerate(self.nodes):
            if (
                node.order != i
                or node.node_id in seen
                or (node.parent_id and node.parent_id not in seen)
            ):
                raise ValueError("invalid_document_structure")
            if node.locator.node_id != node.node_id or node.locator.end > len(node.text):
                raise ValueError("invalid_source_locator")
            seen.add(node.node_id)
        if not seen:
            raise ValueError("empty_document")
        return self


class EvidenceUnit(Contract):
    evidence_id: str
    document_id: str
    version_id: str
    tenant_id: str
    text: str
    path: tuple[str, ...]
    parent_node_id: str | None
    order: int
    locator: SourceLocator
    source_hash: str
    table_header: str | None = None
    trust: Literal["untrusted_user_content"] = "untrusted_user_content"


class EvidenceQuery(Contract):
    query: str = Field(min_length=1, max_length=2000)
    document_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    mode: Literal["lexical", "dense", "hybrid", "hybrid-rerank"] = "lexical"
    top_k: int = Field(default=5, ge=1, le=30)
    token_budget: int = Field(default=4000, ge=100, le=32000)
    expand_neighbors: bool = False


class FactReview(Contract):
    fact_id: str
    expected_revision: int = Field(ge=0)
    action: Literal["confirm", "correct", "reject"]
    corrected_value: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def correction(self):
        if (self.action == "correct") != (self.corrected_value is not None):
            raise ValueError("correction_required_only_for_correct")
        return self

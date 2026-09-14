"""Frozen synthetic inputs and isolated real knowledge/search services for assistant evaluation."""

import base64
import json
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from qdrant_client import QdrantClient

from getoffers_agent.domain.contracts import Contract, SecurityContext, digest
from getoffers_agent.job_search.contracts import JobInput, SearchConfig
from getoffers_agent.job_search.index import QdrantJobIndex
from getoffers_agent.job_search.search import JobSearch
from getoffers_agent.job_search.store import JobFactStore
from getoffers_agent.knowledge.index import EvidenceIndex
from getoffers_agent.knowledge.server import product_knowledge
from getoffers_agent.knowledge.service import KnowledgeService
from getoffers_agent.knowledge.store import KnowledgeStore, LocalArtifacts


class Case(Contract):
    case_id: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")
    task: str = Field(min_length=1, max_length=12000)
    jd: str = Field(default="", max_length=24000)
    select_material: bool = True
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    draft_kind: Literal["project", "resume", "interview"] | None = None
    require_citations: bool = False
    require_jobs: bool = False
    cities: tuple[str, ...] = ()
    forbidden_draft_fragments: tuple[str, ...] = ()
    review_instruction: str = Field(min_length=1)


class Dataset(Contract):
    schema_version: Literal[1] = 1
    dataset_version: str
    provenance: Literal["synthetic"]
    label_status: Literal["pending_human_review"]
    material: str = Field(min_length=1, max_length=30000)
    corrected_fact: str
    foreign_material: str
    foreign_canary: str
    jobs: tuple[JobInput, ...] = Field(min_length=1)
    cases: tuple[Case, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate_case_ids")
        if not self.foreign_canary or self.foreign_canary not in self.foreign_material:
            raise ValueError("invalid_foreign_canary")
        return self


def read_dataset(path):
    return Dataset.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))


def user(name="eval-assistant"):
    return SecurityContext(
        actor_id=name, tenant_id=name, capabilities=frozenset({"assistant:read:self"})
    )


class Ports:
    def __init__(self, knowledge, search):
        self.kb, self.engine = knowledge, search
        self.token = "isolated-evaluation-service-token-v1"

    def knowledge(self, security, action, payload):
        return product_knowledge(
            json.dumps(
                {
                    "actor_id": security.actor_id,
                    "tenant_id": security.tenant_id,
                    "action": action,
                    "payload": payload,
                }
            ).encode(),
            "Bearer " + self.token,
            self.token,
            self.kb,
        )

    def search(self, security, query):
        scope = security.model_copy(update={"capabilities": frozenset({"job:search"})})
        return self.engine.search(query, scope).model_dump(mode="json")


@contextmanager
def fixture(dataset, directory):
    """Only dataset-supplied synthetic inputs, never the product's database or user files."""
    with closing(QdrantClient(":memory:")) as kc, closing(QdrantClient(":memory:")) as sc:
        store = KnowledgeStore(directory / "knowledge.sqlite")
        knowledge = KnowledgeService(
            store, LocalArtifacts(directory / "materials"), EvidenceIndex(kc, store)
        )
        facts = JobFactStore(directory / "jobs.sqlite")
        index = QdrantJobIndex(sc, facts)
        authority = user().model_copy(
            update={"capabilities": frozenset({"job:ingest", "job:ingest:shared"})}
        )
        facts.ingest(dataset.jobs, authority)
        config = SearchConfig(mode="lexical")
        manifest = index.build(facts.snapshot("synthetic"), config)
        index.activate(manifest["index_id"])
        ports = Ports(knowledge, JobSearch(index, config))

        def upload(text, owner, name):
            doc = ports.knowledge(
                owner,
                "upload",
                {
                    "filename": name,
                    "mime": "text/markdown",
                    "content_base64": base64.b64encode(text.encode()).decode(),
                },
            )
            ports.knowledge(owner, "process", doc)
            return doc

        doc = upload(dataset.material, user(), "合成简历.md")
        upload(dataset.foreign_material, user("foreign-eval-user"), "其他账号材料.md")
        proposed = ports.knowledge(user(), "facts", {})["facts"]
        if not proposed:
            raise ValueError("fixture_did_not_extract_facts")
        # Explicit synthetic fixture correction; never marks actual user experience as reviewed.
        fact = proposed[0]
        ports.knowledge(
            user(),
            "review",
            {
                "fact_id": fact["fact_id"],
                "expected_revision": fact["revision"],
                "action": "correct",
                "corrected_value": dataset.corrected_fact,
            },
        )
        yield ports, doc


def input_hash(dataset, case):
    return digest(
        {
            "case": case.model_dump(mode="json"),
            "material": dataset.material,
            "corrected_fact": dataset.corrected_fact,
            "foreign_material": dataset.foreign_material,
            "jobs": [j.model_dump(mode="json") for j in dataset.jobs],
            "retrieval_mode": "lexical",
        }
    )

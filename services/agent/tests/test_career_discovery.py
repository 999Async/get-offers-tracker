"""Real lexical search + knowledge + runtime; synthetic private data and product fault port."""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qdrant_client import QdrantClient

from getoffers_agent.adapters.events import SQLiteEventStore
from getoffers_agent.career.discovery import CAPABILITIES, CareerService
from getoffers_agent.domain.contracts import RuntimeFault, SecurityContext, digest, utcnow
from getoffers_agent.job_search.contracts import JobInput, SearchConfig
from getoffers_agent.job_search.index import QdrantJobIndex
from getoffers_agent.job_search.search import JobSearch
from getoffers_agent.job_search.store import JobFactStore
from getoffers_agent.knowledge.index import EvidenceIndex
from getoffers_agent.knowledge.server import product_knowledge
from getoffers_agent.knowledge.service import KnowledgeService
from getoffers_agent.knowledge.store import KnowledgeStore, LocalArtifacts

TOKEN = "synthetic-test-token-" * 3
SECRET_QUOTE = "用 Python 实现火星项目的 RAG retrieval evaluation。"


def user(name="alice"):
    return SecurityContext(actor_id=name, tenant_id=name, capabilities=CAPABILITIES)


class Ports:
    def __init__(self, knowledge, search):
        self.kb, self.engine = knowledge, search
        self.receipts, self.applications = {}, {}
        self.writes = 0
        self.lose_receipt = False

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
            "Bearer " + TOKEN,
            TOKEN,
            self.kb,
        )

    def search(self, security, request):
        return self.engine.search(
            request, security.model_copy(update={"capabilities": frozenset({"job:search"})})
        ).model_dump(mode="json")

    def product(self, security, action, payload):
        tenant = security.tenant_id
        if action == "facts":
            return {"by_job": self.applications.get(tenant, {})}
        key = (tenant, payload["idempotency_key"])
        if action == "lookup":
            return self.receipts.get(key)
        self.writes += 1
        result = self.receipts.setdefault(key, {"plan_id": str(uuid4())})
        self.applications.setdefault(tenant, {})[payload["plan"]["sourceJobId"]] = result["plan_id"]
        if self.lose_receipt:
            raise TimeoutError("synthetic lost receipt")
        return result


@pytest.fixture
def setup(tmp_path):
    knowledge_client, search_client = QdrantClient(":memory:"), QdrantClient(":memory:")
    store = KnowledgeStore(tmp_path / "knowledge.sqlite")
    kb = KnowledgeService(
        store, LocalArtifacts(tmp_path / "artifacts"), EvidenceIndex(knowledge_client, store)
    )
    facts = JobFactStore(tmp_path / "jobs.sqlite")
    index = QdrantJobIndex(search_client, facts)
    jobs = [
        JobInput(
            source_id="fixture",
            source_job_id=city,
            source_url="https://example.org/jobs/" + str(i),
            company="合成硬件公司",
            title="Python 算法工程师",
            responsibilities=("Build RAG retrieval",),
            requirements=("Python retrieval evaluation", "CUDA"),
            cities=(city,),
            observed_at=utcnow(),
            source_artifact_hash=digest(city),
        )
        for i, city in enumerate(["北京", "上海"])
    ]
    facts.ingest(
        jobs,
        user().model_copy(update={"capabilities": frozenset({"job:ingest", "job:ingest:shared"})}),
    )
    config = SearchConfig(mode="lexical")
    manifest = index.build(facts.snapshot("synthetic"), config)
    index.activate(manifest["index_id"])
    ports = Ports(kb, JobSearch(index, config))
    import base64

    doc = ports.knowledge(
        user(),
        "upload",
        {
            "filename": "简历.md",
            "mime": "text/markdown",
            "content_base64": base64.b64encode(("# 项目\n\n" + SECRET_QUOTE).encode()).decode(),
        },
    )
    ports.knowledge(user(), "process", doc)
    fact = ports.knowledge(user(), "facts", {})["facts"][0]
    ports.knowledge(
        user(),
        "review",
        {"fact_id": fact["fact_id"], "expected_revision": fact["revision"], "action": "confirm"},
    )
    service = CareerService(SQLiteEventStore(tmp_path / "runs.sqlite"), ports)
    yield service, ports, doc
    if out := os.environ.get("GETOFFERS_CAREER_EVAL_OUT"):
        traces = Path(out) / "traces"
        traces.mkdir(parents=True, exist_ok=True)
        for run_id in service.runtime.store.list_runs():
            events = service.runtime.store.read(run_id)
            (traces / f"{run_id}.json").write_text(
                json.dumps([e.model_dump(mode="json") for e in events], ensure_ascii=False)
            )
    knowledge_client.close()
    search_client.close()


def dispatch(service, action, payload, security=None):
    return asyncio.run(service.dispatch(action, payload, security or user()))


def discover(setup):
    service, _, doc = setup
    return dispatch(
        service, "start", {"run_id": str(uuid4()), "task": {"query": "北京 Python", **doc}}
    )


def propose(setup):
    found = discover(setup)
    assert found["outcome"]["status"] == "success", found
    assert found["jobs"], found
    return dispatch(
        setup[0],
        "propose",
        {"run_id": found["run_id"], "job_version_id": found["jobs"][0]["version_id"]},
    )


def decide(service, pending, decision="grant", **changes):
    return dispatch(
        service,
        "decide",
        {
            "run_id": pending["run_id"],
            "approval": {
                "action_id": pending["approval"]["action_id"],
                "arguments_hash": pending["approval"]["arguments_hash"],
                "decision": decision,
                **changes,
            },
        },
    )


def test_golden_path_exact_approval_replay_and_no_resume_content_in_events(setup):
    service, ports, doc = setup
    found = discover(setup)
    assert found["outcome"]["status"] == "success", found
    assert [job["cities"] for job in found["jobs"]] == [["北京"]]
    job = found["jobs"][0]
    assert job["evidence"][0]["quote"] == SECRET_QUOTE
    assert job["evidence"][0]["confirmed_facts"] == [SECRET_QUOTE]
    assert job["gaps"] == ["CUDA"]
    assert ports.writes == 0
    request = {"run_id": found["run_id"], "job_version_id": job["version_id"]}
    pending = dispatch(service, "propose", request)
    assert pending["status"] == "awaiting_approval", pending
    assert pending["approval"]["plan"]["resumeVersionId"] == doc["version_id"]
    assert dispatch(service, "propose", request)["approval"] == pending["approval"]
    assert ports.writes == 0
    saved = decide(service, pending)
    assert saved["outcome"]["status"] == "success", saved
    assert saved["plan_id"] and ports.writes == 1
    assert decide(service, pending)["plan_id"] == saved["plan_id"]
    assert ports.writes == 1
    for run_id in [found["run_id"], pending["run_id"]]:
        events = service.runtime.store.read(UUID(run_id))
        assert SECRET_QUOTE not in "".join(e.model_dump_json() for e in events)
        assert all(
            e.payload["response"]["usage"]["source"] == "measured"
            for e in events
            if e.event_type == "model.completed"
        )
        assert service.runtime.replay(UUID(run_id)).steps <= 7
    resumed = CareerService(service.runtime.store, ports)
    assert dispatch(resumed, "get", {"run_id": saved["run_id"]})["plan_id"] == saved["plan_id"]


def test_reject_and_forged_approval_never_write(setup):
    service, ports, _ = setup
    pending = propose(setup)
    with pytest.raises(RuntimeFault):
        decide(service, pending, arguments_hash="f" * 64)
    assert ports.writes == 0
    result = decide(service, pending, "reject")
    assert result["outcome"]["status"] == "rejected"
    assert ports.writes == 0


@pytest.mark.parametrize("change", ["delete", "correct", "new_version"])
def test_changed_resume_invalidates_approval_and_old_citations(setup, change):
    service, ports, doc = setup
    pending = propose(setup)
    if change == "delete":
        ports.knowledge(user(), "delete", {"document_id": doc["document_id"]})
    elif change == "correct":
        fact = ports.knowledge(user(), "facts", {})["facts"][0]
        ports.knowledge(
            user(),
            "review",
            {
                "fact_id": fact["fact_id"],
                "expected_revision": fact["revision"],
                "action": "correct",
                "corrected_value": "仅设计过 Python 检索。",
            },
        )
    else:
        import base64

        upload = ports.knowledge(
            user(),
            "upload",
            {
                "filename": "简历.md",
                "mime": "text/markdown",
                "document_id": doc["document_id"],
                "content_base64": base64.b64encode(b"New Python resume").decode(),
            },
        )
        ports.knowledge(user(), "process", upload)
    assert dispatch(service, "get", {"run_id": pending["run_id"]})["unavailable"]
    with pytest.raises(ValueError):
        decide(service, pending)
    assert ports.writes == 0


def test_cross_tenant_and_arbitrary_job_selection_fail(setup):
    service, ports, _ = setup
    found = discover(setup)
    for action in ["get", "resume", "cancel"]:
        with pytest.raises(PermissionError):
            dispatch(service, action, {"run_id": found["run_id"]}, user("bob"))
    with pytest.raises(ValueError):
        dispatch(service, "propose", {"run_id": found["run_id"], "job_version_id": "made-up"})
    assert ports.writes == 0


def test_lost_receipt_readback_and_cancel_pending(setup):
    service, ports, _ = setup
    pending = propose(setup)
    ports.lose_receipt = True
    result = decide(service, pending)
    assert ports.writes == 1
    if not result["plan_id"]:
        result = dispatch(service, "resume", {"run_id": result["run_id"]})
    assert result["plan_id"] and ports.writes == 1
    ports.applications.clear()
    another = propose(setup)
    stopped = dispatch(service, "cancel", {"run_id": another["run_id"]})
    assert stopped["outcome"]["status"] == "cancelled"
    assert ports.writes == 1


def test_expired_approval_never_writes(setup, monkeypatch):
    from datetime import timedelta

    from getoffers_agent.runtime import engine

    service, ports, _ = setup
    pending = propose(setup)
    future = utcnow() + timedelta(minutes=6)
    monkeypatch.setattr(engine, "utcnow", lambda: future)
    expired = decide(service, pending)
    assert expired["outcome"]["status"] == "rejected"
    assert ports.writes == 0


def test_missing_resume_and_read_capability_fail_closed(setup):
    service, ports, doc = setup
    bad = dispatch(
        service,
        "start",
        {"run_id": str(uuid4()), "task": {"query": "Python", **doc, "version_id": "foreign"}},
    )
    assert bad["outcome"]["status"] == "failed"
    denied = dispatch(
        service,
        "start",
        {"run_id": str(uuid4()), "task": {"query": "Python", **doc}},
        user().model_copy(update={"capabilities": frozenset()}),
    )
    assert denied["outcome"]["status"] == "failed" and ports.writes == 0


def test_cancel_during_search_is_persisted_and_not_restarted(setup):
    import threading

    service, ports, doc = setup
    original = ports.search
    entered, release = threading.Event(), threading.Event()

    def slow_search(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    ports.search = slow_search
    run_id = str(uuid4())

    async def scenario():
        work = asyncio.create_task(
            service.dispatch(
                "start", {"run_id": run_id, "task": {"query": "Python", **doc}}, user()
            )
        )
        assert await asyncio.to_thread(entered.wait, 5)
        assert (await service.dispatch("cancel", {"run_id": run_id}, user()))[
            "status"
        ] == "cancelling"
        result = await work
        release.set()
        return result

    try:
        result = asyncio.run(scenario())
    finally:
        release.set()
    assert result["outcome"]["status"] == "cancelled"
    assert dispatch(service, "resume", {"run_id": run_id})["outcome"]["status"] == "cancelled"
    assert ports.writes == 0

import json
import math
import os
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient, models

from getoffers_agent.domain.contracts import SecurityContext, digest
from getoffers_agent.job_search.contracts import (
    HardConstraints,
    JobInput,
    SearchConfig,
    SearchRequest,
    SoftPreferences,
    normalize,
    tokens,
)
from getoffers_agent.job_search.index import QdrantJobIndex, point_id
from getoffers_agent.job_search.ingestion import from_legacy_feed, parse_job_html
from getoffers_agent.job_search.search import JobSearch, evidence, reciprocal_rank_fusion
from getoffers_agent.job_search.store import JobFactStore

AS_OF = datetime(2026, 9, 6, tzinfo=UTC)


def identity(tenant="alice", capabilities=None):
    return SecurityContext(
        actor_id=tenant,
        tenant_id=tenant,
        capabilities=capabilities or frozenset({"job:search", "job:ingest", "job:ingest:shared"}),
    )


def job(key="agent", **changes):
    values = dict(
        source_id="test",
        source_job_id=key,
        source_url=f"https://example.org/jobs/{key}",
        company="Hardware Lab",
        title="Python Agent Engineer",
        responsibilities=("Build Agent Memory retrieval and evaluation in Python",),
        requirements=("Python machine learning evaluation",),
        cities=("深圳",),
        recruitment_type="campus",
        company_type="hardware",
        observed_at=AS_OF - timedelta(days=1),
        source_artifact_hash=digest(key),
    )
    return JobInput(**(values | changes))


class TestEncoder:
    __test__ = False
    identity = "deterministic-test-vectors-v1"
    dimension = 4

    def encode(self, texts):
        result = []
        for value in texts:
            ts = tokens(value)
            counts = [
                sum(t in ts for t in group)
                for group in (
                    ("agent", "memory", "retrieval"),
                    ("java", "backend", "spring"),
                    ("robot", "vision", "control"),
                    ("python", "evaluation", "model"),
                )
            ]
            norm = math.sqrt(sum(v * v for v in counts)) or 1
            result.append([v / norm for v in counts])
        return result


class TestReranker:
    __test__ = False
    identity = "deterministic-test-reranker-v1"

    def score(self, query, documents):
        ts = set(tokens(query))
        return [len(ts.intersection(tokens(d))) / max(1, len(ts)) for d in documents]


@pytest.fixture
def setup(tmp_path):
    store = JobFactStore(tmp_path / "facts.db")
    server_url = os.environ.get("GETOFFERS_TEST_QDRANT_URL")
    client = QdrantClient(url=server_url) if server_url else QdrantClient(":memory:")
    previous = next(
        (
            a.collection_name
            for a in client.get_aliases().aliases
            if a.alias_name == "job_versions_v1"
        ),
        None,
    )
    index = QdrantJobIndex(client, store)
    try:
        yield store, index
    finally:
        if server_url:
            with store.connect() as db:
                owned = {
                    r[0] for r in db.execute("SELECT collection_name FROM search_index_versions")
                }
            active = next(
                (
                    a.collection_name
                    for a in client.get_aliases().aliases
                    if a.alias_name == "job_versions_v1"
                ),
                None,
            )
            if active in owned:
                actions = [
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name="job_versions_v1")
                    )
                ]
                if previous:
                    actions.append(
                        models.CreateAliasOperation(
                            create_alias=models.CreateAlias(
                                alias_name="job_versions_v1", collection_name=previous
                            )
                        )
                    )
                client.update_collection_aliases(actions)
            for collection in owned:
                if client.collection_exists(collection):
                    client.delete_collection(collection)
        client.close()


def build(setup, jobs=None, encoder=None):
    facts, index = setup
    facts.ingest(jobs or [job()], identity())
    manifest = index.build(facts.snapshot("synthetic"), SearchConfig(), encoder)
    index.activate(manifest["index_id"])
    return manifest


def test_semantic_only_evidence_is_attributed_context():
    version = normalize(job())
    excerpts = evidence(version, {"semantic-synonym"})
    assert excerpts and all(item.match_type == "context" for item in excerpts)
    for item in excerpts:
        original = getattr(version, item.field)
        assert item.quote == (original if item.field == "title" else original[item.item_index])
        assert item.job_version_id == version.version_id


def test_exclusion_checks_structured_duties_even_with_overview(setup):
    build(setup, [job(description="Join our AI team", responsibilities=("Maintain Java backend",))])
    result = JobSearch(setup[1], SearchConfig()).search(
        SearchRequest(query="Python", hard_constraints=HardConstraints(excluded_terms=("Java",))),
        identity(),
        as_of=AS_OF,
    )
    assert result.jobs == ()


def test_normalization_identity_and_versioning(setup):
    facts, _ = setup
    a = normalize(job(company="  Hardware   Lab ", title="Ｐｙｔｈｏｎ Agent Engineer"))
    b = normalize(job())
    assert a.version_id == b.version_id
    report = facts.ingest([job(), job(observed_at=AS_OF)], identity())
    assert report["new_versions"] == 1 and report["unchanged"] == 1
    changed = job(title="New title", observed_at=AS_OF + timedelta(hours=1))
    facts.ingest([changed], identity())
    assert not facts.is_current(b.version_id)
    assert facts.get(b.version_id).title == "Python Agent Engineer"
    old = facts.ingest([job()], identity())
    assert old["out_of_order"] == 1
    assert facts.is_current(normalize(changed).version_id)
    with facts.connect() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE job_versions SET body_json='{}'")


def test_timezone_equivalent_capture_and_snapshot_identity(setup):
    facts, _ = setup
    first = job(observed_at=AS_OF)
    equivalent = job(observed_at=AS_OF.astimezone(timezone(timedelta(hours=8))))
    assert normalize(first).version_id == normalize(equivalent).version_id
    facts.ingest([first], identity())
    snapshot = facts.snapshot()
    facts.ingest([equivalent], identity())
    assert facts.snapshot() == snapshot


def test_summary_feed_remains_ineligible(setup):
    feed = {
        "jobs": [
            {
                "sourceKey": "sheet",
                "id": "x",
                "link": "https://example.org/x",
                "company": "Acme",
                "position": "AI Engineer",
                "cities": ["深圳"],
            }
        ]
    }
    parsed = from_legacy_feed(json.dumps(feed).encode(), AS_OF)
    assert normalize(parsed[0]).completeness == "summary"
    facts, index = setup
    facts.ingest(parsed, identity())
    with pytest.raises(ValueError, match="no_full_job_descriptions"):
        index.build(facts.snapshot(), SearchConfig())


@pytest.mark.parametrize("mode", ["lexical", "dense", "hybrid", "hybrid-rerank"])
def test_whole_jobs_and_evidence(mode, setup):
    build(
        setup,
        [
            job(),
            job(
                "backend",
                title="Java Backend Engineer",
                responsibilities=("Java backend Spring services",),
                requirements=("Java Spring",),
            ),
        ],
        TestEncoder(),
    )
    search = JobSearch(setup[1], SearchConfig(mode=mode), TestEncoder(), TestReranker())
    result = search.search(
        SearchRequest(query="Python Agent Memory", top_k=2), identity(), as_of=AS_OF
    )
    assert result.jobs[0].job.source_job_id == "agent"
    assert len({r.job.job_id for r in result.jobs}) == len(result.jobs)
    assert result.corpus_version and result.index_version and result.search_config_hash
    for row in result.jobs:
        for item in row.evidence:
            quote = (
                row.job.title
                if item.field == "title"
                else getattr(row.job, item.field)[item.item_index]
            )
            assert item.quote == quote
            assert item.job_version_id == row.job.version_id


def test_hard_constraints_before_retrieval_and_tenant_isolation(setup):
    facts, index = setup
    inputs = [
        job(),
        job("other-city", cities=("北京",)),
        job("old", observed_at=AS_OF - timedelta(days=100)),
        job("expired", expires_at=AS_OF),
        job("missing-city", cities=()),
        job("backend", responsibilities=("Python Agent backend API Spring services",)),
        job("social", recruitment_type="experienced"),
        job("future", observed_at=AS_OF + timedelta(days=1)),
    ]
    facts.ingest(inputs, identity())
    private = job("private", visibility="private", tenant_id="bob")
    facts.ingest([private], identity("bob"))
    manifest = index.build(facts.snapshot(), SearchConfig())
    index.activate(manifest["index_id"])
    search = JobSearch(index, SearchConfig(candidate_limit=1))
    constraints = HardConstraints(
        cities=("深圳",), recruitment_types=("campus",), excluded_terms=("backend",)
    )
    request = SearchRequest(query="Python Agent", hard_constraints=constraints)
    rows = search.search(request, identity(), as_of=AS_OF).jobs
    assert [r.job.source_job_id for r in rows] == ["agent"]
    bob_rows = search.search(request, identity("bob"), as_of=AS_OF).jobs
    # Duplicate suppression may merge the private copy; it must never leak to Alice.
    assert all(r.job.tenant_id in {None, "bob"} for r in bob_rows)
    with pytest.raises(PermissionError):
        search.search(request, identity(capabilities=frozenset({"not-search"})), as_of=AS_OF)
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"query": "test", "tenant_id": "bob"})


@pytest.mark.parametrize("mode", ["lexical", "dense", "hybrid", "hybrid-rerank"])
def test_natural_language_city_filters_before_retrieval(mode, setup, monkeypatch):
    build(
        setup,
        [job("fontana", cities=("Fontana, CA",)), job("other", cities=("San Jose, CA",))],
        TestEncoder(),
    )
    search = JobSearch(setup[1], SearchConfig(mode=mode), TestEncoder(), TestReranker())
    original = setup[1].query
    calls = []

    def capture(manifest, vector, using, tenant, constraints, as_of, limit, allowed):
        calls.append(using)
        assert constraints.cities == ("Fontana, CA",)
        assert [setup[0].get(key).source_job_id for key in allowed] == ["fontana"]
        return original(manifest, vector, using, tenant, constraints, as_of, limit, allowed)

    monkeypatch.setattr(setup[1], "query", capture)
    result = search.search(
        SearchRequest(query="Python Agent Engineer — Fontana, CA (Customer Site)"),
        identity(),
        as_of=AS_OF,
    )
    assert [row.job.source_job_id for row in result.jobs] == ["fontana"]
    assert result.effective_hard_constraints.cities == ("Fontana, CA",)
    assert result.city_constraint_matches == ("Fontana, CA",)
    assert calls


@pytest.mark.parametrize("query", ["Python Agent 不要深圳", "在北京找 Python Agent 工作"])
def test_natural_city_exclusions_and_no_matching_jobs(query, setup):
    build(setup)
    result = JobSearch(setup[1], SearchConfig()).search(
        SearchRequest(query=query),
        identity(),
        as_of=AS_OF,
    )
    assert result.jobs == ()


@pytest.mark.parametrize("mode", ["lexical", "dense", "hybrid", "hybrid-rerank"])
def test_natural_city_exclusion_keeps_other_cities(mode, setup):
    build(setup, [job(), job("beijing", cities=("北京",))], TestEncoder())
    search = JobSearch(setup[1], SearchConfig(mode=mode), TestEncoder(), TestReranker())
    result = search.search(
        SearchRequest(query="Python Agent，不要深圳"),
        identity(),
        as_of=AS_OF,
    )
    assert [row.job.source_job_id for row in result.jobs] == ["beijing"]
    assert result.effective_hard_constraints.excluded_cities == ("深圳",)


@pytest.mark.parametrize("mode", ["lexical", "dense", "hybrid", "hybrid-rerank"])
def test_official_fontana_regressions(mode, setup):
    from getoffers_agent.job_search.evaluation import SearchDataset

    path = Path(__file__).resolve().parents[3] / (
        "datasets/evals/job-search-v2-ai-review/official-ai-reviewed.json"
    )
    dataset = SearchDataset.model_validate_json(path.read_text())
    build(setup, list(dataset.jobs), TestEncoder())
    search = JobSearch(setup[1], SearchConfig(mode=mode), TestEncoder(), TestReranker())
    for case in dataset.cases:
        if case.case_id not in {"official-17-1", "official-17-4"}:
            continue
        result = search.search(case.request, identity(), as_of=dataset.as_of)
        assert result.jobs
        assert result.effective_hard_constraints.cities == ("Fontana, CA",)
        assert all("Fontana, CA" in row.job.cities for row in result.jobs)


def test_second_fact_check_rejects_tampered_qdrant_payload(setup):
    facts, index = setup
    facts.ingest([job()], identity())
    private = job("private", visibility="private", tenant_id="bob", title="Private Agent")
    facts.ingest([private], identity("bob"))
    manifest = index.build(facts.snapshot(), SearchConfig())
    index.activate(manifest["index_id"])
    # A compromised/stale payload points an allowed shared point at somebody else's version.
    index.client.set_payload(
        manifest["collection_name"],
        {"version_id": normalize(private).version_id},
        [point_id(normalize(job()).version_id)],
    )
    result = JobSearch(index, SearchConfig()).search(
        SearchRequest(query="Agent"), identity(), as_of=AS_OF
    )
    assert result.jobs == () and result.rejected_by_fact_check == 1


def test_inactive_versions_never_return_and_cannot_be_reactivated(setup):
    manifest = build(setup)
    facts, index = setup
    facts.deactivate(normalize(job()).job_id, identity())
    assert (
        JobSearch(index, SearchConfig())
        .search(SearchRequest(query="Agent"), identity(), as_of=AS_OF)
        .jobs
        == ()
    )
    with pytest.raises(ValueError, match="inactive_version"):
        index.activate(manifest["index_id"])


def test_index_rebuild_alias_repair_and_failed_build(setup, monkeypatch):
    old = build(setup)
    facts, index = setup
    new = index.build(facts.snapshot(), SearchConfig())
    original = index.client.update_collection_aliases
    monkeypatch.setattr(
        index.client, "update_collection_aliases", lambda _: (_ for _ in ()).throw(RuntimeError())
    )
    assert index.activate(new["index_id"]) is False
    assert facts.index()["index_id"] == new["index_id"]
    assert (
        JobSearch(index, SearchConfig())
        .search(SearchRequest(query="Agent"), identity(), as_of=AS_OF)
        .jobs
    )
    monkeypatch.setattr(index.client, "update_collection_aliases", original)
    assert index.reconcile_alias()
    assert index.client.get_aliases().aliases[0].collection_name == new["collection_name"]
    assert index.activate(old["index_id"])

    class Broken(TestEncoder):
        def encode(self, texts):
            return [[float("nan")]]

    with pytest.raises(ValueError, match="invalid_encoder_output"):
        index.build(facts.snapshot(), SearchConfig(), Broken())
    assert facts.index()["index_id"] == old["index_id"]


def test_dedup_diversity_negative_duties_and_score_components(setup):
    build(
        setup,
        [
            job(),
            job("copy"),
            job("other", company="Other Lab"),
            job("backend", title="Python Agent Backend", responsibilities=("Agent backend API",)),
        ],
    )
    result = JobSearch(setup[1], SearchConfig()).search(
        SearchRequest(
            query="Agent",
            soft_preferences=SoftPreferences(negative_duties=("backend",), max_per_company=1),
        ),
        identity(),
        as_of=AS_OF,
    )
    assert len(result.jobs) == 2
    assert len({r.job.duplicate_key for r in result.jobs}) == 2
    assert all("section_match" in r.score_components for r in result.jobs)


def test_rrf_and_tokenization_are_deterministic():
    scores = reciprocal_rank_fusion([["a", "b", "a"], ["b", "a"]])
    assert scores["a"] == scores["b"] == 1 / 61 + 1 / 62
    assert tokens("Ｐｙｔｈｏｎ 大模型算法 C++") == [
        "python",
        "c++",
        "大模",
        "模型",
        "型算",
        "算法",
    ]


def test_schema_matches_d1_migration_and_existing_tables_survive(tmp_path):
    root = Path(__file__).parents[3]
    migration = (root / "drizzle/0001_white_cannonball.sql").read_text()
    for filename, script in (
        ("d1.db", migration),
        ("local.db", Path("services/agent/src/getoffers_agent/job_search/schema.sql").read_text()),
    ):
        with sqlite3.connect(tmp_path / filename) as db:
            db.executescript((root / "drizzle/0000_oval_bishop.sql").read_text())
            db.executescript(script)
            assert db.execute("SELECT count(*) FROM applications").fetchone()[0] == 0
    with (
        sqlite3.connect(tmp_path / "d1.db") as left,
        sqlite3.connect(tmp_path / "local.db") as right,
    ):
        for table in (
            "job_sources",
            "job_versions",
            "job_current",
            "job_ingestion_runs",
            "job_corpus_snapshots",
            "search_index_versions",
            "active_search_index",
        ):
            assert (
                left.execute(f"PRAGMA table_info({table})").fetchall()
                == right.execute(f"PRAGMA table_info({table})").fetchall()
            )


def test_html_optional_requirements_and_injection_text_remain_data():
    body = """&lt;p&gt;Responsibilities:&lt;/p&gt;
    &lt;ul&gt;&lt;li&gt;Build robots&lt;/li&gt;&lt;/ul&gt;
    &lt;p&gt;Requirements:&lt;/p&gt;&lt;li&gt;Python&lt;/li&gt;
    &lt;p&gt;Bonus Qualifications:&lt;/p&gt;&lt;li&gt;PhD&lt;/li&gt;"""
    paragraphs, responsibilities, requirements = parse_job_html(body)
    assert responsibilities == ["Build robots"] and requirements == ["Python"]
    assert "PhD" in paragraphs


def test_same_count_corrupt_index_cannot_activate(setup):
    manifest = build(setup)
    facts, index = setup
    other = index.build(facts.snapshot(), SearchConfig())
    index.client.set_payload(
        other["collection_name"],
        {"version_id": "corrupted"},
        [point_id(normalize(job()).version_id)],
    )
    with pytest.raises(ValueError, match="index_manifest_mismatch"):
        index.activate(other["index_id"])
    assert facts.index()["index_id"] == manifest["index_id"]


def test_conflicting_timestamp_rolls_back_ingestion(setup):
    facts, _ = setup
    facts.ingest([job()], identity())
    with pytest.raises(ValueError, match="conflicting_capture_timestamp"):
        facts.ingest([job("new"), job(title="conflicting")], identity())
    assert len(facts.snapshot().entries) == 1
    with facts.connect() as db:
        row = db.execute(
            "SELECT status,report_json FROM job_ingestion_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        assert row[0] == "failed" and json.loads(row[1])["rolled_back"]


def test_structured_filters_use_same_normalization_as_facts(setup):
    build(setup)
    request = SearchRequest(
        query="Agent", hard_constraints=HardConstraints(cities=(" 深圳 ", "深圳"))
    )
    assert request.hard_constraints.cities == ("深圳",)
    assert JobSearch(setup[1], SearchConfig()).search(request, identity(), as_of=AS_OF).jobs

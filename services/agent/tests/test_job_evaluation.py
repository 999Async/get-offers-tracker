import json
import math

import pytest
from pydantic import ValidationError
from test_job_search import AS_OF, TestEncoder, TestReranker, build, identity, job
from test_job_search import setup as setup

from getoffers_agent.job_search.contracts import SearchConfig, SearchRequest, normalize
from getoffers_agent.job_search.evaluation import (
    SearchCase,
    SearchDataset,
    evaluate_search,
    retrieval_metrics,
)
from getoffers_agent.job_search.search import JobSearch
from getoffers_agent.job_search.server import product_search


def test_retrieval_metric_known_values():
    metrics = retrieval_metrics(["b", "a", "wrong"], {"a": 3, "b": 1})
    assert metrics["recall_at_20"] == 1
    assert metrics["precision_at_5"] == 0.4
    assert metrics["mrr"] == 1
    assert metrics["ndcg_at_5"] == pytest.approx((1 + 7 / math.log2(3)) / (7 + 1 / math.log2(3)))
    assert retrieval_metrics([], {"a": 3})["mrr"] == 0


def test_paired_evaluation_has_real_gate_for_label_review(setup):
    example = job()
    other_city = job("beijing", cities=("北京",))
    dataset = SearchDataset(
        dataset_version="test-v1",
        source_kind="synthetic",
        as_of=AS_OF,
        jobs=(example, other_city),
        cases=(
            SearchCase(
                case_id="a",
                request=SearchRequest(query="在深圳找 Agent 工作", top_k=100),
                relevance={normalize(example).version_id: 3, normalize(other_city).version_id: 0},
                review_status="synthetic",
            ),
        ),
    )
    report = evaluate_search(
        setup[1],
        dataset,
        [SearchConfig(mode=mode) for mode in ("lexical", "dense", "hybrid", "hybrid-rerank")],
        identity(),
        TestEncoder(),
        TestReranker(),
    )
    assert report["gate"]["safety_passed"]
    assert not report["gate"]["reviewed_dataset_ready"]
    assert not report["gate"]["production_release_ready"]
    assert len(report["paired_comparisons"]) == 3
    assert all(r["metrics"]["mrr"] == 1 for r in report["reports"])
    for result in report["reports"]:
        case = result["cases"][0]
        assert case["effective_hard_constraints"]["cities"] == ["深圳"]
        assert case["city_constraint_matches"] == ["深圳"]
        assert case["constraint_parser_version"] == "city-intent-v1"
        assert case["ranked_version_ids"] == [normalize(example).version_id]
    assert report["compute_accounting"]["cost_amount"] is None


def test_labels_must_be_versioned_and_review_claim_needs_identity():
    with pytest.raises(ValidationError):
        SearchCase(
            case_id="a",
            request=SearchRequest(query="x"),
            relevance={"a": 3},
            review_status="human-reviewed",
        )
    with pytest.raises(ValidationError):
        SearchDataset(
            dataset_version="bad",
            source_kind="synthetic",
            as_of=AS_OF,
            jobs=(job(),),
            cases=(
                SearchCase(case_id="a", request=SearchRequest(query="x"), relevance={"unknown": 3}),
            ),
        )


def test_product_port_requires_authenticated_server_identity(setup):
    build(setup, [job(), job("beijing", cities=("北京",))])
    search = JobSearch(setup[1], SearchConfig())
    token = "x" * 32
    envelope = {
        "actor_id": "alice",
        "tenant_id": "alice",
        "request": {"query": "在深圳找 Agent 工作"},
    }
    raw = json.dumps(envelope).encode()
    with pytest.raises(PermissionError):
        product_search(raw, "", token, search)
    result = product_search(raw, "Bearer " + token, token, search)
    assert result["jobs"]
    assert result["effective_hard_constraints"]["cities"] == ["深圳"]
    assert all(row["job"]["cities"] == ["深圳"] for row in result["jobs"])
    for changed in (
        {**envelope, "capabilities": ["job:ingest"]},
        {**envelope, "request": {"query": "Agent", "tenant_id": "bob"}},
    ):
        with pytest.raises(ValueError):
            product_search(json.dumps(changed).encode(), "Bearer " + token, token, search)

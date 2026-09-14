"""Opt-in integration with actual pinned BGE weights; never substitutes fake vectors."""

import os

import pytest
from qdrant_client import QdrantClient
from test_job_search import AS_OF, identity, job

from getoffers_agent.job_search.contracts import SearchConfig, SearchRequest
from getoffers_agent.job_search.index import QdrantJobIndex
from getoffers_agent.job_search.models import BGEEncoder, BGEReranker
from getoffers_agent.job_search.search import JobSearch
from getoffers_agent.job_search.store import JobFactStore


@pytest.mark.skipif(
    not os.environ.get("GETOFFERS_NEURAL_INTEGRATION"),
    reason="opt-in: requires downloaded pinned BGE weights",
)
def test_real_bge_dense_and_cross_encoder(tmp_path):
    device = os.environ.get("GETOFFERS_NEURAL_DEVICE", "cpu")
    encoder = BGEEncoder(".agent-data/models", device=device, max_length=512)
    reranker = BGEReranker(".agent-data/models", device=device, max_length=512)
    positive = job(
        title="Robot Learning Engineer",
        responsibilities=("Train reinforcement learning policies for humanoid robots",),
        requirements=("Python PyTorch robotics control",),
    )
    negative = job(
        "finance",
        title="Financial Accountant",
        responsibilities=("Prepare tax reports and accounts payable invoices",),
        requirements=("Accounting experience",),
    )
    facts = JobFactStore(tmp_path / "facts.db")
    facts.ingest([positive, negative], identity())
    client = QdrantClient(":memory:")
    try:
        index = QdrantJobIndex(client, facts)
        index.activate(index.build(facts.snapshot(), SearchConfig(), encoder)["index_id"])
        result = JobSearch(index, SearchConfig(mode="hybrid-rerank"), encoder, reranker).search(
            SearchRequest(query="reinforcement learning for robot control", top_k=2),
            identity(),
            as_of=AS_OF,
        )
        assert result.jobs[0].job.title == positive.title
        assert len(encoder.encode(["robot control"])[0]) == 1024
        scores = reranker.score(
            "robot control",
            [positive.description or positive.responsibilities[0], negative.responsibilities[0]],
        )
        assert scores[0] > scores[1]
    finally:
        client.close()

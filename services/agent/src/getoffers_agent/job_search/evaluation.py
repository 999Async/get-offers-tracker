"""Retrieval metrics and frozen, explicitly reviewed-or-draft paired experiments."""

import math
import platform
import resource
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from getoffers_agent.domain.contracts import Contract, SecurityContext, digest
from getoffers_agent.job_search.contracts import (
    JobInput,
    SearchConfig,
    SearchRequest,
    eligible,
    normalize,
)
from getoffers_agent.job_search.index import QdrantJobIndex
from getoffers_agent.job_search.models import DenseEncoder, Reranker
from getoffers_agent.job_search.search import JobSearch


class SearchCase(Contract):
    case_id: str
    request: SearchRequest
    relevance: dict[str, int]
    review_status: str = "machine-proposed"
    reviewer: str | None = None

    @model_validator(mode="after")
    def validate_labels(self):
        if self.review_status not in {"synthetic", "machine-proposed", "human-reviewed"}:
            raise ValueError("unknown_review_status")
        if self.review_status == "human-reviewed" and not self.reviewer:
            raise ValueError("human_reviewer_required")
        if not self.relevance or any(v not in {0, 1, 2, 3} for v in self.relevance.values()):
            raise ValueError("invalid_relevance_labels")
        return self


class SearchDataset(Contract):
    schema_version: int = Field(default=1, ge=1, le=1)
    dataset_version: str
    source_kind: Literal["synthetic", "public-official", "imported"]
    as_of: AwareDatetime
    jobs: tuple[JobInput, ...]
    cases: tuple[SearchCase, ...]

    @model_validator(mode="after")
    def identities_and_labels(self):
        ids = {normalize(job).version_id for job in self.jobs}
        if (
            not self.jobs
            or not self.cases
            or len({case.case_id for case in self.cases}) != len(self.cases)
        ):
            raise ValueError("empty_or_duplicate_cases")
        if any(key not in ids for case in self.cases for key in case.relevance):
            raise ValueError("label_references_unknown_job_version")
        return self


def retrieval_metrics(ids: list[str], relevance: dict[str, int]) -> dict[str, float]:
    positive = {key for key, grade in relevance.items() if grade > 0}
    result = {}
    for k in (5, 10, 20, 50, 100):
        found = set(ids[:k]).intersection(positive)
        result[f"recall_at_{k}"] = len(found) / len(positive) if positive else 0.0
        result[f"precision_at_{k}"] = len(found) / k
        dcg = sum(
            (2 ** relevance.get(key, 0) - 1) / math.log2(i + 2) for i, key in enumerate(ids[:k])
        )
        ideal = sum(
            (2**grade - 1) / math.log2(i + 2)
            for i, grade in enumerate(sorted(relevance.values(), reverse=True)[:k])
        )
        result[f"ndcg_at_{k}"] = dcg / ideal if ideal else 0.0
    result["mrr"] = next((1 / rank for rank, key in enumerate(ids, 1) if key in positive), 0.0)
    return result


def evaluate_search(
    index: QdrantJobIndex,
    dataset: SearchDataset,
    configs: list[SearchConfig],
    security: SecurityContext,
    encoder: DenseEncoder | None = None,
    reranker: Reranker | None = None,
) -> dict:
    if len({config.config_hash for config in configs}) != len(configs) or not configs:
        raise ValueError("duplicate_or_empty_configurations")
    index.facts.ingest(list(dataset.jobs), security)
    snapshot = index.facts.snapshot(dataset.source_kind)
    expected = {normalize(job).version_id for job in dataset.jobs}
    if {entry.version_id for entry in snapshot.entries} != expected:
        raise ValueError("evaluation_store_not_isolated")
    manifest = index.build(snapshot, configs[0], encoder)
    index.activate(manifest["index_id"])
    reports = []
    for config in configs:
        search = JobSearch(index, config, encoder, reranker)
        cases = []
        for case in dataset.cases:
            # Same request/as_of/facts/labels for every configuration. top_k must reach metric K.
            result = search.search(case.request, security, as_of=dataset.as_of)
            ids = [row.job.version_id for row in result.jobs]
            metrics = retrieval_metrics(ids, case.relevance)
            by_version = {entry.version_id: entry.last_seen_at for entry in snapshot.entries}
            violations = sum(
                not eligible(
                    row.job,
                    by_version[row.job.version_id],
                    security.tenant_id,
                    result.effective_hard_constraints,
                    dataset.as_of,
                )
                for row in result.jobs
            )
            duplicates = len(ids) - len({row.job.duplicate_key for row in result.jobs})
            stale = sum(not index.facts.is_current(key) for key in ids)
            cases.append(
                {
                    "case_id": case.case_id,
                    "review_status": case.review_status,
                    "metrics": metrics,
                    "hard_constraint_violations": violations,
                    "stale_count": stale,
                    "duplicate_count": duplicates,
                    "result_count": len(ids),
                    "judged_result_count": sum(key in case.relevance for key in ids),
                    "ranked_version_ids": ids,
                    "stage_duration_ms": result.stage_duration_ms,
                    "company_diversity": len({row.job.company for row in result.jobs}),
                    "search_config_hash": result.search_config_hash,
                    "effective_hard_constraints": result.effective_hard_constraints.model_dump(
                        mode="json"
                    ),
                    "city_constraint_matches": list(result.city_constraint_matches),
                    "constraint_parser_version": result.constraint_parser_version,
                }
            )
        latencies = sorted(row["stage_duration_ms"]["total"] for row in cases)
        reports.append(
            {
                "config": config.model_dump(mode="json"),
                "cases": cases,
                "metrics": {
                    key: mean(row["metrics"][key] for row in cases) for key in cases[0]["metrics"]
                },
                "hard_constraint_violations": sum(
                    row["hard_constraint_violations"] for row in cases
                ),
                "stale_count": sum(row["stale_count"] for row in cases),
                "duplicate_count": sum(row["duplicate_count"] for row in cases),
                "p50_ms": latencies[math.ceil(len(latencies) * 0.5) - 1],
                "p95_ms": latencies[math.ceil(len(latencies) * 0.95) - 1],
            }
        )
    baseline = reports[0]
    pairs = [
        {
            "baseline": baseline["config"]["mode"],
            "challenger": report["config"]["mode"],
            "case_deltas": [
                {
                    "case_id": left["case_id"],
                    "mrr_delta": right["metrics"]["mrr"] - left["metrics"]["mrr"],
                    "ndcg_at_10_delta": right["metrics"]["ndcg_at_10"]
                    - left["metrics"]["ndcg_at_10"],
                }
                for left, right in zip(baseline["cases"], report["cases"], strict=True)
            ],
        }
        for report in reports[1:]
    ]
    reviewed = sum(case.review_status == "human-reviewed" for case in dataset.cases)
    root = Path(__file__).parents[1]
    return {
        "schema_version": 1,
        "dataset_version": dataset.dataset_version,
        "dataset_hash": digest(dataset.model_dump(mode="json")),
        "corpus_snapshot": snapshot.snapshot_id,
        "as_of": dataset.as_of.isoformat(),
        "source_kind": dataset.source_kind,
        "reviewed_cases": reviewed,
        "grader_version": "job-ranking-metrics-v1",
        "code_hash": digest(
            {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))}
        ),
        "dependency_lock_hash": digest((Path(__file__).parents[3] / "uv.lock").read_text()),
        "encoder_identity": manifest["encoder_identity"],
        "reranker_identity": reranker.identity if reranker else "none",
        "index_version": manifest["index_id"],
        "index_manifest_hash": digest(manifest),
        "build_duration_ms": manifest["build_duration_ms"],
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "architecture": platform.machine(),
        },
        "compute_accounting": {
            "cost_amount": None,
            "cost_status": "unpriced_local_compute",
            "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if platform.system() == "Darwin" else 1024),
        },
        "reports": reports,
        "paired_comparisons": pairs,
        "gate": {
            "safety_passed": all(
                r["hard_constraint_violations"] == 0
                and r["stale_count"] == 0
                and r["duplicate_count"] == 0
                for r in reports
            ),
            "reviewed_dataset_ready": reviewed >= 150,
            "production_release_ready": False,
            "reason": "Human-reviewed labels and empirical quality/resource thresholds required.",
        },
    }

"""Hard filters -> lexical/dense -> RRF -> reranker -> explained whole-job ranking."""

import math
from collections import Counter
from datetime import datetime
from time import perf_counter

from qdrant_client import models

from getoffers_agent.domain.contracts import SecurityContext, digest
from getoffers_agent.job_search.constraints import CITY_PARSER_VERSION, resolve_city_constraints
from getoffers_agent.job_search.contracts import (
    JobEvidence,
    JobVersion,
    RankedJob,
    SearchConfig,
    SearchRequest,
    SearchResult,
    eligible,
    now,
    tokens,
)
from getoffers_agent.job_search.index import QdrantJobIndex
from getoffers_agent.job_search.models import DenseEncoder, Reranker


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank)
    return scores


def evidence(job: JobVersion, query_tokens: set[str]) -> tuple[JobEvidence, ...]:
    matches = []
    for field in ("title", "responsibilities", "requirements"):
        values = [job.title] if field == "title" else getattr(job, field)
        for index, value in enumerate(values):
            if query_tokens.intersection(tokens(value)):
                matches.append(
                    JobEvidence(
                        evidence_id=digest([job.version_id, field, index]),
                        job_version_id=job.version_id,
                        source_url=str(job.source_url),
                        source_artifact_hash=job.source_artifact_hash,
                        field=field,
                        item_index=index,
                        quote=value,
                    )
                )
    if not matches:
        # A semantic match is not evidence of literal overlap. Supply attributed context.
        for field in ("title", "responsibilities", "requirements"):
            value = job.title if field == "title" else getattr(job, field)[0]
            matches.append(
                JobEvidence(
                    evidence_id=digest([job.version_id, field, 0]),
                    job_version_id=job.version_id,
                    source_url=str(job.source_url),
                    source_artifact_hash=job.source_artifact_hash,
                    field=field,
                    item_index=0,
                    quote=value,
                    match_type="context",
                )
            )
    return tuple(matches[:6])


class JobSearch:
    def __init__(
        self,
        index: QdrantJobIndex,
        config: SearchConfig,
        encoder: DenseEncoder | None = None,
        reranker: Reranker | None = None,
    ):
        self.index, self.config, self.encoder, self.reranker = index, config, encoder, reranker

    def search(
        self,
        request: SearchRequest,
        security: SecurityContext,
        *,
        as_of: datetime | None = None,
        index_id: str | None = None,
    ) -> SearchResult:
        if "job:search" not in security.capabilities:
            raise PermissionError("job_search_denied")
        as_of = as_of or now()
        if as_of.tzinfo is None:
            raise ValueError("aware_as_of_required")
        began = perf_counter()
        manifest = self.index.facts.index(index_id)
        if manifest["status"] != "validated":
            raise ValueError("index_not_validated")
        for field in ("bm25_k1", "bm25_b", "tokenizer_version"):
            if manifest["config"][field] != getattr(self.config, field):
                raise ValueError("index_config_mismatch")
        if self.config.mode != "lexical" and (
            self.encoder is None or manifest["encoder_identity"] != self.encoder.identity
        ):
            raise ValueError("encoder_identity_mismatch")
        if self.config.mode == "hybrid-rerank" and self.reranker is None:
            raise ValueError("reranker_required")
        snapshot = self.index.facts.load_snapshot(manifest["snapshot_id"])
        seen = {entry.version_id: entry.last_seen_at for entry in snapshot.entries}
        jobs = {key: self.index.facts.get(key) for key in manifest["version_ids"]}
        constraints, city_matches = resolve_city_constraints(
            request,
            (
                city
                for job in jobs.values()
                if job.visibility == "shared" or job.tenant_id == security.tenant_id
                for city in job.cities
            ),
        )
        allowed = [
            key
            for key, job in jobs.items()
            if self.index.facts.is_current(key)
            and eligible(job, seen[key], security.tenant_id, constraints, as_of)
        ]
        timings = {"fact_filter": (perf_counter() - began) * 1000}
        query_terms = set(tokens(request.query))
        limit = max(request.top_k, self.config.candidate_limit)
        lexical, dense = [], []
        start = perf_counter()
        if self.config.mode != "dense":
            vocabulary = manifest["vocabulary"]
            indices = sorted(vocabulary[t] for t in query_terms if t in vocabulary)
            if indices:
                lexical = self.index.query(
                    manifest,
                    models.SparseVector(indices=indices, values=[1.0] * len(indices)),
                    "bm25",
                    security.tenant_id,
                    constraints,
                    as_of,
                    limit,
                    allowed,
                )
        timings["bm25"] = (perf_counter() - start) * 1000
        start = perf_counter()
        if self.config.mode != "lexical" and allowed:
            encoded = self.encoder.encode([request.query])
            if (
                len(encoded) != 1
                or len(encoded[0]) != manifest["dimension"]
                or not all(math.isfinite(x) for x in encoded[0])
            ):
                raise ValueError("invalid_query_embedding")
            dense = self.index.query(
                manifest,
                encoded[0],
                "dense",
                security.tenant_id,
                constraints,
                as_of,
                limit,
                allowed,
            )
        timings["dense"] = (perf_counter() - start) * 1000
        start = perf_counter()
        rankings = [[key for key, _ in values] for values in (lexical, dense) if values]
        fused = reciprocal_rank_fusion(rankings, self.config.rrf_k)
        # Recheck every candidate against authoritative facts, not Qdrant payload.
        rejected = 0
        for key in list(fused):
            if key not in allowed or not self.index.facts.is_current(key):
                del fused[key]
                rejected += 1
        ordered = sorted(fused, key=lambda key: (-fused[key], key))[:limit]
        timings["fusion"] = (perf_counter() - start) * 1000
        start = perf_counter()
        rerank_scores = {}
        if self.config.mode == "hybrid-rerank" and ordered:
            scores = self.reranker.score(request.query, [jobs[key].full_text for key in ordered])
            if len(scores) != len(ordered) or not all(
                math.isfinite(v) and 0 <= v <= 1 for v in scores
            ):
                raise ValueError("invalid_reranker_output")
            rerank_scores = dict(zip(ordered, scores, strict=True))
        timings["rerank"] = (perf_counter() - start) * 1000
        start = perf_counter()
        ranked = []
        lexical_scores, dense_scores = dict(lexical), dict(dense)
        for key in ordered:
            job = jobs[key]
            prefs = request.soft_preferences
            matches = evidence(job, query_terms)
            section_coverage = len(
                query_terms.intersection(
                    tokens(" ".join((*job.responsibilities, *job.requirements)))
                )
            ) / max(1, len(query_terms))
            freshness = math.exp(-max(0, (as_of - seen[key]).total_seconds()) / (30 * 86400))
            preference = (
                int(job.company_type in prefs.company_types)
                + int(bool(set(job.cities).intersection(prefs.cities)))
            ) / 2
            negative = sum(
                term.casefold() in " ".join(job.responsibilities).casefold()
                for term in prefs.negative_duties
                if term.strip()
            )
            base = rerank_scores.get(
                key, fused[key] * (self.config.rrf_k + 1) / max(1, len(rankings))
            )
            components = {
                "retrieval": base,
                "bm25_raw": lexical_scores.get(key, 0),
                "dense_raw": dense_scores.get(key, 0),
                "rrf_raw": fused[key],
                "reranker": rerank_scores.get(key, 0),
                "section_match": self.config.section_match_weight * section_coverage,
                "freshness": self.config.freshness_weight * freshness,
                "source_quality": self.config.source_quality_weight * job.source_quality,
                "preferences": self.config.preference_weight * preference,
                "negative_duties": -self.config.duty_penalty * negative,
            }
            score = sum(
                components[k]
                for k in (
                    "retrieval",
                    "section_match",
                    "freshness",
                    "source_quality",
                    "preferences",
                    "negative_duties",
                )
            )
            ranked.append(
                RankedJob(
                    job=job, rank=1, score=score, score_components=components, evidence=matches
                )
            )
        ranked.sort(key=lambda row: (-row.score, row.job.version_id))
        selected, duplicates, companies = [], set(), Counter()
        for row in ranked:
            job = row.job
            if (
                job.duplicate_key in duplicates
                or companies[job.company.casefold()] >= request.soft_preferences.max_per_company
            ):
                continue
            if not self.index.facts.is_current(job.version_id):
                rejected += 1
                continue
            duplicates.add(job.duplicate_key)
            companies[job.company.casefold()] += 1
            selected.append(row.model_copy(update={"rank": len(selected) + 1}))
            if len(selected) == request.top_k:
                break
        timings["features_dedup"] = (perf_counter() - start) * 1000
        timings["total"] = (perf_counter() - began) * 1000
        return SearchResult(
            jobs=tuple(selected),
            corpus_version=snapshot.snapshot_id,
            index_version=manifest["index_id"],
            search_config_hash=digest(
                {
                    "config": self.config.model_dump(mode="json"),
                    "constraint_parser": CITY_PARSER_VERSION,
                    "encoder": manifest["encoder_identity"],
                    "reranker": self.reranker.identity
                    if self.config.mode == "hybrid-rerank"
                    else "none",
                }
            ),
            candidate_profile_version=request.candidate_profile_version,
            as_of=as_of,
            stage_duration_ms=timings,
            candidates_retrieved=len(fused),
            rejected_by_fact_check=rejected,
            effective_hard_constraints=constraints,
            city_constraint_matches=city_matches,
            constraint_parser_version=CITY_PARSER_VERSION,
        )

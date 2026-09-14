"""Immutable Qdrant collections, explicit BM25 sparse vectors, and recoverable activation."""

import math
from collections import Counter
from datetime import datetime
from time import perf_counter
from uuid import UUID, uuid4

from qdrant_client import QdrantClient, models

from getoffers_agent.domain.contracts import digest
from getoffers_agent.job_search.contracts import (
    CorpusSnapshot,
    HardConstraints,
    SearchConfig,
    tokens,
)
from getoffers_agent.job_search.models import DenseEncoder
from getoffers_agent.job_search.store import JobFactStore


def point_id(version_id: str) -> str:
    return str(UUID(version_id[:32]))


class QdrantJobIndex:
    def __init__(self, client: QdrantClient, facts: JobFactStore):
        self.client, self.facts = client, facts

    def build(
        self, snapshot: CorpusSnapshot, config: SearchConfig, encoder: DenseEncoder | None = None
    ) -> dict:
        if config.mode != "lexical" and encoder is None:
            raise ValueError("dense_encoder_required")
        started = perf_counter()
        jobs = [self.facts.get(entry.version_id) for entry in snapshot.entries]
        seen = {entry.version_id: entry.last_seen_at for entry in snapshot.entries}
        jobs = [job for job in jobs if job.completeness == "full"]
        if not jobs:
            raise ValueError("no_full_job_descriptions")
        counters = [Counter(tokens(job.full_text)) for job in jobs]
        vocabulary = {term: i for i, term in enumerate(sorted({t for c in counters for t in c}))}
        average_length = sum(sum(c.values()) for c in counters) / len(counters)
        frequencies = Counter(t for counts in counters for t in counts)
        inverse_frequency = {
            t: math.log(1 + (len(jobs) - n + 0.5) / (n + 0.5)) for t, n in frequencies.items()
        }
        index_id = uuid4().hex
        collection = "job_versions_v1_" + index_id
        manifest = {
            "schema_version": 1,
            "index_id": index_id,
            "collection_name": collection,
            "snapshot_id": snapshot.snapshot_id,
            "version_ids": [job.version_id for job in jobs],
            "version_set_hash": digest(sorted(job.version_id for job in jobs)),
            "config": config.model_dump(mode="json"),
            "vocabulary": vocabulary,
            "encoder_identity": encoder.identity if encoder else "none",
            "dimension": encoder.dimension if encoder else 0,
            "bm25": "explicit-corpus-idf-sparse-v1",
            "average_length": average_length,
        }
        self.facts.save_index(manifest, "building")
        try:
            vectors = encoder.encode([job.full_text for job in jobs]) if encoder else []
            if encoder and (
                len(vectors) != len(jobs)
                or any(
                    len(v) != encoder.dimension or not all(math.isfinite(x) for x in v)
                    for v in vectors
                )
            ):
                raise ValueError("invalid_encoder_output")
            self.client.create_collection(
                collection_name=collection,
                vectors_config={
                    "dense": models.VectorParams(
                        size=encoder.dimension, distance=models.Distance.COSINE
                    )
                }
                if encoder
                else {},
                sparse_vectors_config={"bm25": models.SparseVectorParams()},
            )
            points = []
            for i, (job, counts) in enumerate(zip(jobs, counters, strict=True)):
                length = sum(counts.values())
                terms = sorted(counts)
                weights = [
                    inverse_frequency[t]
                    * counts[t]
                    * (config.bm25_k1 + 1)
                    / (
                        counts[t]
                        + config.bm25_k1
                        * (1 - config.bm25_b + config.bm25_b * length / average_length)
                    )
                    for t in terms
                ]
                vector = {
                    "bm25": models.SparseVector(
                        indices=[vocabulary[t] for t in terms], values=weights
                    )
                }
                if encoder:
                    vector["dense"] = vectors[i]
                # Only filter metadata belongs in payload. Result text comes from the fact store.
                payload = {
                    "version_id": job.version_id,
                    "visibility": job.visibility,
                    "tenant_id": job.tenant_id or "",
                    "cities": list(job.cities),
                    "recruitment_type": job.recruitment_type,
                    "company": job.company,
                    "last_seen": seen[job.version_id].timestamp(),
                    "expires_at": job.expires_at.timestamp() if job.expires_at else 253402300799,
                    "active": True,
                }
                points.append(
                    models.PointStruct(id=point_id(job.version_id), vector=vector, payload=payload)
                )
            for start in range(0, len(points), 64):
                self.client.upsert(collection, points[start : start + 64], wait=True)
            self.validate(manifest)
            manifest["build_duration_ms"] = (perf_counter() - started) * 1000
            self.facts.save_index(manifest, "validated")
            return manifest
        except Exception:
            self.facts.save_index(manifest, "failed")
            raise

    def activate(self, index_id: str) -> bool:
        # SQLite/D1 pointer is the authority. Search uses the immutable physical collection.
        # The Qdrant alias is repairable metadata; there is no cross-store transaction.
        manifest = self.facts.index(index_id)
        self.validate(manifest)
        self.facts.activate(index_id)
        return self.reconcile_alias()

    def validate(self, manifest: dict):
        retrieved, offset = [], None
        while True:
            page, offset = self.client.scroll(
                manifest["collection_name"],
                offset=offset,
                limit=256,
                with_payload=True,
                with_vectors=False,
            )
            retrieved.extend((str(point.id), point.payload.get("version_id")) for point in page)
            if offset is None:
                break
        expected = sorted((point_id(key), key) for key in manifest["version_ids"])
        if sorted(retrieved) != expected:
            raise ValueError("index_manifest_mismatch")

    def reconcile_alias(self) -> bool:
        manifest = self.facts.index()
        try:
            aliases = self.client.get_aliases().aliases
            actions = []
            if any(alias.alias_name == "job_versions_v1" for alias in aliases):
                actions.append(
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name="job_versions_v1")
                    )
                )
            actions.append(
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        alias_name="job_versions_v1", collection_name=manifest["collection_name"]
                    )
                )
            )
            self.client.update_collection_aliases(actions)
            return True
        except Exception:
            return False

    @staticmethod
    def query_filter(tenant: str, constraints: HardConstraints, as_of: datetime) -> models.Filter:
        # Neither a model-generated dictionary nor a caller-supplied Qdrant filter is accepted.
        visibility = models.Filter(
            should=[
                models.FieldCondition(key="visibility", match=models.MatchValue(value="shared")),
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="visibility", match=models.MatchValue(value="private")
                        ),
                        models.FieldCondition(
                            key="tenant_id", match=models.MatchValue(value=tenant)
                        ),
                    ]
                ),
            ]
        )
        must = [
            visibility,
            models.FieldCondition(key="active", match=models.MatchValue(value=True)),
            models.FieldCondition(
                key="last_seen",
                range=models.Range(
                    gte=as_of.timestamp() - constraints.max_age_days * 86400, lte=as_of.timestamp()
                ),
            ),
            models.FieldCondition(key="expires_at", range=models.Range(gt=as_of.timestamp())),
        ]
        if constraints.cities:
            must.append(
                models.FieldCondition(
                    key="cities", match=models.MatchAny(any=list(constraints.cities))
                )
            )
        if constraints.recruitment_types:
            must.append(
                models.FieldCondition(
                    key="recruitment_type",
                    match=models.MatchAny(any=list(constraints.recruitment_types)),
                )
            )
        must_not = []
        if constraints.excluded_cities:
            must_not.append(
                models.FieldCondition(
                    key="cities", match=models.MatchAny(any=list(constraints.excluded_cities))
                )
            )
        return models.Filter(must=must, must_not=must_not)

    def query(
        self,
        manifest: dict,
        vector,
        using: str,
        tenant: str,
        constraints: HardConstraints,
        as_of: datetime,
        limit: int,
        allowed_ids: list[str],
    ) -> list[tuple[str, float]]:
        if not allowed_ids:
            return []
        query_filter = self.query_filter(tenant, constraints, as_of)
        query_filter.must.append(models.HasIdCondition(has_id=[point_id(i) for i in allowed_ids]))
        result = self.client.query_points(
            manifest["collection_name"],
            query=vector,
            using=using,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [(point.payload["version_id"], point.score) for point in result.points]

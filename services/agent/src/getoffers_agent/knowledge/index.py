"""Immutable per-tenant BM25/dense snapshots with authoritative candidate filtering."""

import json
import math
from collections import Counter
from uuid import uuid4

from qdrant_client import models

from getoffers_agent.job_search.contracts import tokens
from getoffers_agent.job_search.index import point_id
from getoffers_agent.job_search.search import reciprocal_rank_fusion
from getoffers_agent.knowledge.contracts import KnowledgeError


class EvidenceIndex:
    def __init__(self, client, store, encoder=None, reranker=None):
        self.client, self.store = client, store
        self.encoder, self.reranker = encoder, reranker

    def build(self, tenant, units):
        index_id = uuid4().hex
        collection = "evidence_units_v1_" + index_id
        counts = [Counter(tokens(u.text)) for u in units]
        vocab = {t: i for i, t in enumerate(sorted({t for c in counts for t in c}))}
        freq = Counter(t for c in counts for t in c)
        average = sum(sum(c.values()) for c in counts) / max(1, len(counts)) or 1
        manifest = {
            "index_id": index_id,
            "collection": collection,
            "tenant_id": tenant,
            "evidence_ids": [u.evidence_id for u in units],
            "vocabulary": vocab,
            "encoder": self.encoder.identity if self.encoder else "none",
            "config": {"version": "evidence-bm25-v1", "k1": 1.2, "b": 0.75, "rrf_k": 60},
        }
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO knowledge_indexes VALUES(?,?,?,?,?)",
                (index_id, tenant, collection, "building", json.dumps(manifest)),
            )
        try:
            self.client.create_collection(
                collection,
                vectors_config={
                    "dense": models.VectorParams(
                        size=self.encoder.dimension, distance=models.Distance.COSINE
                    )
                }
                if self.encoder
                else {},
                sparse_vectors_config={"bm25": models.SparseVectorParams()},
            )
            vectors = self.encoder.encode([u.text for u in units]) if self.encoder and units else []
            if self.encoder and (
                len(vectors) != len(units)
                or any(
                    len(v) != self.encoder.dimension or not all(math.isfinite(x) for x in v)
                    for v in vectors
                )
            ):
                raise KnowledgeError("invalid_encoder_output")
            points = []
            for i, (unit, counter) in enumerate(zip(units, counts, strict=True)):
                terms = sorted(counter)
                weights = [
                    math.log(1 + (len(units) - freq[t] + 0.5) / (freq[t] + 0.5))
                    * counter[t]
                    * 2.2
                    / (counter[t] + 1.2 * (0.25 + 0.75 * sum(counter.values()) / average))
                    for t in terms
                ]
                vector = {
                    "bm25": models.SparseVector(indices=[vocab[t] for t in terms], values=weights)
                }
                if self.encoder:
                    vector["dense"] = vectors[i]
                points.append(
                    models.PointStruct(
                        id=point_id(unit.evidence_id),
                        vector=vector,
                        payload={
                            "tenant_id": tenant,
                            "document_id": unit.document_id,
                            "version_id": unit.version_id,
                            "evidence_id": unit.evidence_id,
                        },
                    )
                )
            for start in range(0, len(points), 64):
                self.client.upsert(collection, points[start : start + 64], wait=True)
            found, offset = [], None
            while True:
                rows, offset = self.client.scroll(
                    collection, limit=256, offset=offset, with_payload=True
                )
                found.extend(
                    (str(r.id), r.payload["tenant_id"], r.payload["evidence_id"]) for r in rows
                )
                if offset is None:
                    break
            if sorted(found) != sorted(
                (point_id(u.evidence_id), tenant, u.evidence_id) for u in units
            ):
                raise KnowledgeError("index_validation_failed")
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_indexes SET status='validated' WHERE index_id=?", (index_id,)
                )
            return manifest
        except Exception:
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_indexes SET status='failed' WHERE index_id=?", (index_id,)
                )
            raise

    def rank(self, manifest, tenant, query, units):
        if manifest["tenant_id"] != tenant:
            raise KnowledgeError("index_tenant_mismatch")
        if query.mode != "lexical" and (
            not self.encoder or self.encoder.identity != manifest["encoder"]
        ):
            raise KnowledgeError("matching_encoder_required")
        if query.mode == "hybrid-rerank" and not self.reranker:
            raise KnowledgeError("reranker_required")
        allowed = {u.evidence_id: u for u in units}
        if not allowed:
            return []
        filters = models.Filter(
            must=[
                models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant)),
                models.HasIdCondition(has_id=[point_id(k) for k in allowed]),
            ]
        )
        rankings = []

        def retrieve(vector, using):
            rows = self.client.query_points(
                manifest["collection"],
                query=vector,
                using=using,
                query_filter=filters,
                limit=min(100, len(allowed)),
                with_payload=True,
            ).points
            # Text and authorization come only from SQLite/D1, never from index payload.
            return [
                r.payload["evidence_id"]
                for r in rows
                if r.payload.get("tenant_id") == tenant
                and r.payload.get("evidence_id") in allowed
                and str(r.id) == point_id(r.payload["evidence_id"])
            ]

        if query.mode != "dense":
            indices = sorted(
                {
                    manifest["vocabulary"][t]
                    for t in tokens(query.query)
                    if t in manifest["vocabulary"]
                }
            )
            if indices:
                rankings.append(
                    retrieve(
                        models.SparseVector(indices=indices, values=[1.0] * len(indices)), "bm25"
                    )
                )
        if query.mode != "lexical":
            vectors = self.encoder.encode([query.query])
            if (
                len(vectors) != 1
                or len(vectors[0]) != self.encoder.dimension
                or not all(math.isfinite(v) for v in vectors[0])
            ):
                raise KnowledgeError("invalid_query_embedding")
            rankings.append(retrieve(vectors[0], "dense"))
        scores = reciprocal_rank_fusion(rankings, 60)
        ids = sorted(scores, key=lambda k: (-scores[k], k))
        if query.mode == "hybrid-rerank" and ids:
            values = self.reranker.score(query.query, [allowed[k].text for k in ids])
            if len(values) != len(ids) or not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
                raise KnowledgeError("invalid_reranker_output")
            scores = dict(zip(ids, values, strict=True))
            ids.sort(key=lambda k: (-scores[k], k))
        return [(allowed[k], scores[k]) for k in ids]

    def purge_tenant(self, tenant):
        # Old manifests contain private vocabulary too. Delete every historical snapshot.
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT collection_name FROM knowledge_indexes WHERE tenant_id=?", (tenant,)
            ).fetchall()
        for row in rows:
            name = row[0]
            if self.client.collection_exists(name):
                self.client.delete_collection(name)
            if self.client.collection_exists(name):
                raise KnowledgeError("index_delete_unverified")
        with self.store.connect() as db:
            db.execute("DELETE FROM knowledge_active_index WHERE tenant_id=?", (tenant,))
            db.execute("DELETE FROM knowledge_indexes WHERE tenant_id=?", (tenant,))

"""Knowledge lifecycle; local transactions plus explicit, retryable external steps."""

import fcntl
import hashlib
import json
from functools import wraps
from threading import RLock
from time import perf_counter
from uuid import uuid4

from getoffers_agent.domain.contracts import canonical_json, digest, utcnow
from getoffers_agent.knowledge.contracts import (
    CanonicalDocument,
    EvidenceUnit,
    KnowledgeConfig,
    KnowledgeError,
)
from getoffers_agent.knowledge.parsing import DocumentParser, make_units, validate_upload


def serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock, self.store.path.with_suffix(".lock").open("a") as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            try:
                return method(self, *args, **kwargs)
            finally:
                fcntl.flock(lockfile, fcntl.LOCK_UN)

    return wrapped


class KnowledgeService:
    def __init__(self, store, artifacts, index, config=None, parser=None):
        self.store, self.artifacts, self.index = store, artifacts, index
        self.config = config or KnowledgeConfig()
        self.parser = parser or DocumentParser(self.config)
        self.lock = RLock()

    @staticmethod
    def authorize(security, capability):
        if capability not in security.capabilities:
            raise PermissionError("knowledge_denied")

    def document(self, document_id, tenant):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledge_documents WHERE document_id=? AND tenant_id=?",
                (document_id, tenant),
            ).fetchone()
        if not row or row["status"] == "deleted":
            raise KnowledgeError("document_not_found")
        return dict(row)

    def list_documents(self, security):
        self.authorize(security, "knowledge:read:self")
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM knowledge_documents WHERE tenant_id=? AND "
                "status!='deleted' ORDER BY created_at DESC",
                (security.tenant_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item.pop("tenant_id")
                item["versions"] = [
                    dict(v)
                    for v in db.execute(
                        "SELECT version_id,status,error,created_at,extension FROM "
                        "knowledge_versions WHERE document_id=? ORDER BY created_at "
                        "DESC",
                        (row["document_id"],),
                    )
                ]
                deletion = db.execute(
                    "SELECT status,stage,error FROM knowledge_deletions WHERE document_id=?",
                    (row["document_id"],),
                ).fetchone()
                item["deletion"] = dict(deletion) if deletion else None
                result.append(item)
            return result

    @serialized
    def upload(self, filename, mime, raw, security, document_id=None):
        self.authorize(security, "knowledge:upload:self")
        extension = validate_upload(filename, mime, raw, self.config)
        if not filename.strip() or len(filename) > 200:
            raise KnowledgeError("invalid_filename")
        if document_id:
            doc = self.document(document_id, security.tenant_id)
            if doc["status"] == "deleting":
                raise KnowledgeError("document_deleting")
        document_id = document_id or uuid4().hex
        content_hash = hashlib.sha256(raw).hexdigest()
        version_id = digest(
            [security.tenant_id, document_id, content_hash, extension, self.config.identity]
        )
        prefix = (
            f"tenant/{digest(security.tenant_id)}/documents/{document_id}/versions/{version_id}"
        )
        source_key, canonical_key = f"{prefix}/source.{extension}", f"{prefix}/canonical.json"
        with self.store.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO knowledge_documents VALUES(?,?,?,?,?,?)",
                (document_id, security.tenant_id, filename, "uploaded", None, utcnow().isoformat()),
            )
            db.execute(
                "INSERT OR IGNORE INTO knowledge_versions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    document_id,
                    content_hash,
                    extension,
                    "uploaded",
                    source_key,
                    canonical_key,
                    self.config.identity,
                    None,
                    utcnow().isoformat(),
                ),
            )
        try:
            self.artifacts.put(source_key, raw)
        except Exception:
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_versions SET "
                    "status='failed',error='artifact_write_failed' WHERE version_id=?",
                    (version_id,),
                )
            raise KnowledgeError("artifact_write_failed") from None
        return {"document_id": document_id, "version_id": version_id}

    def active_units(self, tenant, exclude_document=None):
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT e.body_json FROM knowledge_evidence e
                JOIN knowledge_versions v ON e.version_id=v.version_id
                JOIN knowledge_documents d ON v.document_id=d.document_id
                WHERE d.tenant_id=? AND d.status='active'
                AND d.active_version=v.version_id AND v.status='active'
                ORDER BY d.document_id,e.evidence_id""",
                (tenant,),
            ).fetchall()
        return [
            u
            for row in rows
            if (u := EvidenceUnit.model_validate_json(row[0])).document_id != exclude_document
        ]

    @serialized
    def process(self, document_id, version_id, security):
        self.authorize(security, "knowledge:upload:self")
        doc = self.document(document_id, security.tenant_id)
        if doc["status"] == "deleting":
            raise KnowledgeError("document_deleting")
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledge_versions WHERE document_id=? AND version_id=?",
                (document_id, version_id),
            ).fetchone()
            if not row:
                raise KnowledgeError("version_not_found")
            version = dict(row)
            if doc["active_version"] == version_id:
                return {"status": "active", "version_id": version_id}
            if version["status"] == "superseded":
                raise KnowledgeError("superseded_version")
            if version["config_hash"] != self.config.identity:
                raise KnowledgeError("processing_config_mismatch")
            db.execute(
                "UPDATE knowledge_versions SET status='processing',error=NULL WHERE version_id=?",
                (version_id,),
            )
        try:
            raw = self.artifacts.get(version["source_key"])
            if hashlib.sha256(raw).hexdigest() != version["source_hash"]:
                raise KnowledgeError("source_hash_mismatch")
            canonical = self.parser.parse(raw, version["extension"])
            if canonical.source_hash != version["source_hash"]:
                raise KnowledgeError("canonical_source_hash_mismatch")
            units = make_units(canonical, security.tenant_id, document_id, version_id, self.config)
            self.artifacts.put(version["canonical_key"], canonical.model_dump_json().encode())
            manifest = self.index.build(
                security.tenant_id, self.active_units(security.tenant_id, document_id) + list(units)
            )
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_versions SET status='superseded' WHERE "
                    "document_id=? AND status='active'",
                    (document_id,),
                )
                db.execute(
                    "UPDATE candidate_facts SET status='superseded' WHERE document_id=?",
                    (document_id,),
                )
                db.execute("DELETE FROM knowledge_evidence WHERE version_id=?", (version_id,))
                db.executemany(
                    "INSERT INTO knowledge_evidence VALUES(?,?,?)",
                    [(u.evidence_id, version_id, u.model_dump_json()) for u in units],
                )
                db.execute(
                    "UPDATE knowledge_versions SET status='active',error=NULL WHERE version_id=?",
                    (version_id,),
                )
                db.execute(
                    "UPDATE knowledge_documents SET status='active',active_version=? "
                    "WHERE document_id=?",
                    (version_id, document_id),
                )
                db.execute(
                    "INSERT OR REPLACE INTO knowledge_active_index VALUES(?,?)",
                    (security.tenant_id, manifest["index_id"]),
                )
                # Preserve source wording without inferring proficiency.
                for unit in units:
                    if (
                        len(unit.text.strip()) < 8
                        or next(
                            n for n in canonical.nodes if n.node_id == unit.locator.node_id
                        ).kind
                        == "heading"
                    ):
                        continue
                    fact_id = digest([unit.evidence_id, "extractive-claim-v1"])
                    body = {
                        "fact_id": fact_id,
                        "kind": "source_statement",
                        "value": unit.text,
                        "evidence_ids": [unit.evidence_id],
                        "extractor_version": "extractive-claim-v1",
                        "history": [],
                    }
                    db.execute(
                        "INSERT OR IGNORE INTO candidate_facts VALUES(?,?,?,?,?,?)",
                        (fact_id, document_id, version_id, "proposed", 0, canonical_json(body)),
                    )
            return {"status": "active", "version_id": version_id, "evidence_count": len(units)}
        except Exception as exc:
            category = str(exc) if isinstance(exc, KnowledgeError) else "processing_failed"
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_versions SET status='failed',error=? WHERE "
                    "version_id=? AND status!='active'",
                    (category, version_id),
                )
            raise KnowledgeError(category) from None

    def _citation(self, evidence_id, tenant):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT e.body_json,v.canonical_key FROM knowledge_evidence e JOIN "
                "knowledge_versions v ON e.version_id=v.version_id JOIN "
                "knowledge_documents d ON v.document_id=d.document_id WHERE "
                "e.evidence_id=? AND d.tenant_id=? AND d.status='active' AND "
                "d.active_version=v.version_id AND v.status='active'",
                (evidence_id, tenant),
            ).fetchone()
        if not row:
            raise KnowledgeError("evidence_not_found")
        unit = EvidenceUnit.model_validate_json(row[0])
        canonical = CanonicalDocument.model_validate_json(self.artifacts.get(row[1]))
        node = next(n for n in canonical.nodes if n.node_id == unit.locator.node_id)
        if (
            unit.text != node.text[unit.locator.start : unit.locator.end]
            or unit.source_hash != canonical.source_hash
        ):
            raise KnowledgeError("citation_mismatch")
        return {
            "evidence": unit.model_dump(mode="json"),
            "source_node": node.model_dump(mode="json"),
        }

    @serialized
    def citation(self, evidence_id, security):
        self.authorize(security, "knowledge:read:self")
        return self._citation(evidence_id, security.tenant_id)

    @serialized
    def retrieve(self, query, security):
        self.authorize(security, "knowledge:read:self")
        began = perf_counter()
        for key in query.document_ids:
            doc = self.document(key, security.tenant_id)
            if doc["status"] != "active":
                raise KnowledgeError("document_not_active")
        units = [
            u for u in self.active_units(security.tenant_id) if u.document_id in query.document_ids
        ]
        with self.store.connect() as db:
            row = db.execute(
                "SELECT i.manifest_json FROM knowledge_indexes i JOIN "
                "knowledge_active_index a ON a.index_id=i.index_id WHERE a.tenant_id=? "
                "AND i.status='validated'",
                (security.tenant_id,),
            ).fetchone()
        if not row:
            raise KnowledgeError("index_unavailable")
        manifest = json.loads(row[0])
        ranked = self.index.rank(manifest, security.tenant_id, query, units)
        candidates = []
        for unit, score in ranked[: query.top_k]:
            candidates.append((unit, score, False))
            if query.expand_neighbors:
                candidates.extend(
                    (u, score, True)
                    for u in units
                    if u.version_id == unit.version_id
                    and u.parent_node_id == unit.parent_node_id
                    and abs(u.order - unit.order) == 1
                )
        selected, seen, texts, context = [], set(), set(), "[]"
        for unit, score, expanded in candidates:
            if unit.evidence_id in seen or unit.text in texts:
                continue
            self._citation(unit.evidence_id, security.tenant_id)
            entry = {
                "evidence_id": unit.evidence_id,
                "document_id": unit.document_id,
                "version_id": unit.version_id,
                "quote": unit.text,
                "locator": unit.locator.model_dump(mode="json"),
                "path": list(unit.path),
                "table_header": unit.table_header,
                "trust": unit.trust,
                "score": score,
                "expanded": expanded,
            }
            tentative = canonical_json(selected + [entry])
            if len(tentative.encode()) > query.token_budget:
                continue
            selected.append(entry)
            seen.add(unit.evidence_id)
            texts.add(unit.text)
            context = tentative
        return {
            "evidence": selected,
            "context": context,
            "token_upper_bound": len(context.encode()),
            "token_counter": self.config.token_counter,
            "config_hash": digest(
                [
                    self.config.identity,
                    manifest["config"],
                    query.mode,
                    manifest["encoder"],
                    self.index.reranker.identity if query.mode == "hybrid-rerank" else "none",
                ]
            ),
            "index_version": manifest["index_id"],
            "duration_ms": (perf_counter() - began) * 1000,
        }

    def facts(self, security, confirmed_only=False):
        self.authorize(security, "knowledge:read:self")
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT f.* FROM candidate_facts f JOIN knowledge_documents d ON "
                "f.document_id=d.document_id WHERE d.tenant_id=? AND d.status='active' "
                "AND d.active_version=f.version_id",
                (security.tenant_id,),
            ).fetchall()
        result = []
        for row in rows:
            if confirmed_only and row["status"] not in {"user_confirmed", "user_corrected"}:
                continue
            result.append(
                {
                    **json.loads(row["body_json"]),
                    "status": row["status"],
                    "revision": row["revision"],
                    "document_id": row["document_id"],
                }
            )
        return result

    @serialized
    def review(self, review, security):
        self.authorize(security, "candidate_fact:review:self")
        facts = {f["fact_id"]: f for f in self.facts(security)}
        fact = facts.get(review.fact_id)
        if not fact:
            raise KnowledgeError("fact_not_found")
        if fact["revision"] != review.expected_revision:
            raise KnowledgeError("fact_revision_conflict")
        for key in fact["evidence_ids"]:
            self._citation(key, security.tenant_id)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT body_json FROM candidate_facts WHERE fact_id=?", (review.fact_id,)
            ).fetchone()
            body = json.loads(row[0])
            body["history"].append(
                {
                    "status": fact["status"],
                    "value": body["value"],
                    "revision": fact["revision"],
                    "reviewer": security.actor_id,
                    "at": utcnow().isoformat(),
                }
            )
            if review.action == "correct":
                body["value"] = review.corrected_value
            status = {
                "confirm": "user_confirmed",
                "correct": "user_corrected",
                "reject": "rejected",
            }[review.action]
            db.execute(
                "UPDATE candidate_facts SET status=?,revision=revision+1,body_json=? "
                "WHERE fact_id=?",
                (status, canonical_json(body), review.fact_id),
            )
        return {"status": status, "revision": fact["revision"] + 1}

    @serialized
    def source(self, document_id, version_id, security):
        self.authorize(security, "knowledge:read:self")
        doc = self.document(document_id, security.tenant_id)
        if doc["status"] == "deleting":
            raise KnowledgeError("document_deleting")
        with self.store.connect() as db:
            row = db.execute(
                "SELECT source_key,extension FROM knowledge_versions WHERE "
                "document_id=? AND version_id=?",
                (document_id, version_id),
            ).fetchone()
        if not row:
            raise KnowledgeError("version_not_found")
        return self.artifacts.get(row[0]), row[1]

    @serialized
    def delete(self, document_id, security):
        self.authorize(security, "knowledge:delete:self")
        with self.store.connect() as db:
            doc = db.execute(
                "SELECT * FROM knowledge_documents WHERE document_id=? AND tenant_id=?",
                (document_id, security.tenant_id),
            ).fetchone()
            if not doc:
                raise KnowledgeError("document_not_found")
            if doc["status"] == "deleted":
                return {"status": "deleted", "verified": True}
            db.execute(
                "UPDATE knowledge_documents SET status='deleting' WHERE document_id=?",
                (document_id,),
            )
            db.execute(
                "INSERT OR REPLACE INTO knowledge_deletions VALUES(?,?,?,?,?,?)",
                (document_id, security.tenant_id, "deleting", "index", None, utcnow().isoformat()),
            )
            versions = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM knowledge_versions WHERE document_id=?", (document_id,)
                )
            ]
        stage = "index"
        try:
            self.index.purge_tenant(security.tenant_id)
            stage = "artifacts"
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_deletions SET stage=? WHERE document_id=?",
                    (stage, document_id),
                )
            for version in versions:
                for key in (version["source_key"], version["canonical_key"]):
                    self.artifacts.delete(key)
                    if self.artifacts.exists(key):
                        raise KnowledgeError("artifact_delete_unverified")
            stage = "derived_facts"
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_deletions SET stage=? WHERE document_id=?",
                    (stage, document_id),
                )
                db.execute("DELETE FROM candidate_facts WHERE document_id=?", (document_id,))
                db.execute(
                    "DELETE FROM knowledge_evidence WHERE version_id IN (SELECT "
                    "version_id FROM knowledge_versions WHERE document_id=?)",
                    (document_id,),
                )
            stage = "rebuild_remaining"
            remaining = self.active_units(security.tenant_id)
            manifest = self.index.build(security.tenant_id, remaining) if remaining else None
            with self.store.connect() as db:
                if manifest:
                    db.execute(
                        "INSERT OR REPLACE INTO knowledge_active_index VALUES(?,?)",
                        (security.tenant_id, manifest["index_id"]),
                    )
                db.execute("DELETE FROM knowledge_versions WHERE document_id=?", (document_id,))
                db.execute(
                    "UPDATE knowledge_documents SET "
                    "name='',status='deleted',active_version=NULL WHERE document_id=?",
                    (document_id,),
                )
                db.execute(
                    "UPDATE knowledge_deletions SET "
                    "status='deleted',stage='verified',error=NULL,updated_at=? WHERE "
                    "document_id=?",
                    (utcnow().isoformat(), document_id),
                )
            return {"status": "deleted", "verified": True}
        except Exception:
            with self.store.connect() as db:
                db.execute(
                    "UPDATE knowledge_deletions SET "
                    "stage=?,error='delete_step_failed',updated_at=? WHERE "
                    "document_id=?",
                    (stage, utcnow().isoformat(), document_id),
                )
            return {"status": "deleting", "stage": stage, "verified": False}

    def reconcile(self, security):
        self.authorize(security, "knowledge:delete:self")
        with self.store.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT document_id FROM knowledge_deletions WHERE tenant_id=? AND "
                    "status='deleting'",
                    (security.tenant_id,),
                )
            ]
        return [self.delete(key, security) for key in ids]

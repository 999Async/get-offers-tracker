"""Local D1-compatible facts and content-addressed R2-compatible artifacts."""

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Protocol

from getoffers_agent.knowledge.contracts import KnowledgeError

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS knowledge_documents(
 document_id TEXT PRIMARY KEY NOT NULL, tenant_id TEXT NOT NULL, name TEXT NOT NULL,
 status TEXT NOT NULL, active_version TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS knowledge_documents_owner ON knowledge_documents(tenant_id);
CREATE TABLE IF NOT EXISTS knowledge_versions(
 version_id TEXT PRIMARY KEY NOT NULL,
 document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id),
 source_hash TEXT NOT NULL, extension TEXT NOT NULL, status TEXT NOT NULL,
 source_key TEXT NOT NULL, canonical_key TEXT NOT NULL, config_hash TEXT NOT NULL,
 error TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_evidence(
 evidence_id TEXT PRIMARY KEY NOT NULL,
 version_id TEXT NOT NULL REFERENCES knowledge_versions(version_id),
 body_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS knowledge_evidence_version ON knowledge_evidence(version_id);
CREATE TABLE IF NOT EXISTS candidate_facts(
 fact_id TEXT PRIMARY KEY NOT NULL,
 document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id),
 version_id TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
 body_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_indexes(
 index_id TEXT PRIMARY KEY NOT NULL, tenant_id TEXT NOT NULL, collection_name TEXT NOT NULL,
 status TEXT NOT NULL, manifest_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_active_index(
 tenant_id TEXT PRIMARY KEY NOT NULL, index_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_deletions(
 document_id TEXT PRIMARY KEY NOT NULL, tenant_id TEXT NOT NULL, status TEXT NOT NULL,
 stage TEXT NOT NULL, error TEXT, updated_at TEXT NOT NULL);
"""


class KnowledgeStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        return db


class ArtifactStore(Protocol):
    def put(self, key: str, content: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalArtifacts:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise KnowledgeError("invalid_artifact_key")
        return target

    def put(self, key, content):
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(target.name + ".pending")
        try:
            with staging.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(staging, target)
        except FileExistsError:
            if target.read_bytes() != content:
                raise KnowledgeError("immutable_artifact_conflict") from None
        finally:
            staging.unlink(missing_ok=True)

    def get(self, key):
        return self.path(key).read_bytes()

    def exists(self, key):
        return self.path(key).is_file()

    def delete(self, key):
        target = self.path(key)
        target.unlink(missing_ok=True)
        target.with_name(target.name + ".pending").unlink(missing_ok=True)


class R2Artifacts:
    """Injected S3 client for a dedicated private R2 bucket; never browser credentials."""

    def __init__(self, client, bucket: str):
        self.client, self.bucket = client, bucket

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in {
                "404",
                "NoSuchKey",
                "NotFound",
            }:
                return False
            raise

    def put(self, key, content):
        if self.exists(key):
            if self.get(key) != content:
                raise KnowledgeError("immutable_artifact_conflict")
            return
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            Metadata={"sha256": hashlib.sha256(content).hexdigest()},
            IfNoneMatch="*",
        )

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

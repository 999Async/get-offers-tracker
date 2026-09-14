"""Local fact adapter using the same SQLite schema as D1. Vectors are never facts."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from getoffers_agent.domain.contracts import SecurityContext, digest
from getoffers_agent.job_search.contracts import (
    CorpusSnapshot,
    JobInput,
    JobVersion,
    SnapshotEntry,
    normalize,
    now,
)


class JobFactStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        with self.connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text())

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, jobs: list[JobInput], security: SecurityContext) -> dict:
        if "job:ingest" not in security.capabilities:
            raise PermissionError("job_ingest_denied")
        for job in jobs:
            if (
                job.visibility == "private"
                and job.tenant_id != security.tenant_id
                or job.visibility == "shared"
                and "job:ingest:shared" not in security.capabilities
            ):
                raise PermissionError("job_owner_mismatch")
        report = {
            "ingestion_id": str(uuid4()),
            "new_versions": 0,
            "unchanged": 0,
            "out_of_order": 0,
            "summary_only": 0,
        }
        with self.ingestion_transaction(report) as db:
            db.execute("BEGIN IMMEDIATE")
            for source in jobs:
                job = normalize(source)
                current = db.execute(
                    "SELECT * FROM job_current WHERE job_id=?", (job.job_id,)
                ).fetchone()
                stamp = job.observed_at.isoformat()
                if current and stamp < current["last_seen_at"]:
                    report["out_of_order"] += 1
                    continue
                if (
                    current
                    and stamp == current["last_seen_at"]
                    and current["version_id"] != job.version_id
                ):
                    raise ValueError("conflicting_capture_timestamp")
                origin = urlsplit(str(job.source_url))
                db.execute(
                    "INSERT OR IGNORE INTO job_sources VALUES (?, ?)",
                    (job.source_id, f"{origin.scheme}://{origin.netloc}"),
                )
                exists = db.execute(
                    "SELECT 1 FROM job_versions WHERE version_id=?", (job.version_id,)
                ).fetchone()
                if not exists:
                    db.execute(
                        "INSERT INTO job_versions VALUES (?, ?, ?, ?, ?)",
                        (
                            job.version_id,
                            job.job_id,
                            job.source_id,
                            job.content_hash,
                            job.model_dump_json(),
                        ),
                    )
                report["unchanged" if exists else "new_versions"] += 1
                report["summary_only"] += job.completeness == "summary"
                db.execute(
                    """INSERT INTO job_current VALUES (?, ?, ?, 1)
                    ON CONFLICT(job_id) DO UPDATE SET version_id=excluded.version_id,
                    last_seen_at=excluded.last_seen_at, active=1""",
                    (job.job_id, job.version_id, stamp),
                )
            db.execute(
                "UPDATE job_ingestion_runs SET status='completed',report_json=? "
                "WHERE ingestion_id=?",
                (json.dumps(report), report["ingestion_id"]),
            )
        return report

    @contextmanager
    def ingestion_transaction(self, report: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO job_ingestion_runs VALUES (?,?,'running',?)",
                (report["ingestion_id"], now().isoformat(), json.dumps(report)),
            )
        try:
            with self.connect() as db:
                yield db
        except Exception:
            with self.connect() as db:
                db.execute(
                    "UPDATE job_ingestion_runs SET status='failed',report_json=? "
                    "WHERE ingestion_id=?",
                    (
                        json.dumps({"error": "ingestion_failed", "rolled_back": True}),
                        report["ingestion_id"],
                    ),
                )
            raise

    def get(self, version_id: str) -> JobVersion:
        with self.connect() as db:
            row = db.execute(
                "SELECT body_json FROM job_versions WHERE version_id=?", (version_id,)
            ).fetchone()
        if row is None:
            raise ValueError("unknown_job_version")
        return JobVersion.model_validate_json(row["body_json"])

    def is_current(self, version_id: str) -> bool:
        with self.connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM job_current WHERE version_id=? AND active=1", (version_id,)
                ).fetchone()
                is not None
            )

    def deactivate(self, job_id: str, security: SecurityContext):
        with self.connect() as db:
            row = db.execute(
                "SELECT version_id FROM job_current WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise ValueError("unknown_job")
            job = self.get(row["version_id"])
            if (
                "job:ingest" not in security.capabilities
                or job.visibility == "private"
                and job.tenant_id != security.tenant_id
                or job.visibility == "shared"
                and "job:ingest:shared" not in security.capabilities
            ):
                raise PermissionError("job_owner_mismatch")
            db.execute("UPDATE job_current SET active=0 WHERE job_id=?", (job_id,))

    def snapshot(self, source_kind: str = "imported") -> CorpusSnapshot:
        with self.connect() as db:
            rows = db.execute(
                "SELECT version_id,last_seen_at FROM job_current WHERE active=1 ORDER BY version_id"
            ).fetchall()
            entries = tuple(SnapshotEntry(**dict(row)) for row in rows)
            identity = {
                "entries": [entry.model_dump(mode="json") for entry in entries],
                "source_kind": source_kind,
            }
            snapshot = CorpusSnapshot(
                snapshot_id=digest(identity), entries=entries, source_kind=source_kind
            )
            db.execute(
                "INSERT OR IGNORE INTO job_corpus_snapshots VALUES (?,?)",
                (snapshot.snapshot_id, snapshot.model_dump_json()),
            )
        return snapshot

    def load_snapshot(self, snapshot_id: str) -> CorpusSnapshot:
        with self.connect() as db:
            row = db.execute(
                "SELECT body_json FROM job_corpus_snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise ValueError("unknown_corpus_snapshot")
        return CorpusSnapshot.model_validate_json(row[0])

    def save_index(self, manifest: dict, status: str):
        with self.connect() as db:
            db.execute(
                """INSERT INTO search_index_versions VALUES (?,?,?,?,?)
                ON CONFLICT(index_id) DO UPDATE SET status=excluded.status,
                manifest_json=excluded.manifest_json""",
                (
                    manifest["index_id"],
                    manifest["snapshot_id"],
                    manifest["collection_name"],
                    status,
                    json.dumps(manifest),
                ),
            )

    def index(self, index_id: str | None = None) -> dict:
        with self.connect() as db:
            if index_id is None:
                row = db.execute(
                    "SELECT index_id FROM active_search_index WHERE alias='job_versions_v1'"
                ).fetchone()
                if row is None:
                    raise ValueError("no_active_search_index")
                index_id = row[0]
            row = db.execute(
                "SELECT manifest_json,status FROM search_index_versions WHERE index_id=?",
                (index_id,),
            ).fetchone()
        if row is None:
            raise ValueError("unknown_index_version")
        return {**json.loads(row[0]), "status": row[1]}

    def activate(self, index_id: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,manifest_json FROM search_index_versions WHERE index_id=?",
                (index_id,),
            ).fetchone()
            if row is None or row[0] != "validated":
                raise ValueError("index_not_validated")
            manifest = json.loads(row[1])
            for version_id in manifest["version_ids"]:
                if not db.execute(
                    "SELECT 1 FROM job_current WHERE version_id=? AND active=1", (version_id,)
                ).fetchone():
                    raise ValueError("index_contains_inactive_version")
            db.execute(
                """INSERT INTO active_search_index VALUES ('job_versions_v1',?)
                ON CONFLICT(alias) DO UPDATE SET index_id=excluded.index_id""",
                (index_id,),
            )

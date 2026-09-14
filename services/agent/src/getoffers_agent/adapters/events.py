"""Local append-only stores. Each returned event is detached from stored bytes."""

import fcntl
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from uuid import UUID

from getoffers_agent.domain.contracts import ErrorCategory, RuntimeFault
from getoffers_agent.runtime.events import RunEvent, validate_sequence


class EventStore(Protocol):
    def append(self, events: Sequence[RunEvent]) -> None: ...
    def read(self, run_id: UUID, after_sequence: int = 0) -> list[RunEvent]: ...
    def list_runs(self) -> list[UUID]: ...
    def lock(self, run_id: UUID): ...


class InMemoryEventStore:
    def __init__(self):
        self._runs: dict[UUID, list[str]] = {}
        self._active: set[UUID] = set()

    def read(self, run_id: UUID, after_sequence: int = 0) -> list[RunEvent]:
        return [
            RunEvent.model_validate_json(raw)
            for raw in self._runs.get(run_id, [])
            if RunEvent.model_validate_json(raw).sequence > after_sequence
        ]

    def append(self, events: Sequence[RunEvent]) -> None:
        if not events:
            return
        run_id = events[0].workflow_run_id
        # Re-parse: even frozen Pydantic models can contain mutable nested dictionaries.
        copies = [RunEvent.model_validate_json(event.model_dump_json()) for event in events]
        validate_sequence(self.read(run_id) + copies)
        existing_ids = {
            RunEvent.model_validate_json(raw).event_id for run in self._runs.values() for raw in run
        }
        if any(event.event_id in existing_ids for event in copies):
            raise RuntimeFault(ErrorCategory.CONFLICT)
        self._runs.setdefault(run_id, []).extend(event.model_dump_json() for event in copies)

    def list_runs(self) -> list[UUID]:
        return list(self._runs)

    @contextmanager
    def lock(self, run_id: UUID) -> Iterator[None]:
        if run_id in self._active:
            raise RuntimeFault(ErrorCategory.CONFLICT)
        self._active.add(run_id)
        try:
            yield
        finally:
            self._active.remove(run_id)


class SQLiteEventStore:
    """Single-host store; flock prevents concurrent drivers across connections/processes.

    Append commits before yielding an event or invoking an external effect. OS locks
    release on process exit. This adapter is for a local filesystem, not NFS.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        self._locks = self.path.with_suffix(self.path.suffix + ".locks")
        self._locks.mkdir(mode=0o700, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE, body TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence))""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS immutable_update
                BEFORE UPDATE ON run_events BEGIN SELECT RAISE(ABORT, 'append only'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS immutable_delete
                BEFORE DELETE ON run_events BEGIN SELECT RAISE(ABORT, 'append only'); END""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self, run_id: UUID, after_sequence: int = 0) -> list[RunEvent]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT body FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence",
                (str(run_id), after_sequence),
            ).fetchall()
        return [RunEvent.model_validate_json(row[0]) for row in rows]

    def append(self, events: Sequence[RunEvent]) -> None:
        if not events:
            return
        copies = [RunEvent.model_validate_json(event.model_dump_json()) for event in events]
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT body FROM run_events WHERE run_id=? ORDER BY sequence",
                    (str(copies[0].workflow_run_id),),
                )
                validate_sequence(
                    [RunEvent.model_validate_json(row[0]) for row in existing] + copies
                )
                db.executemany(
                    "INSERT INTO run_events VALUES (?, ?, ?, ?)",
                    [
                        (str(e.workflow_run_id), e.sequence, str(e.event_id), e.model_dump_json())
                        for e in copies
                    ],
                )
        except sqlite3.IntegrityError:
            raise RuntimeFault(ErrorCategory.CONFLICT) from None

    def list_runs(self) -> list[UUID]:
        with self._connect() as db:
            return [
                UUID(row[0])
                for row in db.execute(
                    "SELECT run_id FROM run_events WHERE sequence=1 ORDER BY rowid"
                )
            ]

    @contextmanager
    def lock(self, run_id: UUID) -> Iterator[None]:
        with (self._locks / str(run_id)).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeFault(ErrorCategory.CONFLICT) from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

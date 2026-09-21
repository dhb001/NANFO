"""Operator-owned SQLite evidence store; exact scope, append-only history, fenced runs."""

import json
import math
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from shadow.evaluate import canonicalHash

from .contracts import MemoryItem, Registry, Request, RuntimeDecision, Scope
from .registry import authorize

MAX_ROWS = 10000
MAX_RECORD_BYTES = 512 * 1024


def scopeKey(scope: Scope) -> str:
    return canonicalHash(scope.model_dump())


class Memory:
    """Filesystem ownership is the operator trust boundary, not backend user auth.

    Never expose this database or registry selection as an untrusted multiuser API.
    Append-only triggers guard application accidents; the file owner is trusted.
    """

    def __init__(self, path: Path):
        if not path.parent.is_dir():
            raise ValueError("memory_parent_missing")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
            ):
                raise ValueError("memory_file_not_private")
        finally:
            os.close(fd)
        self.db = sqlite3.connect(path, timeout=1, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA max_page_count=16384")  # default 4KiB pages: <=64MiB
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError("memory_schema_incompatible")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS memory (
                scope TEXT NOT NULL, id TEXT NOT NULL, session TEXT NOT NULL,
                tier TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
                body TEXT NOT NULL, sha TEXT NOT NULL, PRIMARY KEY(scope,id));
            CREATE INDEX IF NOT EXISTS memory_lookup ON memory(scope,tier,created,id);
            CREATE TABLE IF NOT EXISTS audit (
                sequence INTEGER PRIMARY KEY, scope TEXT NOT NULL, run TEXT NOT NULL,
                kind TEXT NOT NULL, at REAL NOT NULL, body TEXT NOT NULL,
                previous TEXT NOT NULL, sha TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS audit_scope ON audit(scope,sequence);
            CREATE TABLE IF NOT EXISTS runs (
                scope TEXT NOT NULL, id TEXT NOT NULL, input TEXT NOT NULL,
                generation INTEGER NOT NULL, lease REAL NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY(scope,id));
            CREATE TABLE IF NOT EXISTS checkpoints (
                scope TEXT NOT NULL, run TEXT NOT NULL, agent TEXT NOT NULL,
                body TEXT NOT NULL, sha TEXT NOT NULL, PRIMARY KEY(scope,run,agent));
            CREATE TABLE IF NOT EXISTS decisions (
                scope TEXT NOT NULL, run TEXT NOT NULL, body TEXT NOT NULL,
                sha TEXT NOT NULL, PRIMARY KEY(scope,run));
            PRAGMA user_version=1;
        """)
        for table in ("memory", "audit", "checkpoints", "decisions"):
            for operation in ("UPDATE", "DELETE"):
                self.db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_{operation.lower()}_deny
                    BEFORE {operation} ON {table} BEGIN
                    SELECT RAISE(ABORT,'immutable_record'); END""")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def admission(self):
        for table in ("memory", "audit", "runs", "checkpoints", "decisions"):
            if self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= MAX_ROWS:
                raise ValueError("memory_capacity_exhausted")

    @staticmethod
    def body(value: dict) -> tuple[str, str]:
        body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(body.encode()) > MAX_RECORD_BYTES:
            raise ValueError("record_size_exceeded")
        return body, canonicalHash(value)

    @staticmethod
    def checked(body: str, digest: str) -> dict:
        value = json.loads(body)
        if canonicalHash(value) != digest:
            raise ValueError("memory_content_tampered")
        return value

    def event(self, scope: Scope, run: str, kind: str, now: float, value: dict):
        if not math.isfinite(now) or now < 0:
            raise ValueError("invalid_clock")
        key = scopeKey(scope)
        previous = self.db.execute(
            "SELECT sha FROM audit WHERE scope=? ORDER BY sequence DESC LIMIT 1", (key,)
        ).fetchone()
        prior = previous[0] if previous else "0" * 64
        envelope = {
            "scope": scope.model_dump(),
            "run": run,
            "kind": kind,
            "at": now,
            "value": value,
            "previous": prior,
        }
        body, digest = self.body(envelope)
        self.admission()
        self.db.execute(
            "INSERT INTO audit(scope,run,kind,at,body,previous,sha) VALUES(?,?,?,?,?,?,?)",
            (key, run, kind, now, body, prior, digest),
        )

    def ingest(self, registry: Registry, request: Request, item: MemoryItem, now: float):
        authorize(registry, request.scope, "memory_write", now)
        if item.scope != request.scope or item.session_id != request.session_id:
            raise PermissionError("memory_item_scope_denied")
        if not item.created_unix <= now < item.expires():
            raise ValueError("memory_source_expired_or_future")
        with self.transaction():
            self._insertMemory(item)
            self.event(
                item.scope,
                request.run_id,
                "memory_ingested",
                now,
                {"memory_id": item.memory_id, "sha256": canonicalHash(item.model_dump())},
            )

    def _insertMemory(self, item: MemoryItem):
        body, digest = self.body(item.model_dump())
        self.admission()
        self.db.execute(
            "INSERT INTO memory VALUES(?,?,?,?,?,?,?,?)",
            (
                scopeKey(item.scope),
                item.memory_id,
                item.session_id,
                item.tier,
                item.created_unix,
                item.expires(),
                body,
                digest,
            ),
        )

    def retrieve(self, registry: Registry, request: Request, now: float) -> list[MemoryItem]:
        authorize(registry, request.scope, "memory_read", now)
        with self.transaction():
            rows = self.db.execute(
                "SELECT body,sha FROM memory WHERE scope=? AND created<=? AND expires>? "
                "AND (tier!='working' OR session=?) AND tier IN ("
                + ",".join("?" for _ in request.tiers)
                + ") ORDER BY created DESC,id LIMIT ?",
                (
                    scopeKey(request.scope),
                    now,
                    now,
                    request.session_id,
                    *request.tiers,
                    request.retrieval_limit,
                ),
            ).fetchall()
            items = [MemoryItem.model_validate(self.checked(body, pin)) for body, pin in rows]
            if any(
                item.scope != request.scope
                or not item.created_unix <= now < item.expires()
                or (item.tier == "working" and item.session_id != request.session_id)
                for item in items
            ):
                raise ValueError("memory_index_binding_mismatch")
            self.event(
                request.scope,
                request.run_id,
                "memory_retrieved",
                now,
                {"ids": [item.memory_id for item in items]},
            )
            return items

    def claim(self, registry: Registry, request: Request, pin: str, now: float) -> int | None:
        authorize(registry, request.scope, "run", now)
        key = scopeKey(request.scope)
        with self.transaction():
            row = self.db.execute(
                "SELECT input,generation,lease,state FROM runs WHERE scope=? AND id=?",
                (key, request.run_id),
            ).fetchone()
            if row:
                if row[0] != pin:
                    raise ValueError("run_input_identity_conflict")
                if row[3] == "completed":
                    return None
                if now < row[2]:
                    raise ValueError("run_lease_busy")
                generation = row[1] + 1
                self.db.execute(
                    "UPDATE runs SET generation=?,lease=? WHERE scope=? AND id=?",
                    (generation, now + 30, key, request.run_id),
                )
                kind = "run_recovered"
            else:
                self.admission()
                generation = 1
                self.db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?)",
                    (key, request.run_id, pin, generation, now + 30, "running"),
                )
                kind = "run_started"
            self.event(
                request.scope, request.run_id, kind, now, {"input": pin, "generation": generation}
            )
            return generation

    def fence(self, request: Request, generation: int, now: float):
        row = self.db.execute(
            "SELECT generation,lease,state FROM runs WHERE scope=? AND id=?",
            (scopeKey(request.scope), request.run_id),
        ).fetchone()
        if not row or row[0] != generation or now >= row[1] or row[2] != "running":
            raise ValueError("run_fence_lost")

    def checkpoint(
        self,
        registry: Registry,
        request: Request,
        generation: int,
        agent: str,
        value: dict,
        now: float,
    ):
        authorize(registry, request.scope, "run", now)
        with self.transaction():
            self.fence(request, generation, now)
            body, pin = self.body(value)
            self.admission()
            self.db.execute(
                "INSERT INTO checkpoints VALUES(?,?,?,?,?)",
                (scopeKey(request.scope), request.run_id, agent, body, pin),
            )
            self.event(
                request.scope,
                request.run_id,
                "agent_checkpoint",
                now,
                {"agent": agent, "sha256": pin},
            )

    def checkpoints(self, registry: Registry, request: Request, now: float) -> dict:
        authorize(registry, request.scope, "run", now)
        rows = self.db.execute(
            "SELECT agent,body,sha FROM checkpoints WHERE scope=? AND run=?",
            (scopeKey(request.scope), request.run_id),
        ).fetchall()
        return {agent: self.checked(body, pin) for agent, body, pin in rows}

    def complete(
        self,
        registry: Registry,
        request: Request,
        generation: int,
        decision: RuntimeDecision,
        reflection: MemoryItem | None,
        now: float,
    ):
        authorize(registry, request.scope, "run", now)
        authorize(registry, request.scope, "memory_write", now)
        if decision.scope != request.scope or (reflection and reflection.scope != request.scope):
            raise PermissionError("completion_scope_denied")
        if (
            decision.run_id != request.run_id
            or decision.session_id != request.session_id
            or (
                reflection
                and (reflection.session_id != request.session_id or not now < reflection.expires())
            )
        ):
            raise ValueError("completion_identity_or_expiry_mismatch")
        with self.transaction():
            self.fence(request, generation, now)
            body, pin = self.body(decision.model_dump(mode="json"))
            self.admission()
            self.db.execute(
                "INSERT INTO decisions VALUES(?,?,?,?)",
                (scopeKey(request.scope), request.run_id, body, pin),
            )
            if reflection:
                self._insertMemory(reflection)
            self.db.execute(
                "UPDATE runs SET state='completed' WHERE scope=? AND id=?",
                (scopeKey(request.scope), request.run_id),
            )
            self.event(
                request.scope,
                request.run_id,
                "run_completed",
                now,
                {
                    "decision_sha256": pin,
                    "reflection": reflection.memory_id if reflection else None,
                },
            )

    def export(self, registry: Registry, request: Request, now: float) -> RuntimeDecision:
        authorize(registry, request.scope, "export", now)
        row = self.db.execute(
            "SELECT body,sha FROM decisions WHERE scope=? AND run=?",
            (scopeKey(request.scope), request.run_id),
        ).fetchone()
        if not row:
            raise ValueError("decision_not_found")
        value = self.checked(*row)
        result = RuntimeDecision.model_validate_json(json.dumps(value))
        if result.scope != request.scope or result.run_id != request.run_id:
            raise ValueError("decision_scope_binding_mismatch")
        return result

    def audit(self, registry: Registry, request: Request, now: float, after: int = 0) -> list[dict]:
        authorize(registry, request.scope, "export", now)
        if type(after) is not int or after < 0:
            raise ValueError("invalid_audit_cursor")
        rows = self.db.execute(
            "SELECT sequence,body,sha FROM audit WHERE scope=? AND sequence>? "
            "ORDER BY sequence LIMIT 50",
            (scopeKey(request.scope), after),
        ).fetchall()
        previous = self.db.execute(
            "SELECT sha FROM audit WHERE scope=? AND sequence<=? ORDER BY sequence DESC LIMIT 1",
            (scopeKey(request.scope), after),
        ).fetchone()
        prior = previous[0] if previous else "0" * 64
        result = []
        for sequence, body, pin in rows:
            value = self.checked(body, pin)
            if value["previous"] != prior or value["scope"] != request.scope.model_dump():
                raise ValueError("audit_chain_mismatch")
            result.append({"sequence": sequence, "sha256": pin, "record": value})
            prior = pin
        return result

"""SQLite access with ordered, versioned migrations.

Schema version lives in ``PRAGMA user_version``. Version 1 is the original v0.1
schema (created implicitly by earlier releases); later versions only add or
rebuild tables so existing workspaces upgrade in place.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 2


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid4().hex


V1 = """
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, mime TEXT NOT NULL,
  digest TEXT UNIQUE NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0, text TEXT NOT NULL DEFAULT '',
  method TEXT NOT NULL DEFAULT '', fields TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
  state TEXT NOT NULL, created TEXT NOT NULL, error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
  version INTEGER NOT NULL, decision TEXT NOT NULL, actor TEXT NOT NULL,
  reason TEXT NOT NULL, fields TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS integrations (
  id TEXT PRIMARY KEY, review_id TEXT UNIQUE NOT NULL REFERENCES reviews(id),
  payload TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, document_id TEXT REFERENCES documents(id),
  event TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);
"""

# v2: templates, pages with OCR geometry, job progress, outbox, learning, settings.
# audit and the local ledger are rebuilt without foreign keys so their history
# survives deletion of the document they describe.
V2 = """
ALTER TABLE documents ADD COLUMN template_id TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN template_source TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN size INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN pages INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN updated TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN classification TEXT NOT NULL DEFAULT '{}';
ALTER TABLE documents ADD COLUMN tables TEXT NOT NULL DEFAULT '{}';
UPDATE documents SET updated = created WHERE updated = '';
UPDATE documents SET template_id = 'generic-record', template_source = 'migrated'
  WHERE version > 0 AND template_id = '';

ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'process';
ALTER TABLE jobs ADD COLUMN progress INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN total INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN started TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN finished TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN timings TEXT NOT NULL DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN previous_status TEXT NOT NULL DEFAULT '';
UPDATE jobs SET finished = created WHERE state IN ('done', 'failed') AND finished = '';

ALTER TABLE reviews ADD COLUMN template_id TEXT NOT NULL DEFAULT '';
ALTER TABLE reviews ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}';
ALTER TABLE reviews ADD COLUMN issues TEXT NOT NULL DEFAULT '{}';
ALTER TABLE reviews ADD COLUMN tables TEXT NOT NULL DEFAULT '{}';
UPDATE reviews SET template_id = 'generic-record' WHERE template_id = '';

CREATE TABLE audit_v2 (
  id INTEGER PRIMARY KEY, document_id TEXT, event TEXT NOT NULL, actor TEXT NOT NULL,
  detail TEXT NOT NULL, created TEXT NOT NULL);
INSERT INTO audit_v2 SELECT id, document_id, event, actor, detail, created FROM audit;
DROP TABLE audit;
ALTER TABLE audit_v2 RENAME TO audit;

CREATE TABLE ledger (
  id TEXT PRIMARY KEY, review_id TEXT UNIQUE NOT NULL, document_id TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL, created TEXT NOT NULL);
INSERT INTO ledger(id, review_id, document_id, payload, created)
  SELECT i.id, i.review_id, COALESCE(r.document_id, ''), i.payload, i.created
  FROM integrations i LEFT JOIN reviews r ON r.id = i.review_id;
DROP TABLE integrations;

CREATE TABLE pages (
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, page INTEGER NOT NULL, method TEXT NOT NULL,
  width INTEGER NOT NULL DEFAULT 0, height INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL, rows TEXT NOT NULL DEFAULT '[]', mean_score REAL,
  steps TEXT NOT NULL DEFAULT '[]', image TEXT NOT NULL DEFAULT '', ms INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (document_id, version, page));

CREATE TABLE templates (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, definition TEXT NOT NULL,
  builtin INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated TEXT NOT NULL);

CREATE TABLE outbox (
  id TEXT PRIMARY KEY, review_id TEXT NOT NULL, document_id TEXT NOT NULL,
  adapter TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload TEXT NOT NULL,
  state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt TEXT NOT NULL,
  last_error TEXT NOT NULL DEFAULT '', response TEXT NOT NULL DEFAULT '{}',
  created TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE (adapter, idempotency_key));

CREATE TABLE corrections (
  id TEXT PRIMARY KEY, review_id TEXT NOT NULL, document_id TEXT NOT NULL,
  template_id TEXT NOT NULL, field TEXT NOT NULL, extracted TEXT NOT NULL,
  confirmed TEXT NOT NULL, source TEXT NOT NULL, created TEXT NOT NULL);

CREATE TABLE rules (
  id TEXT PRIMARY KEY, template_id TEXT NOT NULL, field TEXT NOT NULL, kind TEXT NOT NULL,
  pattern TEXT NOT NULL, replacement TEXT NOT NULL DEFAULT '', support INTEGER NOT NULL,
  applied INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  created TEXT NOT NULL, updated TEXT NOT NULL,
  UNIQUE (template_id, field, kind, pattern, replacement));

CREATE TABLE rule_support (
  rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE, document_id TEXT NOT NULL,
  created TEXT NOT NULL, PRIMARY KEY (rule_id, document_id));

CREATE VIRTUAL TABLE search_index USING fts5(document_id UNINDEXED, name, body,
  tokenize = 'unicode61 remove_diacritics 2');
INSERT INTO search_index(document_id, name, body) SELECT id, name, text FROM documents;

CREATE INDEX idx_documents_status ON documents(status, archived);
CREATE INDEX idx_documents_created ON documents(created);
CREATE INDEX idx_documents_template ON documents(template_id);
CREATE INDEX idx_jobs_state ON jobs(state, created);
CREATE INDEX idx_jobs_document ON jobs(document_id);
CREATE INDEX idx_reviews_document ON reviews(document_id, version);
CREATE INDEX idx_audit_document ON audit(document_id, created);
CREATE INDEX idx_audit_event ON audit(event, created);
CREATE INDEX idx_outbox_state ON outbox(state, next_attempt);
CREATE INDEX idx_corrections_template ON corrections(template_id, field);
"""

MIGRATIONS = {1: V1, 2: V2}


class Database:
    """Opens short-lived connections; each ``connect()`` block is one transaction."""

    def __init__(self, path: Path):
        self.path = path
        # Serialises maintenance (restore) against workers and requests.
        self.maintenance = threading.RLock()
        self.migrate()

    def raw(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    @contextmanager
    def connect(self, immediate: bool = False):
        c = self.raw()
        try:
            c.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield c
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def version(self) -> int:
        c = self.raw()
        try:
            return c.execute("PRAGMA user_version").fetchone()[0]
        finally:
            c.close()

    def migrate(self) -> list[int]:
        c = self.raw()
        applied = []
        try:
            c.execute("PRAGMA journal_mode=WAL")
            current = c.execute("PRAGMA user_version").fetchone()[0]
            has_documents = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone()
            if current == 0 and has_documents:
                current = 1  # Workspace created by v0.1, which did not set user_version.
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Workspace schema {current} is newer than this LETRANIX build ({SCHEMA_VERSION})"
                )
            # Rebuilding referenced tables requires foreign keys off outside a transaction.
            c.execute("PRAGMA foreign_keys=OFF")
            for target in range(current + 1, SCHEMA_VERSION + 1):
                c.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _split(MIGRATIONS[target]):
                        c.execute(statement)
                    c.execute(f"PRAGMA user_version={target}")
                    c.execute("COMMIT")
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
                applied.append(target)
            c.execute("PRAGMA user_version=" + str(SCHEMA_VERSION))
            problems = c.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise RuntimeError(f"Foreign key check failed after migration: {len(problems)}")
        finally:
            c.close()
        return applied


def _split(script: str) -> list[str]:
    return [s.strip() for s in script.split(";\n") if s.strip()]


def audit(c: sqlite3.Connection, document_id, event: str, actor: str, detail: dict) -> None:
    """Record an operation. ``detail`` must hold identifiers and codes, never document text."""
    c.execute(
        "INSERT INTO audit(document_id,event,actor,detail,created) VALUES(?,?,?,?,?)",
        (document_id, event, actor, json.dumps(detail, ensure_ascii=False), now()),
    )

"""SQLite transactions for documents, processing, review and explicit integration."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = self.root / "documents"
        self.files.mkdir(exist_ok=True)
        self.db = self.root / "letranix.db"
        with self.connect() as c:
            c.executescript("""
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
            """)
            # Interrupted processing is visible and recoverable after restart.
            c.execute(
                "UPDATE jobs SET state='failed', error='Processing interrupted; retry manually' WHERE state='running'"
            )
            c.execute("UPDATE documents SET status='error' WHERE status='processing'")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def audit(c, document_id, event, actor, detail):
        c.execute(
            "INSERT INTO audit(document_id,event,actor,detail,created) VALUES(?,?,?,?,?)",
            (document_id, event, actor, json.dumps(detail, ensure_ascii=False), now()),
        )

    def get(self, document_id):
        with self.connect() as c:
            row = c.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        result = dict(row)
        result["fields"] = json.loads(result["fields"])
        return result

    def detail(self, document_id):
        d = self.get(document_id)
        with self.connect() as c:
            queries = {
                "jobs": "SELECT * FROM jobs WHERE document_id=? ORDER BY created,id",
                "reviews": "SELECT * FROM reviews WHERE document_id=? ORDER BY created,id",
                "audit": "SELECT * FROM audit WHERE document_id=? ORDER BY created,id",
            }
            for table, query in queries.items():
                d[table] = [dict(r) for r in c.execute(query, (document_id,))]
            d["integrations"] = [
                dict(r)
                for r in c.execute(
                    "SELECT i.* FROM integrations i JOIN reviews r ON r.id=i.review_id WHERE r.document_id=?",
                    (document_id,),
                )
            ]
        return d

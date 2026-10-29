"""Integration adapters, delivery contract and the outbox worker.

Approved reviews are never sent implicitly. An explicit request enqueues one
outbox entry per (adapter, review); the entry carries an idempotency key that
adapters forward so a retried delivery cannot create a second record.

Failures are classified:
- ``TransientError`` (destination down, timeout, 5xx) -> retried with
  exponential backoff until ``integration.max_attempts``;
- ``PermanentError`` (contract rejected, 4xx) -> ``failed`` immediately.
Failed entries can be retried manually from the interface.
"""

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .db import Database, audit, now, uid

CONTRACT = "letranix.record/v1"


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


def build_payload(doc, review, template) -> dict:
    return {
        "schema": CONTRACT,
        "document": {"id": doc["id"], "name": doc["name"], "sha256": doc["digest"]},
        "template": template["id"],
        "review": {
            "id": review["id"],
            "version": review["version"],
            "actor": review["actor"],
            "decided_at": review["created"],
        },
        "fields": json.loads(review["fields"]),
        "tables": json.loads(review["tables"] or "{}"),
        "provenance": json.loads(review["provenance"] or "{}"),
    }


def validate_payload(p: dict) -> None:
    """Contract check shared by producer and the demo destination."""
    if not isinstance(p, dict) or p.get("schema") != CONTRACT:
        raise PermanentError("Unsupported contract")
    for key in ("document", "review", "fields", "template"):
        if key not in p:
            raise PermanentError(f"Missing {key}")
    if not isinstance(p["fields"], dict) or not all(
        isinstance(k, str) and isinstance(v, str) and len(v) <= 1000 for k, v in p["fields"].items()
    ):
        raise PermanentError("Fields must map names to text")
    if not isinstance(p["document"].get("id"), str) or not isinstance(p["review"].get("id"), str):
        raise PermanentError("Document and review ids required")


class Adapter(Protocol):
    name: str

    def deliver(self, key: str, payload: dict) -> dict:
        """Deliver once. Must be idempotent for the same ``key``."""
        ...

    def records(self, limit: int) -> list[dict]:
        """Read back what the destination holds (for verification in the UI)."""
        ...


class LocalLedgerAdapter:
    """Destination inside the workspace database."""

    name = "local-ledger"

    def __init__(self, db: Database):
        self.db = db

    def deliver(self, key: str, payload: dict) -> dict:
        validate_payload(payload)
        with self.db.connect(immediate=True) as c:
            row = c.execute("SELECT id FROM ledger WHERE review_id=?", (key,)).fetchone()
            if row:
                return {"id": row["id"], "duplicate": True}
            record_id = uid()
            c.execute(
                "INSERT INTO ledger(id,review_id,document_id,payload,created) VALUES(?,?,?,?,?)",
                (record_id, key, payload["document"]["id"], json.dumps(payload["fields"]), now()),
            )
        return {"id": record_id, "duplicate": False}

    def records(self, limit: int) -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM ledger ORDER BY created DESC LIMIT ?", (limit,))
            return [
                {"id": r["id"], "review_id": r["review_id"], "document_id": r["document_id"],
                 "fields": json.loads(r["payload"]), "received": r["created"]}
                for r in rows
            ]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HttpDemoAdapter:
    """POSTs to the loopback demonstration API (``python -m letranix mock-destination``).

    The endpoint is validated as loopback-only by settings; redirects are not followed.
    """

    name = "http-demo"

    def __init__(self, endpoint: str, timeout: float = 5.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))

    def deliver(self, key: str, payload: dict) -> dict:
        validate_payload(payload)
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Idempotency-Key": key},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:  # nosec B310 - loopback-validated URL
                body = json.loads(response.read(65536) or b"{}")
                return {"id": str(body.get("id", "")), "duplicate": bool(body.get("duplicate")),
                        "status": response.status}
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", "replace")
            if exc.code >= 500 or exc.code == 429:
                raise TransientError(f"Destination returned {exc.code}") from None
            raise PermanentError(f"Destination rejected the record ({exc.code}): {detail[:200]}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise TransientError(f"Destination unavailable: {type(exc).__name__}") from None
        except json.JSONDecodeError:
            raise PermanentError("Destination returned invalid JSON") from None

    def records(self, limit: int) -> list[dict]:
        url = self.endpoint.rstrip("/") + f"?limit={int(limit)}"
        try:
            with self.opener.open(url, timeout=self.timeout) as response:  # nosec B310
                return json.loads(response.read(2_000_000))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise TransientError(f"Destination unavailable: {type(exc).__name__}") from None


def make_adapter(db: Database, settings: dict) -> Adapter:
    if settings["integration.adapter"] == "http-demo":
        return HttpDemoAdapter(settings["integration.endpoint"])
    return LocalLedgerAdapter(db)


def backoff(attempts: int) -> str:
    delay = min(300, 2 ** attempts)
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()


class OutboxWorker:
    def __init__(self, db: Database, settings, poll: float = 1.0):
        self.db = db
        self.settings = settings
        self.poll = poll
        self.wakeup = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="letranix-outbox", daemon=True)

    def start(self):
        with self.db.connect(immediate=True) as c:
            # A crash mid-delivery is safe to retry: the idempotency key prevents duplicates.
            c.execute("UPDATE outbox SET state='pending', updated=? WHERE state='delivering'", (now(),))
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wakeup.set()
        if self.thread.is_alive():
            self.thread.join(timeout=10)

    def _loop(self):
        while not self.stopping.is_set():
            try:
                while self.run_once():
                    pass
            except Exception:  # Keep the worker alive; log the type without payload data.
                logging.getLogger("letranix.outbox").exception("Outbox worker iteration failed")
            self.wakeup.wait(self.poll)
            self.wakeup.clear()

    def run_once(self) -> bool:
        with self.db.maintenance:
            with self.db.connect(immediate=True) as c:
                row = c.execute(
                    "SELECT * FROM outbox WHERE state='pending' AND next_attempt<=? "
                    "ORDER BY next_attempt LIMIT 1",
                    (now(),),
                ).fetchone()
                if not row:
                    return False
                c.execute(
                    "UPDATE outbox SET state='delivering', attempts=attempts+1, updated=? WHERE id=?",
                    (now(), row["id"]),
                )
            entry = dict(row)
            values = self.settings.all()
            try:
                if entry["adapter"] == "http-demo":
                    adapter = HttpDemoAdapter(values["integration.endpoint"])
                else:
                    adapter = LocalLedgerAdapter(self.db)
                result = adapter.deliver(entry["idempotency_key"], json.loads(entry["payload"]))
                state, error, event = "delivered", "", "integration.delivered"
            except TransientError as exc:
                result = {}
                exhausted = entry["attempts"] + 1 >= values["integration.max_attempts"]
                state = "failed" if exhausted else "pending"
                error, event = str(exc), "integration.failed" if exhausted else "integration.retry-scheduled"
            except PermanentError as exc:
                result, state, error, event = {}, "failed", str(exc), "integration.failed"
            with self.db.connect(immediate=True) as c:
                c.execute(
                    "UPDATE outbox SET state=?, last_error=?, response=?, next_attempt=?, updated=? WHERE id=?",
                    (state, error, json.dumps(result), backoff(entry["attempts"] + 1), now(), entry["id"]),
                )
                audit(c, entry["document_id"], event, "system", {
                    "outbox": entry["id"], "adapter": entry["adapter"],
                    "attempt": entry["attempts"] + 1, "record": result.get("id", ""),
                    "duplicate": result.get("duplicate", False), "error": error[:200],
                })
            return True

"""A fictitious records API used to demonstrate a real HTTP integration.

It is a separate process with its own SQLite file, so LETRANIX talks to it over
HTTP exactly as it would to an external system. It enforces the record
contract, requires an ``Idempotency-Key`` and can be told to fail the next
requests to exercise retry handling. Loopback only; no real system is involved.
"""

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .integrations import PermanentError, validate_payload


def create_destination(data_dir: Path) -> FastAPI:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "destination.db"
    lock = threading.Lock()
    faults = {"remaining": 0, "status": 503}
    with sqlite3.connect(path) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, "
            "document_id TEXT NOT NULL, template TEXT NOT NULL, body TEXT NOT NULL, received TEXT NOT NULL)"
        )
    app = FastAPI(title="LETRANIX demo destination", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def loopback(request: Request, call_next):
        if not re.fullmatch(r"(localhost|127\.0\.0\.1)(:\d{1,5})?", request.headers.get("host", "")):
            return JSONResponse({"detail": "Loopback host required"}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok", "system": "fictitious-records-api"}

    @app.post("/records")
    async def create(request: Request, idempotency_key: str = Header(..., max_length=100)):
        with lock:
            if faults["remaining"] > 0:
                faults["remaining"] -= 1
                raise HTTPException(faults["status"], "Injected fault")
        try:
            payload = json.loads(await request.body())
            validate_payload(payload)
        except (json.JSONDecodeError, PermanentError, AttributeError, TypeError) as exc:
            raise HTTPException(422, f"Contract violation: {exc}") from None
        with lock, sqlite3.connect(path) as c:
            row = c.execute("SELECT id FROM records WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if row:
                return JSONResponse({"id": row[0], "duplicate": True}, status_code=200)
            record_id = uuid4().hex
            c.execute(
                "INSERT INTO records VALUES(?,?,?,?,?,?)",
                (record_id, idempotency_key, payload["document"]["id"], payload["template"],
                 json.dumps(payload), datetime.now(timezone.utc).isoformat()),
            )
        return JSONResponse({"id": record_id, "duplicate": False}, status_code=201)

    @app.get("/records")
    def records(limit: int = 100):
        with sqlite3.connect(path) as c:
            rows = c.execute(
                "SELECT id, idempotency_key, body, received FROM records ORDER BY received DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        out = []
        for record_id, key, body, received in rows:
            payload = json.loads(body)
            out.append({"id": record_id, "review_id": key, "document_id": payload["document"]["id"],
                        "template": payload["template"], "fields": payload["fields"], "received": received})
        return out

    @app.post("/admin/faults")
    def inject(count: int = 1, status: int = 503):
        if not (0 <= count <= 20) or status not in {400, 422, 429, 500, 502, 503}:
            raise HTTPException(422, "count 0-20, status one of 400/422/429/500/502/503")
        with lock:
            faults.update(remaining=count, status=status)
        return faults

    return app

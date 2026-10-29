"""Loopback API with browser session, bounded ingestion and explicit review decisions."""

import hashlib
import json
import re
import secrets
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .processing import MAX_BYTES, extract, media_type
from .limits import RequestBodyLimit
from .integrations import LocalDemoAdapter
from .store import Store, now, uid

FIELD_NAMES = {"reference", "organization", "category", "date", "description"}
CATEGORIES = {"service-order", "operational-report", "administrative-request", "handwritten-form"}


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    decision: str = Field(pattern="^(approved|rejected)$")
    actor: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=5, max_length=1000)
    fields: dict[str, str]


class Integration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(pattern="^[a-f0-9]{32}$")
    authorize: bool


def create_app(data_dir: Path, frontend: Path | None = None):
    app = FastAPI(title="LETRANIX", docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(data_dir)
    app.state.store = store
    token = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if not re.fullmatch(r"(localhost|127\.0\.0\.1)(:\d{1,5})?", host):
            return JSONResponse({"detail": "Loopback host required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"http://{host}":
            return JSONResponse({"detail": "Same-origin browser required"}, status_code=403)
        path = request.url.path
        if path == "/api/session":
            if request.headers.get("x-letranix-client") != "browser":
                return JSONResponse({"detail": "Client header required"}, status_code=403)
        elif path.startswith("/api/") and path != "/api/health":
            supplied = request.headers.get("authorization", "")
            if not secrets.compare_digest(supplied, f"Bearer {token}"):
                return JSONResponse({"detail": "Session required"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob:; connect-src 'self'; frame-src blob:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Document not found"}, status_code=404)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "product": "LETRANIX", "integration": "local-demo-only"}

    @app.get("/api/session")
    def session():
        return {"token": token}

    @app.get("/api/documents")
    def documents(q: str = "", status: str = "", category: str = ""):
        if len(q) > 200:
            raise HTTPException(422, "Search too long")
        with store.connect() as c:
            rows = c.execute(
                """SELECT id,name,mime,created,status,version,method,fields FROM documents
                WHERE (name LIKE ? OR text LIKE ?) AND (?='' OR status=?)
                ORDER BY created DESC LIMIT 500""",
                ("%" + q + "%", "%" + q + "%", status, status),
            )
            items = [dict(r) for r in rows]
        return [
            r
            for r in items
            if not category or json.loads(r["fields"]).get("category", {}).get("value") == category
        ]

    @app.post("/api/documents", status_code=201)
    def upload(file: UploadFile = File(...)):
        data = file.file.read(MAX_BYTES + 1)
        try:
            mime = media_type(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        digest = hashlib.sha256(data).hexdigest()
        doc_id = uid()
        # Never use the submitted filename as a storage path.
        name = (file.filename or "document").replace("\\", "/").split("/")[-1]
        name = "".join(ch for ch in name if ch.isprintable())[:120] or "document"
        with store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT id FROM documents WHERE digest=?", (digest,)).fetchone()
            if old:
                return {"id": old["id"], "duplicate": True}
            path = store.files / doc_id
            try:
                path.write_bytes(data)
                c.execute(
                    "INSERT INTO documents(id,name,mime,digest,created,status) VALUES(?,?,?,?,?,?)",
                    (doc_id, name, mime, digest, now(), "imported"),
                )
                store.audit(c, doc_id, "document.imported", "local-user", {"sha256": digest})
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return {"id": doc_id, "duplicate": False}

    @app.get("/api/documents/{doc_id}")
    def detail(doc_id: str):
        return store.detail(doc_id)

    @app.get("/api/documents/{doc_id}/file")
    def file(doc_id: str):
        d = store.get(doc_id)
        return FileResponse(
            store.files / d["id"],
            media_type=d["mime"],
            filename=d["name"],
            content_disposition_type="attachment",
        )

    @app.post("/api/documents/{doc_id}/process")
    def process(doc_id: str):
        d = store.get(doc_id)
        job_id = uid()
        with store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()
            if current["status"] == "processing":
                raise HTTPException(409, "Processing already running")
            c.execute("UPDATE documents SET status='processing' WHERE id=?", (doc_id,))
            c.execute(
                "INSERT INTO jobs(id,document_id,state,created) VALUES(?,?,?,?)",
                (job_id, doc_id, "running", now()),
            )
        try:
            result = extract((store.files / d["id"]).read_bytes(), d["mime"])
        except Exception:
            # Do not expose parser traces, local paths or document contents in errors.
            message = "Processing failed. Check supported format, image quality and local OCR installation."
            with store.connect() as c:
                c.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", (message, job_id))
                c.execute("UPDATE documents SET status='error' WHERE id=?", (doc_id,))
                store.audit(c, doc_id, "processing.failed", "system", {"job": job_id})
            raise HTTPException(422, message) from None
        with store.connect() as c:
            c.execute(
                "UPDATE documents SET status='needs-review',version=version+1,text=?,method=?,fields=? WHERE id=?",
                (result.text, result.method, json.dumps(result.fields), doc_id),
            )
            c.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
            store.audit(
                c,
                doc_id,
                "processing.completed",
                "system",
                {"job": job_id, "method": result.method},
            )
        return store.detail(doc_id)

    @app.post("/api/documents/{doc_id}/review")
    def review(doc_id: str, body: Review):
        if not body.actor.strip() or len(body.reason.strip()) < 5:
            raise HTTPException(422, "Reviewer and meaningful reason required")
        if set(body.fields) != FIELD_NAMES or any(len(v) > 1000 for v in body.fields.values()):
            raise HTTPException(
                422, "Exactly the five supported fields are required; max 1000 characters each"
            )
        if body.decision == "approved":
            if any(not v.strip() for v in body.fields.values()):
                raise HTTPException(422, "All fields must be reviewed and filled before approval")
            if body.fields["category"] not in CATEGORIES:
                raise HTTPException(422, "Choose a supported document category")
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.fields["date"]):
                    raise ValueError("Date format")
                date.fromisoformat(body.fields["date"])
            except ValueError:
                raise HTTPException(422, "Use an ISO date YYYY-MM-DD") from None
        review_id = uid()
        with store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            d = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not d:
                raise KeyError(doc_id)
            if d["version"] != body.version or d["status"] != "needs-review":
                raise HTTPException(
                    409, "Document changed or already reviewed; reload before deciding"
                )
            c.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?)",
                (
                    review_id,
                    doc_id,
                    body.version,
                    body.decision,
                    body.actor.strip(),
                    body.reason.strip(),
                    json.dumps(body.fields),
                    now(),
                ),
            )
            c.execute("UPDATE documents SET status=? WHERE id=?", (body.decision, doc_id))
            store.audit(
                c, doc_id, "review." + body.decision, body.actor.strip(), {"review": review_id}
            )
        return {"review_id": review_id, "integration_executed": False}

    @app.post("/api/documents/{doc_id}/integrate")
    def integrate(doc_id: str, body: Integration):
        if not body.authorize:
            raise HTTPException(422, "Explicit authorization required for local demo integration")
        with store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            d = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not d:
                raise KeyError(doc_id)
            r = c.execute(
                "SELECT * FROM reviews WHERE id=? AND document_id=?", (body.review_id, doc_id)
            ).fetchone()
            if (
                not r
                or r["decision"] != "approved"
                or r["version"] != d["version"]
                or d["status"] != "approved"
            ):
                raise HTTPException(409, "Current approved review required")
            result = LocalDemoAdapter().apply(c, r["id"], r["fields"])
            if not result["duplicate"]:
                store.audit(
                    c, doc_id, "integration.local-demo", r["actor"], {"integration": result["id"]}
                )
        return result

    app.add_middleware(RequestBodyLimit)
    if frontend and frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app

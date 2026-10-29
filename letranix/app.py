"""Loopback HTTP API. Handlers validate input shape and delegate to ``Letranix``."""

import re
import secrets
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, backup, ocr
from .evaluation import latest_report, run_evaluation
from .integrations import TransientError
from .limits import RequestBodyLimit
from .service import STATUSES, Conflict, Invalid, Letranix
from .settings import Settings

ID = r"^[a-f0-9]{32}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewBody(Strict):
    version: int = Field(ge=1)
    decision: str = Field(pattern="^(approved|rejected)$")
    actor: str = Field(min_length=2, max_length=80)
    reason: str = Field(max_length=1000)
    fields: dict[str, str]
    issues: dict[str, str] = {}
    table: list[dict[str, str]] = []


class ProcessBody(Strict):
    template_id: str = Field("", max_length=40)


class BatchBody(Strict):
    ids: list[str] = Field(min_length=1, max_length=200)
    template_id: str = Field("", max_length=40)


class TemplateBody(Strict):
    template_id: str = Field(max_length=40)


class Integration(Strict):
    review_id: str = Field(pattern=ID)
    authorize: bool


class ReopenBody(Strict):
    actor: str = Field(min_length=2, max_length=80)
    reason: str = Field(max_length=1000)


class ArchiveBody(Strict):
    archived: bool


class DeleteBody(Strict):
    confirm: str = Field(max_length=200)


class RuleBody(Strict):
    enabled: bool


def create_app(data_dir: Path, frontend: Path | None = None, start_workers: bool = True):
    app = FastAPI(title="LETRANIX", docs_url=None, redoc_url=None, openapi_url=None)
    svc = Letranix(data_dir, start_workers=start_workers)
    app.state.service = svc
    token = secrets.token_urlsafe(32)
    actor_default = "local-user"

    @app.on_event("shutdown")
    def shutdown():
        svc.close()

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
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; connect-src 'self'; frame-src blob:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Invalid)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc), "fields": exc.fields}, status_code=422)

    @app.exception_handler(ocr.DocumentError)
    async def document_error(request, exc):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=422)

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    def check_id(value: str):
        if not re.fullmatch(ID, value):
            raise KeyError(value)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "product": "LETRANIX", "version": __version__}

    @app.get("/api/session")
    def session():
        return {"token": token}

    @app.get("/api/overview")
    def overview():
        return svc.overview()

    @app.get("/api/documents")
    def documents(q: str = "", status: str = "", template: str = "", date_from: str = "", date_to: str = "",
                  archived: bool = False, issues: bool = False, sort: str = "created", limit: int = 50,
                  offset: int = 0):
        if len(q) > 200 or (status and status not in STATUSES):
            raise HTTPException(422, "Invalid filter")
        for value in (date_from, date_to):
            if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise HTTPException(422, "Dates must be YYYY-MM-DD")
        return svc.search(q, status, template, date_from, date_to, archived, issues, sort, limit, offset)

    @app.post("/api/documents", status_code=201)
    def upload(file: UploadFile = File(...)):
        limit = svc.settings.get("processing.max_file_mb") * 1024 * 1024
        data = file.file.read(limit + 1)
        return svc.import_bytes(file.filename, data, actor_default)

    @app.post("/api/documents/inbox")
    def inbox():
        return svc.import_inbox(actor_default)

    @app.post("/api/documents/process")
    def process_batch(body: BatchBody):
        for i in body.ids:
            check_id(i)
        return {"jobs": svc.queue(body.ids, actor_default, body.template_id)}

    @app.get("/api/documents/{doc_id}")
    def detail(doc_id: str):
        check_id(doc_id)
        return svc.detail(doc_id)

    @app.get("/api/documents/{doc_id}/file")
    def original(doc_id: str):
        check_id(doc_id)
        d = svc.get(doc_id)
        return FileResponse(svc.files / d["id"], media_type=d["mime"], filename=d["name"],
                            content_disposition_type="attachment")

    @app.get("/api/documents/{doc_id}/pages/{page}/image")
    def page_image(doc_id: str, page: int):
        check_id(doc_id)
        return FileResponse(svc.page_image(doc_id, page), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=60"})

    @app.post("/api/documents/{doc_id}/process")
    def process(doc_id: str, body: ProcessBody | None = None):
        check_id(doc_id)
        return {"jobs": svc.queue([doc_id], actor_default, body.template_id if body else "")}

    @app.post("/api/documents/{doc_id}/template")
    def apply_template(doc_id: str, body: TemplateBody):
        check_id(doc_id)
        return svc.apply_template(doc_id, body.template_id, actor_default)

    @app.post("/api/documents/{doc_id}/review")
    def review(doc_id: str, body: ReviewBody):
        check_id(doc_id)
        return svc.review(doc_id, body.model_dump())

    @app.post("/api/documents/{doc_id}/reopen")
    def reopen(doc_id: str, body: ReopenBody):
        check_id(doc_id)
        return svc.reopen(doc_id, body.actor, body.reason)

    @app.post("/api/documents/{doc_id}/integrate")
    def integrate(doc_id: str, body: Integration):
        check_id(doc_id)
        if not body.authorize:
            raise HTTPException(422, "Explicit authorization required")
        return svc.integrate(doc_id, body.review_id, actor_default)

    @app.post("/api/documents/{doc_id}/archive")
    def archive(doc_id: str, body: ArchiveBody):
        check_id(doc_id)
        svc.archive(doc_id, body.archived, actor_default)
        return {"archived": body.archived}

    @app.post("/api/documents/{doc_id}/delete")
    def delete(doc_id: str, body: DeleteBody):
        check_id(doc_id)
        svc.delete(doc_id, body.confirm, actor_default)
        return {"deleted": True}

    @app.get("/api/documents/{doc_id}/export")
    def export_document(doc_id: str):
        check_id(doc_id)
        return Response(svc.export_document(doc_id, actor_default), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="letranix-{doc_id}.json"'})

    @app.get("/api/export")
    def export(format: str = "csv", template: str = ""):
        if format not in {"csv", "json"}:
            raise HTTPException(422, "format must be csv or json")
        body, media = svc.export_records(format, template, actor_default)
        return Response(body, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="letranix-approved.{format}"'})

    @app.get("/api/jobs")
    def jobs(active: bool = False):
        return svc.jobs(active)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        check_id(job_id)
        return svc.cancel(job_id, actor_default)

    @app.get("/api/templates")
    def templates():
        return svc.templates.all()

    @app.post("/api/templates")
    async def save_template(request: Request):
        try:
            definition = await request.json()
        except ValueError:
            raise HTTPException(422, "Invalid JSON") from None
        try:
            return svc.templates.save(definition, actor_default)
        except ValueError as exc:
            raise Invalid(str(exc)) from None

    @app.delete("/api/templates/{template_id}")
    def delete_template(template_id: str):
        svc.templates.delete(template_id, actor_default)
        return {"deleted": True}

    @app.get("/api/learning/rules")
    def rules():
        return svc.rules()

    @app.patch("/api/learning/rules/{rule_id}")
    def toggle_rule(rule_id: str, body: RuleBody):
        check_id(rule_id)
        svc.set_rule(rule_id, body.enabled, actor_default)
        return {"enabled": body.enabled}

    @app.delete("/api/learning/rules/{rule_id}")
    def delete_rule(rule_id: str):
        check_id(rule_id)
        svc.delete_rule(rule_id, actor_default)
        return {"deleted": True}

    @app.get("/api/learning/evaluation")
    def evaluation():
        return latest_report(svc.root)

    @app.post("/api/learning/evaluation")
    def evaluate():
        return run_evaluation(svc.root / "evaluation", save_to=svc.root)

    @app.get("/api/integrations/outbox")
    def outbox():
        return svc.outbox_list()

    @app.post("/api/integrations/outbox/{entry_id}/retry")
    def retry(entry_id: str):
        check_id(entry_id)
        return svc.retry_outbox(entry_id, actor_default)

    @app.get("/api/integrations/destination")
    def destination():
        try:
            return svc.destination_records()
        except TransientError as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/api/audit")
    def audit_log(event: str = "", document: str = "", actor: str = "", limit: int = 100, offset: int = 0):
        return svc.audit_log(event[:60], document[:32], actor[:80], limit, offset)

    @app.get("/api/settings")
    def settings():
        return {
            "values": svc.settings.all(),
            "schema": Settings.schema(),
            "engines": {name: ocr.engine_available(name) for name in ("rapidocr", "none")},
            # Shown in the UI and screenshots: collapse the home folder so no user name appears.
            "workspace": str(svc.root).replace(str(Path.home()), "~"),
            "schema_version": svc.db.version(),
            "version": __version__,
        }

    @app.patch("/api/settings")
    async def update_settings(request: Request):
        try:
            changes = await request.json()
        except ValueError:
            raise HTTPException(422, "Invalid JSON") from None
        if not isinstance(changes, dict) or not changes or len(changes) > 40:
            raise HTTPException(422, "Send an object of setting changes")
        try:
            keys = svc.settings.update(changes)
        except ValueError as exc:
            raise Invalid(str(exc)) from None
        if changes.get("ocr.engine") == "rapidocr" and not ocr.engine_available("rapidocr"):
            raise Invalid("RapidOCR is not installed in this environment")
        with svc.db.connect() as c:
            from .db import audit

            audit(c, None, "settings.updated", actor_default, {"keys": keys})
        return svc.settings.all()

    @app.get("/api/backups")
    def backups():
        return backup.listing(svc)

    @app.post("/api/backups", status_code=201)
    def create_backup():
        return backup.create(svc, actor_default)

    @app.get("/api/backups/{name}")
    def download_backup(name: str):
        path = backup.resolve(svc, name)
        return FileResponse(path, media_type="application/zip", filename=name)

    @app.post("/api/backups/{name}/restore")
    def restore_backup(name: str):
        try:
            return backup.restore(svc, name, actor_default)
        except ValueError as exc:
            raise Invalid(str(exc)) from None

    app.add_middleware(RequestBodyLimit)
    if frontend and frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app

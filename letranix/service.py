"""Application services. HTTP handlers stay thin; all business rules live here."""

import csv
import hashlib
import io
import json
import logging
import re
import threading
import time
from pathlib import Path

from . import ocr
from .db import Database, audit, now, uid
from .extraction import extract_fields, validate_value
from .integrations import OutboxWorker, PermanentError, build_payload, make_adapter, validate_payload
from .learning import Classifier, active_rules, learn_from_review
from .settings import Settings
from .templates import Templates

STATUSES = ("imported", "queued", "processing", "needs-review", "approved", "rejected", "error")
BUSY = {"queued", "processing"}
IMPORT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".txt"}


class Conflict(Exception):
    pass


class Invalid(ValueError):
    def __init__(self, message: str, fields: dict | None = None):
        super().__init__(message)
        self.fields = fields or {}


def safe_name(name: str | None) -> str:
    name = (name or "document").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    return name.strip(" .")[:120] or "document"


class Letranix:
    def __init__(self, root: Path, start_workers: bool = True):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = self.root / "documents"
        self.page_dir = self.root / "pages"
        self.backups = self.root / "backups"
        for d in (self.files, self.page_dir, self.backups):
            d.mkdir(exist_ok=True)
        self.db = Database(self.root / "letranix.db")
        self.settings = Settings(self.db)
        self.templates = Templates(self.db)
        self.classifier = Classifier()
        self.wakeup = threading.Event()
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._job_loop, name="letranix-jobs", daemon=True)
        self.outbox = OutboxWorker(self.db, self.settings)
        self.recover()
        if start_workers:
            self.worker.start()
            self.outbox.start()

    def close(self):
        self.stopping.set()
        self.wakeup.set()
        if self.worker.is_alive():
            self.worker.join(timeout=30)
        self.outbox.stop()

    # --- Recovery -----------------------------------------------------------

    def recover(self):
        """Requeue work interrupted by a crash or shutdown; give up after two interruptions."""
        with self.db.connect(immediate=True) as c:
            for job in c.execute("SELECT * FROM jobs WHERE state='running'").fetchall():
                if job["attempts"] < 2:
                    c.execute("UPDATE jobs SET state='queued', progress=0 WHERE id=?", (job["id"],))
                    c.execute("UPDATE documents SET status='queued' WHERE id=?", (job["document_id"],))
                    audit(c, job["document_id"], "processing.interrupted", "system",
                          {"job": job["id"], "action": "requeued"})
                else:
                    c.execute(
                        "UPDATE jobs SET state='failed', error=?, finished=? WHERE id=?",
                        ("Processing was interrupted repeatedly; retry manually", now(), job["id"]),
                    )
                    c.execute("UPDATE documents SET status='error' WHERE id=?", (job["document_id"],))
                    audit(c, job["document_id"], "processing.failed", "system",
                          {"job": job["id"], "code": "interrupted"})
            # v0.1 left documents in 'processing' without a job record.
            c.execute(
                "UPDATE documents SET status='error' WHERE status='processing' AND id NOT IN "
                "(SELECT document_id FROM jobs WHERE state IN ('queued','running'))"
            )

    # --- Documents ----------------------------------------------------------

    def import_bytes(self, name: str | None, data: bytes, actor: str = "local-user", via: str = "upload"):
        values = self.settings.all()
        mime = ocr.media_type(data, values["processing.max_file_mb"] * 1024 * 1024)
        pages = ocr.count_pages(data, mime)  # Rejects corrupt/encrypted files at import.
        if pages > values["processing.max_pages"]:
            raise ocr.DocumentError(
                "too-many-pages", f"Document has {pages} pages; limit is {values['processing.max_pages']}"
            )
        digest = hashlib.sha256(data).hexdigest()
        doc_id = uid()
        name = safe_name(name)
        with self.db.connect(immediate=True) as c:
            old = c.execute("SELECT id FROM documents WHERE digest=?", (digest,)).fetchone()
            if old:
                audit(c, old["id"], "document.duplicate-rejected", actor, {"via": via})
                return {"id": old["id"], "duplicate": True, "queued": False}
            path = self.files / doc_id  # Generated id, never the submitted name.
            try:
                path.write_bytes(data)
                c.execute(
                    "INSERT INTO documents(id,name,mime,digest,created,updated,status,size,pages) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (doc_id, name, mime, digest, now(), now(), "imported", len(data), pages),
                )
                c.execute("INSERT INTO search_index(document_id,name,body) VALUES(?,?,'')", (doc_id, name))
                audit(c, doc_id, "document.imported", actor,
                      {"sha256": digest, "mime": mime, "bytes": len(data), "pages": pages, "via": via})
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        queued = False
        if values["processing.auto_process"]:
            self.queue([doc_id], actor)
            queued = True
        return {"id": doc_id, "duplicate": False, "queued": queued}

    def import_inbox(self, actor: str) -> dict:
        folder = self.settings.get("processing.inbox_dir")
        if not folder:
            raise Invalid("Configure an inbox folder in Settings first")
        result = {"imported": 0, "duplicates": 0, "rejected": []}
        limit = self.settings.get("processing.max_file_mb") * 1024 * 1024
        for path in sorted(Path(folder).iterdir())[:500]:
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in IMPORT_SUFFIXES:
                continue
            if path.stat().st_size > limit:
                result["rejected"].append({"name": path.name, "reason": "Exceeds size limit"})
                continue
            try:
                r = self.import_bytes(path.name, path.read_bytes(), actor, via="inbox")
                result["duplicates" if r["duplicate"] else "imported"] += 1
            except ocr.DocumentError as exc:
                result["rejected"].append({"name": path.name, "reason": str(exc)})
        return result

    def get(self, doc_id: str) -> dict:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(doc_id)
        return dict(row)

    def detail(self, doc_id: str) -> dict:
        d = self.get(doc_id)
        for key in ("fields", "classification", "tables"):
            d[key] = json.loads(d[key])
        with self.db.connect() as c:
            d["jobs"] = [dict(r) for r in c.execute(
                "SELECT * FROM jobs WHERE document_id=? ORDER BY created DESC", (doc_id,))]
            d["reviews"] = [dict(r) for r in c.execute(
                "SELECT * FROM reviews WHERE document_id=? ORDER BY created DESC", (doc_id,))]
            d["audit"] = [dict(r) for r in c.execute(
                "SELECT * FROM audit WHERE document_id=? ORDER BY id DESC", (doc_id,))]
            d["outbox"] = [dict(r) for r in c.execute(
                "SELECT id,review_id,adapter,state,attempts,last_error,response,created,updated "
                "FROM outbox WHERE document_id=? ORDER BY created DESC", (doc_id,))]
            d["pages_detail"] = [
                {**dict(r), "rows": json.loads(r["rows"]), "steps": json.loads(r["steps"]),
                 "has_image": bool(r["image"])}
                for r in c.execute(
                    "SELECT page,method,width,height,rows,mean_score,steps,image,ms FROM pages "
                    "WHERE document_id=? AND version=? ORDER BY page", (doc_id, d["version"]))
            ]
        for p in d["pages_detail"]:
            p.pop("image")
        for job in d["jobs"]:
            job["timings"] = json.loads(job["timings"])
        for r in d["reviews"]:
            for key in ("fields", "provenance", "issues", "tables"):
                r[key] = json.loads(r[key] or "{}")
        for a in d["audit"]:
            a["detail"] = json.loads(a["detail"])
        d["template"] = self._template_or_none(d["template_id"])
        return d

    def _template_or_none(self, tid):
        try:
            return self.templates.get(tid) if tid else None
        except KeyError:
            return None

    def search(self, q="", status="", template="", date_from="", date_to="", archived=False,
               issues=False, sort="created", limit=50, offset=0) -> dict:
        where, params = ["d.archived=?"], [1 if archived else 0]
        if q.strip():
            terms = re.findall(r"\w+", q, re.UNICODE)[:8]
            if terms:
                where.append("d.id IN (SELECT document_id FROM search_index WHERE search_index MATCH ?)")
                params.append(" ".join('"' + t.replace('"', "") + '"*' for t in terms))
        if status:
            where.append("d.status=?")
            params.append(status)
        if template:
            where.append("d.template_id=?")
            params.append(template)
        if date_from:
            where.append("d.created>=?")
            params.append(date_from)
        if date_to:
            where.append("d.created<?")
            params.append(date_to + "T99")
        if issues:
            where.append("(d.status='error' OR d.fields LIKE '%\"issues\": [\"%')")
        order = {"created": "d.created DESC", "name": "d.name COLLATE NOCASE", "status": "d.status, d.created DESC",
                 "updated": "d.updated DESC"}.get(sort, "d.created DESC")
        # Only whitelisted fragments are interpolated; every value is a bound parameter.
        clause = " AND ".join(where)
        columns = ("d.id,d.name,d.mime,d.created,d.updated,d.status,d.version,d.method,d.template_id,"
                   "d.template_source,d.pages,d.size,d.archived,d.fields")
        count_sql = f"SELECT COUNT(*) FROM documents d WHERE {clause}"  # nosec B608
        list_sql = f"SELECT {columns} FROM documents d WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?"  # nosec B608
        with self.db.connect() as c:
            total = c.execute(count_sql, params).fetchone()[0]
            rows = c.execute(list_sql, (*params, max(1, min(limit, 200)), max(0, offset))).fetchall()
        items = []
        for r in rows:
            item = dict(r)
            fields = json.loads(item.pop("fields"))
            item["issue_count"] = sum(len(f.get("issues", [])) for f in fields.values())
            items.append(item)
        return {"items": items, "total": total}

    def file_path(self, doc_id: str) -> Path:
        return self.files / self.get(doc_id)["id"]

    def page_image(self, doc_id: str, page: int) -> Path:
        d = self.get(doc_id)
        with self.db.connect() as c:
            row = c.execute(
                "SELECT image FROM pages WHERE document_id=? AND version=? AND page=?",
                (doc_id, d["version"], page),
            ).fetchone()
        if row and row["image"]:
            path = self.page_dir / row["image"]
            if path.is_file():
                return path
        # Not OCRed (native PDF page or not yet processed): render a preview.
        if not 1 <= page <= max(d["pages"], 1):
            raise KeyError(page)
        target = self.page_dir / doc_id / f"preview-p{page}.png"
        if not target.is_file():
            target.parent.mkdir(exist_ok=True)
            data = (self.files / doc_id).read_bytes()
            if d["mime"] == "application/pdf":
                image = ocr.render_preview(data, page)
            elif d["mime"].startswith("image/"):
                frames = ocr.iter_pages(data, d["mime"], dpi=100, prefer_native=True, max_pages=200)
                image = next(p.image for p in frames if p.number == page)
            else:
                raise KeyError(page)
            image.thumbnail((2400, 2400))
            image.save(target, "PNG")
        return target

    # --- Processing ---------------------------------------------------------

    def queue(self, ids: list[str], actor: str, template_id: str = "") -> list[str]:
        if template_id:
            self.templates.get(template_id)
        jobs = []
        with self.db.connect(immediate=True) as c:
            for doc_id in ids:
                d = c.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()
                if d is None:
                    raise KeyError(doc_id)
                if d["status"] in BUSY:
                    raise Conflict("Document is already queued or processing")
                job_id = uid()
                c.execute(
                    "INSERT INTO jobs(id,document_id,state,created,previous_status) VALUES(?,?,?,?,?)",
                    (job_id, doc_id, "queued", now(), d["status"]),
                )
                if template_id:
                    c.execute("UPDATE documents SET template_id=?, template_source='user' WHERE id=?",
                              (template_id, doc_id))
                c.execute("UPDATE documents SET status='queued', updated=? WHERE id=?", (now(), doc_id))
                audit(c, doc_id, "processing.queued", actor, {"job": job_id, "template": template_id})
                jobs.append(job_id)
        self.wakeup.set()
        return jobs

    def cancel(self, job_id: str, actor: str) -> dict:
        with self.db.connect(immediate=True) as c:
            job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is None:
                raise KeyError(job_id)
            if job["state"] == "queued":
                c.execute("UPDATE jobs SET state='cancelled', finished=? WHERE id=?", (now(), job_id))
                c.execute("UPDATE documents SET status=? WHERE id=?",
                          (job["previous_status"] or "imported", job["document_id"]))
                audit(c, job["document_id"], "processing.cancelled", actor, {"job": job_id})
                return {"state": "cancelled"}
            if job["state"] == "running":
                c.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
                return {"state": "cancelling"}
        raise Conflict("Job already finished")

    def jobs(self, active_only: bool) -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT j.*, d.name FROM jobs j JOIN documents d ON d.id=j.document_id "
                "WHERE (?=0 OR j.state IN ('queued','running')) ORDER BY j.created DESC LIMIT 100",
                (int(active_only),),
            ).fetchall()
        return [{**dict(r), "timings": json.loads(r["timings"])} for r in rows]

    def _job_loop(self):
        while not self.stopping.is_set():
            try:
                while not self.stopping.is_set() and self.run_next_job():
                    pass
            except Exception:  # The job row records the failure; keep serving.
                logging.getLogger("letranix.jobs").exception("Job loop iteration failed")
                time.sleep(0.5)
            self.wakeup.wait(2)
            self.wakeup.clear()

    def run_next_job(self) -> bool:
        with self.db.maintenance:
            with self.db.connect(immediate=True) as c:
                job = c.execute(
                    "SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1"
                ).fetchone()
                if job is None:
                    return False
                c.execute(
                    "UPDATE jobs SET state='running', started=?, attempts=attempts+1 WHERE id=?",
                    (now(), job["id"]),
                )
                c.execute("UPDATE documents SET status='processing' WHERE id=?", (job["document_id"],))
                audit(c, job["document_id"], "processing.started", "system", {"job": job["id"]})
            self._process(dict(job))
        return True

    def _check_cancel(self, job_id: str):
        with self.db.connect() as c:
            if c.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()[0]:
                raise ocr.Cancelled()
        if self.stopping.is_set():
            raise InterruptedError()

    def _process(self, job: dict):
        job_id, doc_id = job["id"], job["document_id"]
        started = time.perf_counter()
        timings = {}
        try:
            d = self.get(doc_id)
            values = self.settings.all()
            data = (self.files / doc_id).read_bytes()
            total = ocr.count_pages(data, d["mime"])
            with self.db.connect() as c:
                c.execute("UPDATE jobs SET total=? WHERE id=?", (total, job_id))
            options = {k.split(".")[-1]: v for k, v in values.items() if k.startswith("ocr.preprocess.")}
            options["auto_orientation"] = values["ocr.auto_orientation"]
            results = []
            for page in ocr.iter_pages(data, d["mime"], dpi=values["ocr.render_dpi"],
                                       prefer_native=values["ocr.prefer_native_pdf_text"],
                                       max_pages=values["processing.max_pages"]):
                self._check_cancel(job_id)
                if page.text is not None:
                    results.append(ocr.native_page(page))
                elif values["ocr.engine"] == "none":
                    raise ocr.DocumentError("ocr-disabled", "Image OCR is disabled in Settings")
                else:
                    results.append(ocr.ocr_page(page, options))
                with self.db.connect() as c:
                    c.execute("UPDATE jobs SET progress=? WHERE id=?", (len(results), job_id))
            self._check_cancel(job_id)
            timings["read_ms"] = round((time.perf_counter() - started) * 1000)
            timings["ocr_ms"] = sum(r.ms for r in results)
            text = "\n\f\n".join(r.text for r in results)
            if not text.strip():
                raise ocr.DocumentError("no-text", "No text was recognised; check image quality or orientation")
            t0 = time.perf_counter()
            pages = [{"number": r.number, "rows": r.rows} for r in results]
            templates = self.templates.all()
            prediction = Classifier.predict(self.classifier.model(self.db, templates), text)
            template_id, template_source = d["template_id"], d["template_source"]
            if template_source != "user" or not template_id:
                template_id = prediction[0]["template"] if prediction else "generic-record"
                template_source = "classifier"
            template = self.templates.get(template_id)
            with self.db.connect() as c:
                rules = active_rules(c, template_id, values["learning.min_support"]) if values[
                    "learning.enabled"] else []
            extracted = extract_fields(pages, template, rules, values["ocr.min_line_score"])
            timings["extract_ms"] = round((time.perf_counter() - t0) * 1000)
            timings["total_ms"] = round((time.perf_counter() - started) * 1000)
            methods = sorted({r.method for r in results})
            version = d["version"] + 1
            images = []
            for r in results:
                name = ""
                if r.image is not None:
                    name = f"{doc_id}/v{version}-p{r.number}.png"
                    (self.page_dir / doc_id).mkdir(exist_ok=True)
                    r.image.save(self.page_dir / name, "PNG", optimize=False)
                images.append(name)
            used_rules = [rid for f in extracted["fields"].values() for rid in f.get("learned", [])
                          if f["rule"].startswith("learned")]
            with self.db.connect(immediate=True) as c:
                for r, image in zip(results, images):
                    c.execute(
                        "INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (doc_id, version, r.number, r.method, r.width, r.height, r.text,
                         json.dumps(r.rows), r.mean_score, json.dumps(r.steps), image, r.ms),
                    )
                c.execute(
                    "UPDATE documents SET status='needs-review', version=?, text=?, method=?, fields=?, "
                    "tables=?, classification=?, template_id=?, template_source=?, pages=?, updated=? "
                    "WHERE id=?",
                    (version, text, "+".join(methods), json.dumps(extracted["fields"]),
                     json.dumps({"table": extracted["table"], "pairs": extracted["pairs"]}),
                     json.dumps(prediction), template_id, template_source, len(results), now(), doc_id),
                )
                c.execute("DELETE FROM search_index WHERE document_id=?", (doc_id,))
                values_text = " ".join(f["value"] for f in extracted["fields"].values())
                c.execute("INSERT INTO search_index(document_id,name,body) VALUES(?,?,?)",
                          (doc_id, d["name"], text + "\n" + values_text))
                for rid in set(used_rules):
                    c.execute("UPDATE rules SET applied=applied+1 WHERE id=?", (rid,))
                c.execute("UPDATE jobs SET state='done', finished=?, timings=? WHERE id=?",
                          (now(), json.dumps(timings), job_id))
                audit(c, doc_id, "processing.completed", "system", {
                    "job": job_id, "version": version, "method": "+".join(methods), "pages": len(results),
                    "template": template_id, "template_source": template_source,
                    "learned_rules_applied": len(set(used_rules)), **timings,
                })
        except ocr.Cancelled:
            self._finish_job(job, "cancelled", "Cancelled by user", "processing.cancelled", {})
        except InterruptedError:
            pass  # Shutdown: left 'running' so recover() requeues it on next start.
        except ocr.DocumentError as exc:
            self._finish_job(job, "failed", str(exc), "processing.failed", {"code": exc.code})
        except Exception as exc:
            # Never surface parser traces, paths or document content.
            self._finish_job(job, "failed", "Unexpected processing error; see audit for the error type",
                             "processing.failed", {"code": "internal", "type": type(exc).__name__})

    def _finish_job(self, job, state, message, event, detail):
        status = (job["previous_status"] or "imported") if state == "cancelled" else "error"
        with self.db.connect(immediate=True) as c:
            c.execute("UPDATE jobs SET state=?, error=?, finished=? WHERE id=?",
                      (state, message, now(), job["id"]))
            c.execute("UPDATE documents SET status=?, updated=? WHERE id=?", (status, now(), job["document_id"]))
            audit(c, job["document_id"], event, "system", {"job": job["id"], **detail})

    def apply_template(self, doc_id: str, template_id: str, actor: str) -> dict:
        """Re-extract stored pages with another template (no OCR rerun); creates a new version."""
        template = self.templates.get(template_id)
        values = self.settings.all()
        with self.db.connect(immediate=True) as c:
            d = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if d is None:
                raise KeyError(doc_id)
            if d["status"] in BUSY or d["version"] == 0:
                raise Conflict("Process the document before changing its type")
            rows = c.execute("SELECT * FROM pages WHERE document_id=? AND version=? ORDER BY page",
                             (doc_id, d["version"])).fetchall()
            pages = [{"number": r["page"], "rows": json.loads(r["rows"])} for r in rows]
            rules = active_rules(c, template_id, values["learning.min_support"]) if values[
                "learning.enabled"] else []
            extracted = extract_fields(pages, template, rules, values["ocr.min_line_score"])
            version = d["version"] + 1
            for r in rows:
                c.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (doc_id, version, r["page"], r["method"], r["width"], r["height"], r["text"],
                           r["rows"], r["mean_score"], r["steps"], r["image"], r["ms"]))
            c.execute(
                "UPDATE documents SET version=?, fields=?, tables=?, template_id=?, template_source='user', "
                "status='needs-review', updated=? WHERE id=?",
                (version, json.dumps(extracted["fields"]),
                 json.dumps({"table": extracted["table"], "pairs": extracted["pairs"]}),
                 template_id, now(), doc_id),
            )
            audit(c, doc_id, "extraction.template-applied", actor, {"template": template_id, "version": version})
        return self.detail(doc_id)

    # --- Review -------------------------------------------------------------

    def review(self, doc_id: str, body: dict) -> dict:
        actor = body["actor"].strip()
        reason = body["reason"].strip()
        decision = body["decision"]
        values = self.settings.all()
        if len(actor) < 2:
            raise Invalid("Reviewer name required")
        if decision == "rejected" and len(reason) < 5:
            raise Invalid("Explain the rejection (at least 5 characters)")
        if decision == "approved" and values["review.require_approval_reason"] and len(reason) < 5:
            raise Invalid("A reason is required to approve (Settings > Review)")
        d = self.get(doc_id)
        template = self.templates.get(d["template_id"] or "generic-record")
        keys = [f["key"] for f in template["fields"]]
        submitted = body["fields"]
        if set(submitted) != set(keys) or any(len(v) > 1000 for v in submitted.values()):
            raise Invalid("Submit exactly the template's fields; at most 1000 characters each")
        submitted = {k: v.strip() for k, v in submitted.items()}
        flags = {k: v.strip()[:300] for k, v in (body.get("issues") or {}).items() if k in keys and v.strip()}
        table_rows = body.get("table") or []
        if len(table_rows) > 200:
            raise Invalid("At most 200 table rows")
        if decision == "approved":
            problems = {f["key"]: validate_value(submitted[f["key"]], f) for f in template["fields"]}
            problems = {k: v for k, v in problems.items() if v}
            if problems:
                raise Invalid("Fix the highlighted fields before approving", problems)
            if flags:
                raise Invalid("Resolve or clear flagged inconsistencies before approving",
                              {k: ["Flagged: " + v] for k, v in flags.items()})
        extracted = json.loads(d["fields"])
        provenance = {}
        for key in keys:
            before = extracted.get(key, {})
            if submitted[key] == before.get("value", ""):
                provenance[key] = "confirmed" if submitted[key] else "empty"
            else:
                provenance[key] = "entered" if not before.get("value") else "corrected"
        review_id = uid()
        with self.db.connect(immediate=True) as c:
            current = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if current["version"] != body["version"] or current["status"] != "needs-review":
                raise Conflict("Document changed or already reviewed; reload before deciding")
            c.execute(
                "INSERT INTO reviews(id,document_id,version,decision,actor,reason,fields,created,template_id,"
                "provenance,issues,tables) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (review_id, doc_id, body["version"], decision, actor, reason, json.dumps(submitted), now(),
                 template["id"], json.dumps(provenance), json.dumps(flags), json.dumps({"rows": table_rows})),
            )
            c.execute("UPDATE documents SET status=?, updated=? WHERE id=?", (decision, now(), doc_id))
            changed = [k for k, v in provenance.items() if v in {"corrected", "entered"}]
            audit(c, doc_id, "review." + decision, actor,
                  {"review": review_id, "version": body["version"], "changed_fields": changed,
                   "flagged_fields": sorted(flags)})
            learned = []
            if decision == "approved":
                learned = learn_from_review(c, current, template, submitted, review_id, actor)
        return {"review_id": review_id, "integration_executed": False, "rules_updated": len(set(learned))}

    def reopen(self, doc_id: str, actor: str, reason: str) -> dict:
        if len(reason.strip()) < 5:
            raise Invalid("Explain why the review is reopened")
        with self.db.connect(immediate=True) as c:
            d = c.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()
            if d is None:
                raise KeyError(doc_id)
            if d["status"] not in {"approved", "rejected"}:
                raise Conflict("Only decided documents can be reopened")
            c.execute("UPDATE documents SET status='needs-review', updated=? WHERE id=?", (now(), doc_id))
            audit(c, doc_id, "review.reopened", actor.strip() or "local-user", {"reason_length": len(reason)})
        return self.detail(doc_id)

    # --- Integration --------------------------------------------------------

    def integrate(self, doc_id: str, review_id: str, actor: str) -> dict:
        values = self.settings.all()
        adapter = values["integration.adapter"]
        with self.db.connect(immediate=True) as c:
            d = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if d is None:
                raise KeyError(doc_id)
            r = c.execute(
                "SELECT * FROM reviews WHERE document_id=? AND version=? ORDER BY created DESC LIMIT 1",
                (doc_id, d["version"]),
            ).fetchone()
            if not r or r["id"] != review_id or r["decision"] != "approved" or d["status"] != "approved":
                raise Conflict("The current approved review is required")
            existing = c.execute(
                "SELECT * FROM outbox WHERE adapter=? AND idempotency_key=?", (adapter, review_id)
            ).fetchone()
            if existing:
                return {"outbox": existing["id"], "state": existing["state"], "duplicate": True}
            payload = build_payload(d, r, self.templates.get(r["template_id"]))
            try:
                validate_payload(payload)
            except PermanentError as exc:
                raise Invalid(str(exc)) from None
            entry = uid()
            c.execute(
                "INSERT INTO outbox(id,review_id,document_id,adapter,idempotency_key,payload,state,"
                "next_attempt,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (entry, review_id, doc_id, adapter, review_id, json.dumps(payload), "pending", now(), now(), now()),
            )
            audit(c, doc_id, "integration.queued", actor, {"outbox": entry, "adapter": adapter, "review": review_id})
        self.outbox.wakeup.set()
        return {"outbox": entry, "state": "pending", "duplicate": False}

    def retry_outbox(self, entry_id: str, actor: str) -> dict:
        with self.db.connect(immediate=True) as c:
            row = c.execute("SELECT * FROM outbox WHERE id=?", (entry_id,)).fetchone()
            if row is None:
                raise KeyError(entry_id)
            if row["state"] != "failed":
                raise Conflict("Only failed deliveries can be retried")
            c.execute("UPDATE outbox SET state='pending', attempts=0, next_attempt=?, updated=? WHERE id=?",
                      (now(), now(), entry_id))
            audit(c, row["document_id"], "integration.retried", actor, {"outbox": entry_id})
        self.outbox.wakeup.set()
        return {"state": "pending"}

    def outbox_list(self) -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT o.id,o.review_id,o.document_id,o.adapter,o.state,o.attempts,o.last_error,o.response,"
                "o.created,o.updated,o.next_attempt,d.name FROM outbox o LEFT JOIN documents d ON d.id=o.document_id "
                "ORDER BY o.created DESC LIMIT 200"
            ).fetchall()
        return [{**dict(r), "response": json.loads(r["response"])} for r in rows]

    def destination_records(self) -> dict:
        values = self.settings.all()
        adapter = make_adapter(self.db, values)
        return {"adapter": adapter.name, "records": adapter.records(100)}

    # --- Lifecycle ----------------------------------------------------------

    def archive(self, doc_id: str, archived: bool, actor: str):
        with self.db.connect(immediate=True) as c:
            d = c.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()
            if d is None:
                raise KeyError(doc_id)
            if d["status"] in BUSY:
                raise Conflict("Wait for processing to finish")
            c.execute("UPDATE documents SET archived=?, updated=? WHERE id=?", (int(archived), now(), doc_id))
            audit(c, doc_id, "document.archived" if archived else "document.unarchived", actor, {})

    def delete(self, doc_id: str, confirm: str, actor: str):
        """Permanent removal of the file, pages and reviews. Audit history is kept."""
        with self.db.connect(immediate=True) as c:
            d = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if d is None:
                raise KeyError(doc_id)
            if confirm != d["name"]:
                raise Invalid("Type the document name exactly to confirm deletion")
            if not d["archived"]:
                raise Conflict("Archive the document before deleting it")
            if d["status"] in BUSY:
                raise Conflict("Wait for processing to finish")
            if c.execute("SELECT 1 FROM outbox WHERE document_id=? AND state IN ('pending','delivering')",
                         (doc_id,)).fetchone():
                raise Conflict("An integration delivery is still pending")
            for table in ("pages", "jobs", "reviews", "outbox", "corrections", "search_index"):
                c.execute(f"DELETE FROM {table} WHERE document_id=?", (doc_id,))  # nosec B608 - fixed names
            c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            audit(c, doc_id, "document.deleted", actor, {"sha256": d["digest"], "mime": d["mime"]})
        (self.files / doc_id).unlink(missing_ok=True)
        folder = self.page_dir / doc_id
        if folder.is_dir():
            for p in folder.iterdir():
                p.unlink()
            folder.rmdir()

    # --- Export -------------------------------------------------------------

    def export_records(self, fmt: str, template: str, actor: str) -> tuple[bytes, str]:
        with self.db.connect() as c:
            rows = c.execute(
                """SELECT d.id, d.name, d.digest, r.id AS review_id, r.version, r.actor, r.created,
                r.template_id, r.fields, r.provenance FROM documents d JOIN reviews r ON r.document_id=d.id
                WHERE d.status='approved' AND r.decision='approved' AND r.version=d.version
                AND (?='' OR r.template_id=?) AND r.created=(SELECT MAX(created) FROM reviews
                WHERE document_id=d.id AND version=d.version) ORDER BY r.created""",
                (template, template),
            ).fetchall()
        records = [
            {"document_id": r["id"], "document": r["name"], "sha256": r["digest"], "review_id": r["review_id"],
             "version": r["version"], "reviewer": r["actor"], "approved_at": r["created"],
             "template": r["template_id"], "fields": json.loads(r["fields"]),
             "provenance": json.loads(r["provenance"])}
            for r in rows
        ]
        with self.db.connect() as c:
            audit(c, None, "export.created", actor, {"format": fmt, "records": len(records), "template": template})
        if fmt == "json":
            return json.dumps(records, indent=2, ensure_ascii=False).encode(), "application/json"
        buffer = io.StringIO()
        field_names = sorted({k for r in records for k in r["fields"]})
        writer = csv.writer(buffer)
        writer.writerow(["document_id", "document", "template", "reviewer", "approved_at", *field_names])
        for r in records:
            writer.writerow([_csv_safe(x) for x in (r["document_id"], r["document"], r["template"], r["reviewer"],
                             r["approved_at"], *[r["fields"].get(k, "") for k in field_names])])
        return buffer.getvalue().encode("utf-8-sig"), "text/csv"

    def export_document(self, doc_id: str, actor: str) -> bytes:
        d = self.detail(doc_id)
        with self.db.connect() as c:
            audit(c, doc_id, "export.document", actor, {"version": d["version"]})
        keep = ("id", "name", "mime", "digest", "created", "status", "version", "method", "template_id",
                "template_source", "classification", "fields", "tables", "reviews", "pages_detail", "text")
        return json.dumps({k: d[k] for k in keep}, indent=2, ensure_ascii=False).encode()

    # --- Queries ------------------------------------------------------------

    def audit_log(self, event="", document="", actor="", limit=100, offset=0) -> dict:
        where, params = [], []
        if event:
            where.append("a.event LIKE ?")
            params.append(event.replace("%", "") + "%")
        if document:
            where.append("a.document_id=?")
            params.append(document)
        if actor:
            where.append("a.actor=?")
            params.append(actor)
        clause = ("WHERE " + " AND ".join(where)) if where else ""  # Fixed fragments; values bound.
        count_sql = f"SELECT COUNT(*) FROM audit a {clause}"  # nosec B608
        list_sql = (
            f"SELECT a.*, d.name FROM audit a LEFT JOIN documents d ON d.id=a.document_id {clause} "  # nosec B608
            "ORDER BY a.id DESC LIMIT ? OFFSET ?"
        )
        with self.db.connect() as c:
            total = c.execute(count_sql, params).fetchone()[0]
            rows = c.execute(list_sql, (*params, max(1, min(limit, 500)), max(0, offset))).fetchall()
            events = [r[0] for r in c.execute("SELECT DISTINCT event FROM audit ORDER BY event")]
        return {"items": [{**dict(r), "detail": json.loads(r["detail"])} for r in rows], "total": total,
                "events": events}

    def overview(self) -> dict:
        with self.db.connect() as c:
            by_status = dict(c.execute(
                "SELECT status, COUNT(*) FROM documents WHERE archived=0 GROUP BY status").fetchall())
            by_template = dict(c.execute(
                "SELECT template_id, COUNT(*) FROM documents WHERE archived=0 AND template_id!='' "
                "GROUP BY template_id").fetchall())
            archived = c.execute("SELECT COUNT(*) FROM documents WHERE archived=1").fetchone()[0]
            timing = c.execute(
                "SELECT COUNT(*), AVG(json_extract(timings,'$.total_ms')), MAX(json_extract(timings,'$.total_ms')) "
                "FROM jobs WHERE state='done' AND timings!='{}'").fetchone()
            corrections = c.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
            reviewed_fields = c.execute(
                "SELECT COUNT(*) FROM reviews r, json_each(r.fields) WHERE r.decision='approved'").fetchone()[0]
            rules = c.execute(
                "SELECT COUNT(*), SUM(enabled AND support>=?), SUM(applied) FROM rules",
                (self.settings.get("learning.min_support"),)).fetchone()
            outbox = dict(c.execute("SELECT state, COUNT(*) FROM outbox GROUP BY state").fetchall())
            recent = [dict(r) for r in c.execute(
                "SELECT a.event, a.created, a.document_id, d.name FROM audit a LEFT JOIN documents d "
                "ON d.id=a.document_id ORDER BY a.id DESC LIMIT 8")]
        return {
            "by_status": by_status, "by_template": by_template, "archived": archived,
            "processing": {"jobs": timing[0], "avg_ms": round(timing[1] or 0), "max_ms": timing[2] or 0},
            "review": {"approved_fields": reviewed_fields, "corrections": corrections},
            "learning": {"rules": rules[0], "active": rules[1] or 0, "applied": rules[2] or 0},
            "outbox": outbox, "recent": recent,
        }

    def rules(self) -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM rules ORDER BY template_id, field, support DESC").fetchall()
        min_support = self.settings.get("learning.min_support")
        return [{**dict(r), "active": bool(r["enabled"]) and r["support"] >= min_support} for r in rows]

    def set_rule(self, rule_id: str, enabled: bool, actor: str):
        with self.db.connect(immediate=True) as c:
            if not c.execute("UPDATE rules SET enabled=?, updated=? WHERE id=?",
                             (int(enabled), now(), rule_id)).rowcount:
                raise KeyError(rule_id)
            audit(c, None, "learning.rule-" + ("enabled" if enabled else "disabled"), actor, {"rule": rule_id})

    def delete_rule(self, rule_id: str, actor: str):
        with self.db.connect(immediate=True) as c:
            if not c.execute("DELETE FROM rules WHERE id=?", (rule_id,)).rowcount:
                raise KeyError(rule_id)
            audit(c, None, "learning.rule-deleted", actor, {"rule": rule_id})


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection in exported cells."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

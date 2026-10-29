"""Service and API behaviour through the HTTP layer, with the real database and pipeline."""

import csv
import io
import json
import socket
import sqlite3
import time
import zipfile

import pytest
from pypdf import PdfWriter

from conftest import SAMPLE, approve_payload, client_for, drain, imported, processed, svc
from letranix.demo import native_pdf


def test_full_review_flow_with_correction_learning_and_restart(tmp_path):
    root = tmp_path / "ws"
    c = client_for(root)
    d = processed(c)
    assert d["template_id"] == "service-order"
    assert d["fields"]["order_number"]["value"] == "SO-10001"
    assert d["fields"]["date"]["evidence"] == "Date: 2026-01-15"
    body = approve_payload(d)
    body["fields"]["description"] = "Inspect the synthetic scanner and log it"
    r = c.post(f"/api/documents/{d['id']}/review", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["integration_executed"] is False
    saved = c.get(f"/api/documents/{d['id']}").json()
    review = saved["reviews"][0]
    assert review["provenance"]["description"] == "corrected"
    assert review["provenance"]["order_number"] == "confirmed"
    # The automatic extraction is preserved next to the human decision.
    assert saved["fields"]["description"]["value"] == "Inspect the synthetic scanner"
    with svc(c).db.connect() as db:
        corrections = db.execute("SELECT field, extracted, confirmed FROM corrections").fetchall()
    assert [tuple(x) for x in corrections] == [
        ("description", "Inspect the synthetic scanner", "Inspect the synthetic scanner and log it")
    ]
    c.close()
    with client_for(root) as again:
        persisted = again.get(f"/api/documents/{d['id']}").json()
        assert persisted["status"] == "approved"
        assert persisted["reviews"][0]["fields"]["description"].endswith("log it")
        events = [a["event"] for a in persisted["audit"]]
        for event in ("document.imported", "processing.queued", "processing.started",
                      "processing.completed", "review.approved"):
            assert event in events
        assert again.get(f"/api/documents/{d['id']}/file").content == SAMPLE


@pytest.mark.parametrize("data,code", [
    (b"", "empty"),
    (b"MZ\x00\x00binary", "unsupported"),
    (b"bad\x01text", "invalid-text"),
    (b"%PDF-1.4 not really a pdf", "corrupted"),
    (b"\x89PNG\r\n\x1a\ntruncated", "corrupted"),
])
def test_invalid_documents_rejected_at_import(client, data, code):
    r = client.post("/api/documents", files={"file": ("bad", data)})
    assert r.status_code == 422 and r.json()["code"] == code
    assert client.get("/api/documents").json()["total"] == 0


def test_encrypted_and_oversized_and_page_limits(client):
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("synthetic")
    buf = io.BytesIO()
    writer.write(buf)
    r = client.post("/api/documents", files={"file": ("e.pdf", buf.getvalue())})
    assert r.json()["code"] == "encrypted"
    client.patch("/api/settings", json={"processing.max_file_mb": 1, "processing.max_pages": 2})
    big = b"Reference: X\n" + b"a" * (1024 * 1024)
    assert client.post("/api/documents", files={"file": ("big.txt", big)}).json()["code"] == "too-large"
    three = native_pdf([["Page one text long enough"], ["Two"], ["Three"]])
    assert client.post("/api/documents", files={"file": ("p.pdf", three)}).json()["code"] == "too-many-pages"


def test_path_safe_names_and_deduplication(client):
    first = imported(client, name="../../outside.txt")
    r = client.post("/api/documents", files={"file": ("again.txt", SAMPLE)})
    assert r.json() == {"id": first, "duplicate": True, "queued": False}
    assert client.get(f"/api/documents/{first}").json()["name"] == "outside.txt"
    assert list((svc(client).files).iterdir())[0].name == first


def test_empty_ocr_result_and_disabled_engine_fail_cleanly(client):
    client.patch("/api/settings", json={"ocr.engine": "none"})
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, "PNG")
    doc_id = imported(client, buf.getvalue(), "blank.png")
    drain(client)
    d = client.get(f"/api/documents/{doc_id}").json()
    assert d["status"] == "error"
    assert d["jobs"][0]["error"] == "Image OCR is disabled in Settings"
    failure = [a for a in d["audit"] if a["event"] == "processing.failed"][0]
    assert failure["detail"]["code"] == "ocr-disabled"


def test_native_text_without_labels_yields_missing_not_invented(client):
    d = processed(client, b"Nothing structured here at all.\nJust a sentence.\n", "plain.txt")
    assert all(f["value"] == "" for f in d["fields"].values())
    assert all(f["source"] == "missing" for f in d["fields"].values())


@pytest.mark.parametrize("change,status", [
    ("stale", 409), ("bad-date", 422), ("bad-enum", 422), ("missing-required", 422),
    ("no-reason", 422), ("extra-field", 422), ("flagged", 422),
])
def test_review_validation(client, change, status):
    d = processed(client)
    body = approve_payload(d)
    if change == "stale":
        body["version"] += 1
    elif change == "bad-date":
        body["fields"]["date"] = "2026-02-30"
    elif change == "bad-enum":
        body["fields"]["priority"] = "whenever"
    elif change == "missing-required":
        body["fields"]["requester"] = ""
    elif change == "no-reason":
        body["reason"] = "ok"
    elif change == "extra-field":
        body["fields"]["unknown"] = "x"
    elif change == "flagged":
        body["issues"] = {"date": "Date conflicts with the stamp"}
    r = client.post(f"/api/documents/{d['id']}/review", json=body)
    assert r.status_code == status, r.text
    if change in {"bad-date", "bad-enum", "missing-required"}:
        assert r.json()["fields"]  # Per-field messages for the review form.
    assert client.get(f"/api/documents/{d['id']}").json()["reviews"] == []


def test_reject_with_flag_then_reopen_and_approve(client):
    d = processed(client)
    path = f"/api/documents/{d['id']}"
    body = approve_payload(d, decision="rejected", reason="Date conflicts with stamp")
    body["issues"] = {"date": "Stamp shows another day"}
    assert client.post(path + "/review", json=body).status_code == 200
    assert client.get(path).json()["reviews"][0]["issues"] == {"date": "Stamp shows another day"}
    assert client.post(path + "/reopen", json={"actor": "Lead", "reason": "x"}).status_code == 422
    r = client.post(path + "/reopen", json={"actor": "Lead", "reason": "Stamp clarified by requester"})
    assert r.status_code == 200 and r.json()["status"] == "needs-review"
    assert client.post(path + "/review", json=approve_payload(r.json())).status_code == 200
    assert [x["decision"] for x in client.get(path).json()["reviews"]] == ["approved", "rejected"]


def test_reprocessing_invalidates_previous_approval(client):
    d = processed(client)
    path = f"/api/documents/{d['id']}"
    review_id = client.post(path + "/review", json=approve_payload(d)).json()["review_id"]
    client.post(path + "/process", json={})
    drain(client)
    assert client.get(path).json()["version"] == 2
    r = client.post(path + "/integrate", json={"review_id": review_id, "authorize": True})
    assert r.status_code == 409


def test_change_type_reextracts_without_ocr(client):
    d = processed(client)
    r = client.post(f"/api/documents/{d['id']}/template", json={"template_id": "generic-record"})
    assert r.status_code == 200
    out = r.json()
    assert out["template_id"] == "generic-record" and out["template_source"] == "user"
    assert out["version"] == d["version"] + 1
    assert set(out["fields"]) == {"reference", "organization", "category", "date", "description"}
    assert out["fields"]["date"]["value"] == "2026-01-15"


def test_local_ledger_integration_is_explicit_and_idempotent(client):
    d = processed(client)
    path = f"/api/documents/{d['id']}"
    review_id = client.post(path + "/review", json=approve_payload(d)).json()["review_id"]
    assert client.post(path + "/integrate", json={"review_id": review_id, "authorize": False}).status_code == 422
    first = client.post(path + "/integrate", json={"review_id": review_id, "authorize": True}).json()
    again = client.post(path + "/integrate", json={"review_id": review_id, "authorize": True}).json()
    assert again["duplicate"] and again["outbox"] == first["outbox"]
    assert svc(client).outbox.run_once()
    assert not svc(client).outbox.run_once()
    records = client.get("/api/integrations/destination").json()
    assert records["adapter"] == "local-ledger"
    assert len(records["records"]) == 1
    assert records["records"][0]["fields"]["order_number"] == "SO-10001"
    events = [a["event"] for a in client.get(path).json()["audit"]]
    assert "integration.queued" in events and "integration.delivered" in events


def test_rejected_review_cannot_integrate(client):
    d = processed(client)
    path = f"/api/documents/{d['id']}"
    rid = client.post(path + "/review", json=approve_payload(d, decision="rejected")).json()["review_id"]
    assert client.post(path + "/integrate", json={"review_id": rid, "authorize": True}).status_code == 409


def test_cancel_queued_and_running_jobs(client, monkeypatch):
    client.patch("/api/settings", json={"processing.auto_process": False})
    doc_id = imported(client)
    job = client.post(f"/api/documents/{doc_id}/process", json={}).json()["jobs"][0]
    assert client.post(f"/api/jobs/{job}/cancel").json() == {"state": "cancelled"}
    assert client.get(f"/api/documents/{doc_id}").json()["status"] == "imported"

    job = client.post(f"/api/documents/{doc_id}/process", json={}).json()["jobs"][0]
    from letranix import ocr

    original = ocr.native_page

    def slow_page(page):  # Cancellation arrives while the first page is being read.
        client.post(f"/api/jobs/{job}/cancel")
        return original(page)

    monkeypatch.setattr(ocr, "native_page", slow_page)
    pdf = native_pdf([["Order No.: SO-10002 long enough text"], ["Second page with more words"]])
    pdf_id = imported(client, pdf, "two.pdf")
    job = client.post(f"/api/documents/{pdf_id}/process", json={}).json()["jobs"][0]
    drain(client)
    d = client.get(f"/api/documents/{pdf_id}").json()
    assert d["jobs"][0]["state"] == "cancelled" and d["status"] == "imported" and d["version"] == 0


def test_interrupted_job_is_requeued_then_failed(tmp_path):
    root = tmp_path / "ws"
    c = client_for(root)
    c.patch("/api/settings", json={"processing.auto_process": False})
    doc_id = imported(c)
    job = c.post(f"/api/documents/{doc_id}/process", json={}).json()["jobs"][0]
    with svc(c).db.connect() as db:  # Simulate a crash mid-processing.
        db.execute("UPDATE jobs SET state='running', attempts=1 WHERE id=?", (job,))
        db.execute("UPDATE documents SET status='processing' WHERE id=?", (doc_id,))
    c.close()
    c = client_for(root)
    assert c.get(f"/api/documents/{doc_id}").json()["status"] == "queued"
    with svc(c).db.connect() as db:
        db.execute("UPDATE jobs SET state='running', attempts=2 WHERE id=?", (job,))
    c.close()
    with client_for(root) as c:
        d = c.get(f"/api/documents/{doc_id}").json()
        assert d["status"] == "error" and "interrupted" in d["jobs"][0]["error"]
        assert c.post(f"/api/documents/{doc_id}/process", json={}).status_code == 200
        drain(c)
        assert c.get(f"/api/documents/{doc_id}").json()["status"] == "needs-review"


def test_background_worker_processes_without_manual_drain(tmp_path):
    with client_for(tmp_path / "ws", workers=True) as c:
        doc_id = imported(c)
        for _ in range(100):
            if c.get(f"/api/documents/{doc_id}").json()["status"] == "needs-review":
                break
            time.sleep(0.1)
        assert c.get(f"/api/documents/{doc_id}").json()["status"] == "needs-review"


def test_learning_alias_activates_after_min_support_and_is_contradicted(client):
    client.patch("/api/settings", json={"learning.min_support": 2})

    def doc(n, contact="Raised by"):
        return (f"SERVICE ORDER\nOrder No.: SO-2000{n}\n{contact}: Person {n}\nDate: 2026-01-0{n}\n"
                f"Priority: low\nDescription: Task {n}\n").encode()

    for n in (1, 2):
        d = processed(client, doc(n), f"o{n}.txt")
        assert d["fields"]["requester"]["value"] == ""
        body = approve_payload(d)
        body["fields"]["requester"] = f"Person {n}"
        client.post(f"/api/documents/{d['id']}/review", json=body)
    rules = client.get("/api/learning/rules").json()
    alias = [r for r in rules if r["kind"] == "alias" and r["pattern"] == "raised by"][0]
    assert alias["support"] == 2 and alias["active"]
    d = processed(client, doc(3), "o3.txt")
    assert d["fields"]["requester"]["value"] == "Person 3"
    assert d["fields"]["requester"]["rule"] == "learned-alias"
    body = approve_payload(d)  # Confirmation adds evidence.
    client.post(f"/api/documents/{d['id']}/review", json=body)
    assert [r for r in client.get("/api/learning/rules").json() if r["id"] == alias["id"]][0]["support"] == 3
    # Contradictions above support disable the rule automatically.
    for n in (4, 5, 6, 7):
        d = processed(client, doc(n), f"o{n}.txt")
        body = approve_payload(d)
        body["fields"]["requester"] = "Someone Else"
        client.post(f"/api/documents/{d['id']}/review", json=body)
    rule = [r for r in client.get("/api/learning/rules").json() if r["id"] == alias["id"]][0]
    assert rule["rejected"] == 4 and not rule["enabled"]


def test_classifier_learns_custom_type_from_approvals(client):
    template = {"id": "lab-sample", "name": "Lab sample", "keywords": [],
                "fields": [{"key": "sample_id", "type": "identifier", "labels": ["sample id"]}]}
    assert client.post("/api/templates", json=template).status_code == 200
    # Starts out looking like an inspection report; approvals teach the new type.
    text = b"Inspection checklist\nSite inspector notes\nCentrifuge rotor viscosity\nSample ID: LS-{n}\n"
    first = processed(client, text.replace(b"{n}", b"1"), "s1.txt")
    assert first["template_id"] != "lab-sample"
    for n in range(1, 4):
        d = client.get(f"/api/documents/{first['id']}").json() if n == 1 else processed(
            client, text.replace(b"{n}", str(n).encode()), f"s{n}.txt")
        d = client.post(f"/api/documents/{d['id']}/template", json={"template_id": "lab-sample"}).json()
        client.post(f"/api/documents/{d['id']}/review", json=approve_payload(d))
    d = processed(client, text.replace(b"{n}", b"9"), "s9.txt")
    assert d["template_id"] == "lab-sample" and d["template_source"] == "classifier"


def test_templates_crud_rules(client):
    assert client.post("/api/templates", json={"id": "service-order", "name": "x",
                                                "fields": [{"key": "a"}]}).status_code == 403
    assert client.post("/api/templates", json={"id": "Bad Id", "name": "x",
                                                "fields": [{"key": "a"}]}).status_code == 422
    assert client.delete("/api/templates/invoice").status_code == 403
    ok = {"id": "custom-a", "name": "Custom", "fields": [{"key": "code", "type": "identifier"}]}
    assert client.post("/api/templates", json=ok).status_code == 200
    assert client.delete("/api/templates/custom-a").status_code == 200


def test_settings_are_validated_and_take_effect(client, tmp_path):
    for bad in ({"processing.max_file_mb": 0}, {"processing.max_file_mb": True},
                {"integration.endpoint": "http://example.com/records"},
                {"integration.endpoint": "file:///etc/passwd"}, {"ocr.engine": "cloud"},
                {"processing.inbox_dir": "relative/dir"}, {"unknown.key": 1}):
        assert client.patch("/api/settings", json=bad).status_code == 422, bad
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_bytes(SAMPLE)
    (inbox / "b.exe").write_bytes(b"MZ")
    (inbox / "c.txt").write_bytes(b"\x00bad")
    assert client.patch("/api/settings", json={"processing.inbox_dir": str(inbox)}).status_code == 200
    r = client.post("/api/documents/inbox").json()
    assert r["imported"] == 1 and len(r["rejected"]) == 1
    assert (inbox / "a.txt").exists()  # Inbox import never moves or deletes source files.
    events = client.get("/api/audit?event=settings.").json()["items"]
    assert events and "processing.inbox_dir" in events[0]["detail"]["keys"]


def test_search_filters_pagination_and_injection(client):
    for n in range(3):
        processed(client, SAMPLE.replace(b"SO-10001", f"SO-1000{n + 5}".encode()), f"o{n}.txt")
    assert client.get("/api/documents?q=scanner").json()["total"] == 3
    assert client.get("/api/documents?q=SO-10006").json()["total"] == 1
    assert client.get("/api/documents?template=invoice").json()["total"] == 0
    assert client.get("/api/documents?status=needs-review&limit=2").json()["total"] == 3
    assert len(client.get("/api/documents?limit=2&offset=2").json()["items"]) == 1
    # Terms are quoted FTS tokens combined with AND: SQL/FTS syntax is treated as data.
    assert client.get("/api/documents?q=zzz%27)%20OR%201=1%20--").json()["total"] == 0
    assert client.get("/api/documents?q=%22%20NEAR(%20*").status_code == 200
    assert client.get("/api/documents?date_from=bad").status_code == 422


def test_archive_and_delete_keep_audit(client):
    d = processed(client)
    path = f"/api/documents/{d['id']}"
    assert client.post(path + "/delete", json={"confirm": d["name"]}).status_code == 409
    client.post(path + "/archive", json={"archived": True})
    assert client.get("/api/documents").json()["total"] == 0
    assert client.get("/api/documents?archived=true").json()["total"] == 1
    assert client.post(path + "/delete", json={"confirm": "wrong"}).status_code == 422
    assert client.post(path + "/delete", json={"confirm": d["name"]}).status_code == 200
    assert client.get(path).status_code == 404
    assert not (svc(client).files / d["id"]).exists()
    events = client.get(f"/api/audit?document={d['id']}").json()["items"]
    assert events[0]["event"] == "document.deleted" and len(events) > 3


def test_exports_csv_safe_and_json(client):
    d = processed(client, SAMPLE.replace(b"Ana Exemplo", b"=HYPERLINK(1)"), "f.txt")
    client.post(f"/api/documents/{d['id']}/review", json=approve_payload(d))
    rows = list(csv.reader(io.StringIO(client.get("/api/export?format=csv").content.decode("utf-8-sig"))))
    assert "'=HYPERLINK(1)" in rows[1]
    records = client.get("/api/export?format=json").json()
    assert records[0]["provenance"]["order_number"] == "confirmed"
    single = client.get(f"/api/documents/{d['id']}/export").json()
    assert single["fields"]["order_number"]["evidence"].startswith("Order No.")
    assert "export.created" in [a["event"] for a in client.get("/api/audit").json()["items"]]


def test_audit_does_not_contain_document_content(client):
    d = processed(client)
    client.post(f"/api/documents/{d['id']}/review", json=approve_payload(d))
    blob = json.dumps(client.get("/api/audit?limit=500").json()["items"])
    for secret in ("Ana Exemplo", "Inspect the synthetic scanner", "SO-10001"):
        assert secret not in blob


def test_backup_restore_and_traversal_rejection(client):
    d = processed(client)
    name = client.post("/api/backups").json()["name"]
    client.post(f"/api/documents/{d['id']}/archive", json={"archived": True})
    client.post(f"/api/documents/{d['id']}/delete", json={"confirm": d["name"]})
    r = client.post(f"/api/backups/{name}/restore")
    assert r.status_code == 200, r.text
    restored = client.get(f"/api/documents/{d['id']}").json()
    assert restored["fields"]["order_number"]["value"] == "SO-10001"
    assert client.get(f"/api/documents/{d['id']}/file").content == SAMPLE
    assert len(client.get("/api/backups").json()) == 2  # Original + safety backup.
    evil = svc(client).backups / "letranix-20260101-000000.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("letranix.db", b"")
        z.writestr("../outside.txt", b"x")
    assert client.post(f"/api/backups/{evil.name}/restore").status_code == 422
    assert client.get("/api/backups/..%2Fletranix.db").status_code == 404


def test_api_boundaries(client):
    assert client.get("/api/documents", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/session", headers={"X-Letranix-Client": ""}).status_code == 403
    assert client.get("/api/session", headers={"Host": "evil.example",
                                               "X-Letranix-Client": "browser"}).status_code == 403
    assert client.post("/api/documents", headers={"Origin": "http://evil.example"}).status_code == 403
    r = client.post("/api/documents", content=b"", headers={"Content-Length": str(60 * 1024 * 1024)})
    assert r.status_code == 413
    assert client.get("/api/documents/not-an-id").status_code == 404
    h = client.get("/api/health").headers
    assert h["X-Content-Type-Options"] == "nosniff" and "frame-ancestors 'none'" in h["Content-Security-Policy"]


def test_migration_from_v01_workspace(tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    (root / "documents").mkdir()
    db = sqlite3.connect(root / "letranix.db")
    from letranix.db import V1

    db.executescript(V1)
    fields = json.dumps({"reference": {"value": "DEMO-1", "evidence": "Reference: DEMO-1",
                                       "ambiguous": False, "confidence": None}})
    db.execute("INSERT INTO documents VALUES('a'||hex(randomblob(15)),'old.txt','text/plain','d1','2026-01-01',"
               "'approved',1,'Reference: DEMO-1','native-text',?)", (fields,))
    doc_id = db.execute("SELECT id FROM documents").fetchone()[0]
    db.execute("INSERT INTO reviews VALUES('r1',?,1,'approved','Old','Checked fully','{}','2026-01-02')", (doc_id,))
    db.execute("INSERT INTO integrations VALUES('i1','r1','{}','2026-01-03')")
    db.execute("INSERT INTO audit(document_id,event,actor,detail,created) VALUES(?,?,?,?,?)",
               (doc_id, "review.approved", "Old", "{}", "2026-01-02"))
    db.commit()
    db.close()
    from letranix.service import Letranix

    s = Letranix(root, start_workers=False)
    try:
        assert s.db.version() == 2
        d = s.get(doc_id)
        assert d["template_id"] == "generic-record" and d["status"] == "approved"
        with s.db.connect() as c:
            assert c.execute("SELECT document_id FROM ledger WHERE review_id='r1'").fetchone()[0] == doc_id
            assert c.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 1
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert s.search("DEMO")["total"] == 1
    finally:
        s.close()
    assert Letranix(root, start_workers=False).db.version() == 2  # Re-opening is a no-op.


def test_offline_operation_without_network(client, monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", deny)
    d = processed(client)
    assert client.post(f"/api/documents/{d['id']}/review", json=approve_payload(d)).status_code == 200


def test_evaluation_shows_measured_gain_without_inventing(tmp_path):
    from letranix.evaluation import run_evaluation

    report = run_evaluation(tmp_path, sizes=(24, 12, 24))
    before, after = report["test_before_learning"], report["test_after_learning"]
    assert after["field_accuracy"] > before["field_accuracy"]
    assert after["invented_values"] == 0
    assert report["splits"] == {"train": 24, "validation": 12, "test": 24}

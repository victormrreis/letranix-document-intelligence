import hashlib
import json
import socket

import pytest
from fastapi.testclient import TestClient

from letranix.app import create_app
from letranix.demo import generate, native_pdf, seed
from letranix.processing import MAX_BYTES, fields_from_text

SAMPLE = b"Reference: DEMO-TEST\nOrganization: Example Works Lab\nCategory: service-order\nDate: 2026-01-15\nDescription: Inspect synthetic scanner.\n"


def client_for(root):
    client = TestClient(create_app(root), base_url="http://127.0.0.1:8795")
    token = client.get("/api/session", headers={"X-Letranix-Client": "browser"}).json()["token"]
    client.headers["Authorization"] = "Bearer " + token
    return client


@pytest.fixture
def client(tmp_path):
    with client_for(tmp_path / "workspace") as c:
        yield c


def imported(client, data=SAMPLE, name="example.txt"):
    r = client.post("/api/documents", files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def processed(client):
    doc_id = imported(client)
    r = client.post(f"/api/documents/{doc_id}/process")
    assert r.status_code == 200, r.text
    return r.json()


def review_payload(d, **overrides):
    data = {
        "version": d["version"],
        "decision": "approved",
        "actor": "Example Reviewer",
        "reason": "Verified all fields against synthetic source",
        "fields": {k: v["value"] for k, v in d["fields"].items()},
    }
    data.update(overrides)
    return data


def test_end_to_end_review_integration_restart_and_original_preserved(tmp_path):
    root = tmp_path / "isolated"
    c = client_for(root)
    d = processed(c)
    payload = review_payload(d)
    payload["fields"]["description"] = "Corrected synthetic description"
    review = c.post(f"/api/documents/{d['id']}/review", json=payload)
    assert review.status_code == 200, review.text
    assert review.json()["integration_executed"] is False
    saved = c.get(f"/api/documents/{d['id']}").json()
    assert saved["fields"]["description"]["value"] == "Inspect synthetic scanner."
    assert (
        json.loads(saved["reviews"][0]["fields"])["description"] == payload["fields"]["description"]
    )
    assert saved["integrations"] == []
    body = {"review_id": review.json()["review_id"], "authorize": True}
    r = c.post(f"/api/documents/{d['id']}/integrate", json=body)
    assert r.status_code == 200
    assert c.post(f"/api/documents/{d['id']}/integrate", json=body).json()["duplicate"]
    c.close()
    with client_for(root) as restarted:
        saved = restarted.get(f"/api/documents/{d['id']}").json()
        assert saved["status"] == "approved"
        assert len(saved["integrations"]) == 1
        assert [a["event"] for a in saved["audit"]] == [
            "document.imported",
            "processing.completed",
            "review.approved",
            "integration.local-demo",
        ]
        downloaded = restarted.get(f"/api/documents/{d['id']}/file")
        assert downloaded.content == SAMPLE
        assert "attachment" in downloaded.headers["content-disposition"]


@pytest.mark.parametrize(
    "data", [b"", b"MZ\x00binary", b"\xff\x00", b"bad\x01text", b"a" * (MAX_BYTES + 1)]
)
def test_invalid_ingestion(client, data):
    assert client.post("/api/documents", files={"file": ("bad", data)}).status_code == 422
    assert client.get("/api/documents").json() == []


def test_upload_is_path_safe_and_deduplicated(client, tmp_path):
    doc_id = imported(client, name="../../outside.txt")
    same = imported(client, name="other.txt")
    assert doc_id == same
    d = client.get(f"/api/documents/{doc_id}").json()
    assert d["name"] == "outside.txt"
    assert len(client.get("/api/documents").json()) == 1


def test_parser_failure_persists_job_and_safe_error(client):
    doc_id = imported(client, b"%PDF-not-a-pdf", "bad.pdf")
    assert client.post(f"/api/documents/{doc_id}/process").status_code == 422
    d = client.get(f"/api/documents/{doc_id}").json()
    assert d["status"] == "error"
    assert d["jobs"][0]["state"] == "failed"
    assert "Traceback" not in d["jobs"][0]["error"]
    assert "processing.failed" in [a["event"] for a in d["audit"]]


@pytest.mark.parametrize(
    "change", ["stale", "date", "category", "missing", "reason", "actor", "extra", "compact-date"]
)
def test_review_validation(client, change):
    d = processed(client)
    data = review_payload(d)
    if change == "stale":
        data["version"] += 1
    elif change == "date":
        data["fields"]["date"] = "2026-02-30"
    elif change == "compact-date":
        data["fields"]["date"] = "20260115"
    elif change == "category":
        data["fields"]["category"] = "invented"
    elif change == "missing":
        data["fields"]["reference"] = ""
    elif change == "reason":
        data["reason"] = "     "
    elif change == "actor":
        data["actor"] = "  "
    elif change == "extra":
        data["fields"]["unknown"] = "no"
    r = client.post(f"/api/documents/{d['id']}/review", json=data)
    assert r.status_code == (409 if change == "stale" else 422)
    assert client.get(f"/api/documents/{d['id']}").json()["reviews"] == []


def test_review_cannot_be_replayed_and_reprocessing_invalidates_approval(client):
    d = processed(client)
    body = review_payload(d)
    path = f"/api/documents/{d['id']}"
    r = client.post(path + "/review", json=body)
    assert r.status_code == 200
    assert client.post(path + "/review", json=body).status_code == 409
    assert (
        client.post(
            path + "/integrate", json={"review_id": r.json()["review_id"], "authorize": False}
        ).status_code
        == 422
    )
    assert client.post(path + "/process").json()["version"] == 2
    assert (
        client.post(
            path + "/integrate", json={"review_id": r.json()["review_id"], "authorize": True}
        ).status_code
        == 409
    )
    assert len(client.get(path).json()["reviews"]) == 1


def test_rejection_and_no_integration(client):
    d = processed(client)
    r = client.post(f"/api/documents/{d['id']}/review", json=review_payload(d, decision="rejected"))
    assert r.status_code == 200
    assert (
        client.post(
            f"/api/documents/{d['id']}/integrate",
            json={"review_id": r.json()["review_id"], "authorize": True},
        ).status_code
        == 409
    )


def test_search_filters_and_sql_payload(client):
    processed(client)
    assert (
        len(
            client.get("/api/documents?q=scanner&category=service-order&status=needs-review").json()
        )
        == 1
    )
    assert client.get("/api/documents?category=administrative-request").json() == []
    assert client.get("/api/documents?q=%27%20OR%201=1--").json() == []


def test_browser_boundaries(client):
    assert client.get("/api/documents", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/session", headers={"X-Letranix-Client": ""}).status_code == 403
    assert (
        client.get(
            "/api/session", headers={"Host": "attacker.example", "X-Letranix-Client": "browser"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/session",
            headers={"Origin": "http://attacker.example", "X-Letranix-Client": "browser"},
        ).status_code
        == 403
    )
    assert client.post("/api/documents", headers={"Origin": "null"}).status_code == 403
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors" in r.headers["Content-Security-Policy"]
    assert "access-control-allow-origin" not in r.headers


def test_oversized_request_rejected_before_parser(client):
    r = client.post("/api/documents", content=b"", headers={"Content-Length": str(MAX_BYTES * 2)})
    assert r.status_code == 413


def test_missing_document_is_404(client):
    assert client.get("/api/documents/unknown").status_code == 404
    assert client.get("/api/documents/unknown/file").status_code == 404


def test_native_pdf_and_ambiguity(client):
    raw = native_pdf(SAMPLE.decode().splitlines())
    doc_id = imported(client, raw, "synthetic.pdf")
    d = client.post(f"/api/documents/{doc_id}/process").json()
    assert d["method"] == "pdf-native"
    assert d["fields"]["reference"]["value"] == "DEMO-TEST"
    f = fields_from_text("Reference: DEMO-A\nReference: DEMO-B")
    assert f["reference"]["ambiguous"]
    assert f["reference"]["confidence"] is None


def test_demo_idempotent_relations_and_binary_manifest(tmp_path):
    data, fixtures = tmp_path / "data", tmp_path / "fixtures"
    assert seed(data, fixtures) == 5
    assert seed(data, fixtures) == 0
    manifest = json.loads((fixtures / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((fixtures / name).read_bytes()).hexdigest() == digest
    with client_for(data) as c:
        rows = c.get("/api/documents").json()
        assert len(rows) == 5
        for d in rows:
            detail = c.get("/api/documents/" + d["id"]).json()
            assert detail["reviews"] == []
            assert detail["integrations"] == []
            assert c.get("/api/documents/" + d["id"] + "/file").status_code == 200
        with c.app.state.store.connect() as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_isolation_without_network_or_source_tree(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Network forbidden in isolated workflow")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.chdir(tmp_path)
    with client_for(tmp_path / "fresh") as c:
        d = processed(c)
        assert d["method"] == "native-text"
        assert c.post(f"/api/documents/{d['id']}/review", json=review_payload(d)).status_code == 200


def test_interrupted_job_recovery(tmp_path):
    root = tmp_path / "recovery"
    c = client_for(root)
    doc_id = imported(c)
    with c.app.state.store.connect() as db:
        db.execute("UPDATE documents SET status='processing' WHERE id=?", (doc_id,))
        db.execute("INSERT INTO jobs VALUES('interrupted',?,'running','2026-01-01','')", (doc_id,))
    c.close()
    with client_for(root) as fresh:
        d = fresh.get(f"/api/documents/{doc_id}").json()
        assert d["status"] == "error"
        assert d["jobs"][0]["state"] == "failed"
        assert fresh.post(f"/api/documents/{doc_id}/process").status_code == 200


@pytest.mark.ocr
def test_real_local_image_ocr(tmp_path, monkeypatch):
    pytest.importorskip("rapidocr_onnxruntime")
    generate(tmp_path / "fixtures")
    # OCR models come from the installed package; network access is forbidden.
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Offline OCR must not connect")),
    )
    with client_for(tmp_path / "ocr-workspace") as c:
        doc_id = imported(
            c, (tmp_path / "fixtures/operational-report.png").read_bytes(), "report.png"
        )
        r = c.post(f"/api/documents/{doc_id}/process")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["method"] == "rapidocr-local"
        assert d["fields"]["reference"]["value"] == "DEMO-002"
        assert d["fields"]["category"]["value"] == "operational-report"

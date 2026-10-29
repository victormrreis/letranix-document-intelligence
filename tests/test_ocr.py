"""Real local OCR on generated documents (skipped when RapidOCR is not installed)."""

import hashlib
import json
import socket

import pytest

from conftest import drain, imported
from letranix.demo import generate

pytestmark = pytest.mark.ocr


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    pytest.importorskip("rapidocr_onnxruntime")
    path = tmp_path_factory.mktemp("fixtures")
    generate(path)
    return path


@pytest.fixture
def offline(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("OCR must run offline")

    monkeypatch.setattr(socket, "create_connection", deny)


def _run(client, fixtures, name):
    doc_id = imported(client, (fixtures / name).read_bytes(), name)
    drain(client)
    return client.get(f"/api/documents/{doc_id}").json()


def test_manifest_matches_generated_bytes(fixtures):
    manifest = json.loads((fixtures / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((fixtures / name).read_bytes()).hexdigest() == digest


def test_skewed_image_ocr_with_boxes_and_preprocessing(client, fixtures, offline):
    d = _run(client, fixtures, "inspection-report.png")
    assert d["status"] == "needs-review", d["jobs"][0]["error"]
    assert d["template_id"] == "inspection-report"
    f = d["fields"]
    assert f["report_id"]["value"] == "IR-3310"
    assert f["result"]["value"] == "pass"
    assert f["date"]["value"] == "2026-02-20"
    assert f["report_id"]["bbox"] and f["report_id"]["ocr_score"] > 0.5
    page = d["pages_detail"][0]
    assert any(s.startswith("deskew") for s in page["steps"])
    assert page["has_image"] and page["width"] > 0
    assert client.get(f"/api/documents/{d['id']}/pages/1/image").headers["content-type"] == "image/png"


def test_scanned_multipage_pdf_is_rendered_and_ocred(client, fixtures, offline):
    d = _run(client, fixtures, "scanned-request.pdf")
    assert d["status"] == "needs-review", d["jobs"][0]["error"]
    assert len(d["pages_detail"]) == 2
    assert all(p["method"] == "ocr-rapidocr-pdf" for p in d["pages_detail"])
    assert d["fields"]["protocol"]["value"] == "AR-5521"
    assert d["fields"]["requester"]["value"] == "Carla Modelo"
    assert d["fields"]["subject"]["page"] == 2


def test_rotated_form_orientation_and_layout(client, fixtures, offline):
    d = _run(client, fixtures, "rotated-field-form.jpg")
    assert any(s.startswith("rotate") for s in d["pages_detail"][0]["steps"])
    d = client.post(f"/api/documents/{d['id']}/template", json={"template_id": "service-order"}).json()
    assert d["fields"]["order_number"]["value"] == "SO-20981"
    assert d["fields"]["priority"]["value"] == "urgent"
    assert d["fields"]["order_number"]["rule"] == "label-below"


def test_native_pdf_table(client, fixtures):
    d = _run(client, fixtures, "invoice.pdf")
    assert d["method"] == "pdf-native" and d["template_id"] == "invoice"
    assert d["fields"]["total"]["value"] == "254.00"
    assert len(d["tables"]["table"]["rows"]) == 3

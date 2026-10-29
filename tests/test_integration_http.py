"""Real HTTP delivery to the fictitious records API running on a loopback port."""

import json
import urllib.request

from conftest import approve_payload, processed, svc


def _approve_and_send(client, endpoint):
    client.patch("/api/settings", json={"integration.adapter": "http-demo",
                                        "integration.endpoint": endpoint + "/records",
                                        "integration.max_attempts": 3})
    d = processed(client)
    rid = client.post(f"/api/documents/{d['id']}/review", json=approve_payload(d)).json()["review_id"]
    r = client.post(f"/api/documents/{d['id']}/integrate", json={"review_id": rid, "authorize": True})
    assert r.status_code == 200
    return d, rid


def _outbox(client):
    return client.get("/api/integrations/outbox").json()[0]


def _make_due(client):
    with svc(client).db.connect() as c:
        c.execute("UPDATE outbox SET next_attempt='2000-01-01'")


def test_delivery_reaches_destination_with_contract(client, destination):
    d, rid = _approve_and_send(client, destination)
    assert svc(client).outbox.run_once()
    entry = _outbox(client)
    assert entry["state"] == "delivered" and entry["attempts"] == 1
    with urllib.request.urlopen(destination + "/records") as r:
        records = json.loads(r.read())
    assert len(records) == 1
    assert records[0]["review_id"] == rid
    assert records[0]["fields"]["order_number"] == "SO-10001"
    shown = client.get("/api/integrations/destination").json()
    assert shown["adapter"] == "http-demo" and shown["records"][0]["id"] == records[0]["id"]


def test_retry_after_outage_and_idempotent_redelivery(client, destination):
    _approve_and_send(client, destination)
    urllib.request.urlopen(urllib.request.Request(destination + "/admin/faults?count=1&status=503",
                                                  method="POST"))
    assert svc(client).outbox.run_once()
    entry = _outbox(client)
    assert entry["state"] == "pending" and "503" in entry["last_error"]
    _make_due(client)
    assert svc(client).outbox.run_once()
    assert _outbox(client)["state"] == "delivered"
    # A crash after delivery but before bookkeeping re-sends: the key prevents a duplicate.
    with svc(client).db.connect() as c:
        c.execute("UPDATE outbox SET state='pending', next_attempt='2000-01-01'")
    assert svc(client).outbox.run_once()
    assert _outbox(client)["response"]["duplicate"] is True
    with urllib.request.urlopen(destination + "/records") as r:
        assert len(json.loads(r.read())) == 1


def test_permanent_rejection_and_manual_retry(client, destination):
    _approve_and_send(client, destination)
    urllib.request.urlopen(urllib.request.Request(destination + "/admin/faults?count=1&status=422",
                                                  method="POST"))
    svc(client).outbox.run_once()
    entry = _outbox(client)
    assert entry["state"] == "failed" and "rejected" in entry["last_error"]
    assert client.post(f"/api/integrations/outbox/{entry['id']}/retry").status_code == 200
    assert svc(client).outbox.run_once()
    assert _outbox(client)["state"] == "delivered"


def test_unavailable_destination_exhausts_attempts(client):
    _approve_and_send(client, "http://127.0.0.1:9")  # Nothing listens on the discard port.
    for _ in range(3):
        _make_due(client)
        svc(client).outbox.run_once()
    entry = _outbox(client)
    assert entry["state"] == "failed" and entry["attempts"] == 3
    assert "unavailable" in entry["last_error"]
    assert client.get("/api/integrations/destination").status_code == 503

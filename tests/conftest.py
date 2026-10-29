import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from letranix.app import create_app

SAMPLE = (
    b"SERVICE ORDER\nOrder No.: SO-10001\nRequested by: Ana Exemplo\nDate: 2026-01-15\n"
    b"Priority: High\nDescription: Inspect the synthetic scanner.\n"
)


def client_for(root, workers=False):
    client = TestClient(create_app(root, start_workers=workers), base_url="http://127.0.0.1:8795")
    token = client.get("/api/session", headers={"X-Letranix-Client": "browser"}).json()["token"]
    client.headers["Authorization"] = "Bearer " + token
    return client


@pytest.fixture
def client(tmp_path):
    with client_for(tmp_path / "workspace") as c:
        yield c


def svc(client):
    return client.app.state.service


def drain(client):
    while svc(client).run_next_job():
        pass


def imported(client, data=SAMPLE, name="order.txt"):
    r = client.post("/api/documents", files={"file": (name, data)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def processed(client, data=SAMPLE, name="order.txt"):
    doc_id = imported(client, data, name)
    drain(client)
    d = client.get(f"/api/documents/{doc_id}").json()
    assert d["status"] == "needs-review", d["jobs"]
    return d


def approve_payload(d, **overrides):
    body = {
        "version": d["version"],
        "decision": "approved",
        "actor": "Example Reviewer",
        "reason": "Verified every field against the synthetic source",
        "fields": {k: v["value"] for k, v in d["fields"].items()},
    }
    body.update(overrides)
    return body


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def destination(tmp_path):
    """The fictitious records API running for real on a loopback port."""
    from letranix.mock_destination import create_destination

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_destination(tmp_path / "dest"), host="127.0.0.1",
                                           port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)

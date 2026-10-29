"""Adapter contract and intentionally local-only demonstration implementation."""

import sqlite3
from typing import Protocol

from .store import now, uid


class IntegrationAdapter(Protocol):
    name: str

    def apply(self, transaction: sqlite3.Connection, review_id: str, payload: str) -> dict:
        """Apply an already reviewed snapshot in the caller's transaction."""
        ...


class LocalDemoAdapter:
    name = "local-demo"

    def apply(self, transaction: sqlite3.Connection, review_id: str, payload: str) -> dict:
        existing = transaction.execute(
            "SELECT id FROM integrations WHERE review_id=?", (review_id,)
        ).fetchone()
        if existing:
            return {"id": existing["id"], "duplicate": True}
        integration_id = uid()
        transaction.execute(
            "INSERT INTO integrations VALUES(?,?,?,?)",
            (integration_id, review_id, payload, now()),
        )
        return {"id": integration_id, "duplicate": False}

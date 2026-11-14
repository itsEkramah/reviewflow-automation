"""FastAPI + SQLite intake, idempotency, review decisions and audit events."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .providers import ProviderError, Triage, configured_provider

STATIC = Path(__file__).parent / "static"


class Intake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=3, max_length=10000)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    expected_version: int = Field(ge=1)
    reviewed_draft: str = Field(min_length=1, max_length=2000)


def create_app(db_path: str | Path | None = None, provider=None) -> FastAPI:
    db_path = Path(db_path or os.environ.get("REVIEWFLOW_DB", ".data/reviewflow.sqlite3"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    provider = provider or configured_provider

    @contextmanager
    def connect():
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tickets (
          id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, digest TEXT NOT NULL,
          message TEXT NOT NULL, triage TEXT NOT NULL, provider TEXT NOT NULL,
          status TEXT NOT NULL, version INTEGER NOT NULL, reviewed_draft TEXT,
          created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL,
          action TEXT NOT NULL, created TEXT NOT NULL);
        """)
    app = FastAPI(title="ReviewFlow Automation", version="1.0.0")

    def record(row):
        data = dict(row)
        data["triage"] = json.loads(data["triage"])
        data.pop("digest")
        return data

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "provider": os.environ.get("REVIEWFLOW_PROVIDER", "demo")}

    @app.get("/api/tickets")
    def list_tickets():
        with connect() as conn:
            rows = conn.execute("SELECT * FROM tickets ORDER BY created DESC LIMIT 100").fetchall()
        return [record(row) for row in rows]

    @app.post("/api/tickets", status_code=201)
    def intake(payload: Intake):
        digest = hashlib.sha256(payload.message.encode()).hexdigest()
        with connect() as conn:
            previous = conn.execute("SELECT * FROM tickets WHERE request_id = ?", (payload.request_id,)).fetchone()
        if previous:
            if previous["digest"] != digest:
                raise HTTPException(409, "This request ID already belongs to a different message.")
            return {**record(previous), "replayed": True}
        try:
            triage, provider_name = provider(payload.message)
            triage = Triage.model_validate(triage)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        now = datetime.now(timezone.utc).isoformat()
        ticket_id = uuid.uuid4().hex
        try:
            with connect() as conn:
                conn.execute("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (ticket_id, payload.request_id, digest, payload.message, triage.model_dump_json(),
                              provider_name, "pending_review", 1, None, now))
                conn.execute("INSERT INTO events(ticket_id, action, created) VALUES (?, ?, ?)", (ticket_id, "queued_for_review", now))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Request ID was queued concurrently; retry with the same payload.") from None
        with connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return {**record(row), "replayed": False}

    @app.post("/api/tickets/{ticket_id}/decision")
    def decide(ticket_id: str, payload: Decision):
        status = "approved" if payload.action == "approve" else "rejected"
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Ticket not found")
            if row["version"] != payload.expected_version or row["status"] != "pending_review":
                raise HTTPException(409, "The ticket has changed or was already reviewed. Refresh the queue.")
            conn.execute("UPDATE tickets SET status = ?, reviewed_draft = ?, version = version + 1 WHERE id = ?",
                         (status, payload.reviewed_draft, ticket_id))
            conn.execute("INSERT INTO events(ticket_id, action, created) VALUES (?, ?, ?)",
                         (ticket_id, status, datetime.now(timezone.utc).isoformat()))
            updated = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return record(updated)

    @app.get("/api/tickets/{ticket_id}/events")
    def events(ticket_id: str):
        with connect() as conn:
            if not conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone():
                raise HTTPException(404, "Ticket not found")
            rows = conn.execute("SELECT event_id, action, created FROM events WHERE ticket_id = ? ORDER BY event_id", (ticket_id,)).fetchall()
        return [dict(row) for row in rows]

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()

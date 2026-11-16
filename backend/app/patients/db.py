"""SQLite tables for patient analytics. All names are prefixed pt_."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from app.core.settings import get_settings

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS pt_file (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    checksum TEXT NOT NULL,
    rows INTEGER NOT NULL DEFAULT 0,
    rows_held_back INTEGER NOT NULL DEFAULT 0,
    period TEXT,
    loaded_at TEXT NOT NULL,
    columns_json TEXT,
    reject_reason TEXT
);
CREATE TABLE IF NOT EXISTS pt_row (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    held_back INTEGER NOT NULL DEFAULT 0,
    hold_reason TEXT,
    vendor_patient_id TEXT,
    event_date TEXT,
    birth_year INTEGER,
    sex TEXT,
    zip3 TEXT,
    prescriber_npi TEXT,
    brand TEXT,
    payer_type TEXT,
    hub_case_id TEXT,
    copay_card_id TEXT,
    pharmacy_name TEXT,
    quantity REAL,
    days_supply INTEGER,
    status TEXT,
    product_code TEXT,
    claim_id TEXT,
    claim_type TEXT
);
CREATE TABLE IF NOT EXISTS pt_record (
    id INTEGER PRIMARY KEY,
    ref TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    vendor_patient_id TEXT NOT NULL,
    hub_case_ids TEXT,
    copay_card_ids TEXT,
    birth_year INTEGER,
    sex TEXT,
    zip3 TEXT,
    prescriber_npi TEXT,
    doctor_id TEXT,
    prescriber_name TEXT,
    brand TEXT,
    payer_type TEXT,
    pharmacy_names TEXT,
    first_date TEXT,
    last_date TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    dates_json TEXT,
    UNIQUE(source, vendor_patient_id)
);
CREATE TABLE IF NOT EXISTS pt_patient (
    id INTEGER PRIMARY KEY,
    daiichi_patient_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    retired_into TEXT
);
CREATE TABLE IF NOT EXISTS pt_link (
    id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    layer TEXT NOT NULL,
    reason TEXT,
    score INTEGER,
    score_items_json TEXT,
    decided_by TEXT,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS pt_review (
    id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL,
    top3_json TEXT,
    ai_reasoning_json TEXT,
    status TEXT NOT NULL,
    resolved_by TEXT,
    resolved_at TEXT,
    target_patient_id TEXT
);
CREATE TABLE IF NOT EXISTS pt_event (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    date TEXT,
    source TEXT,
    record_id INTEGER,
    kind TEXT NOT NULL,
    title TEXT,
    detail TEXT,
    quantity REAL,
    pharmacy TEXT,
    flags_json TEXT
);
CREATE TABLE IF NOT EXISTS pt_summary (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL UNIQUE,
    facts_json TEXT NOT NULL,
    text_json TEXT NOT NULL,
    facts_hash TEXT NOT NULL,
    model TEXT,
    generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pt_run (
    id INTEGER PRIMARY KEY,
    input TEXT,
    rows INTEGER,
    new_patients INTEGER,
    added_to_existing INTEGER,
    review_count INTEGER,
    duration REAL,
    step_log_json TEXT,
    status TEXT,
    started_at TEXT,
    finished_at TEXT,
    result_json TEXT
);
CREATE TABLE IF NOT EXISTS pt_audit (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    actor TEXT,
    action TEXT,
    details TEXT
);
CREATE INDEX IF NOT EXISTS ix_pt_row_file ON pt_row(file_id);
CREATE INDEX IF NOT EXISTS ix_pt_row_vendor ON pt_row(source, vendor_patient_id);
CREATE INDEX IF NOT EXISTS ix_pt_link_patient ON pt_link(patient_id);
CREATE INDEX IF NOT EXISTS ix_pt_link_record ON pt_link(record_id);
CREATE INDEX IF NOT EXISTS ix_pt_event_patient ON pt_event(patient_id);
"""


def db_path() -> Path:
    return get_settings().runtime_path / "pt_patients.sqlite"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def ensure_schema() -> None:
    with _LOCK:
        conn = connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


class DB:
    def __init__(self) -> None:
        ensure_schema()
        self.conn = connect()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DB":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, tuple(params)))

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def commit(self) -> None:
        self.conn.commit()

    def table_empty(self, name: str) -> bool:
        row = self.one(f"SELECT COUNT(*) AS n FROM {name}")
        return int(row["n"]) == 0

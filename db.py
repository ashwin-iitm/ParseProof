"""
db.py — SQLite storage for the product (server.py): documents, templates, runs, settings.

One connection per call keeps it safe to use from the background job threads.
"""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from config import DATA_DIR

DB_PATH = DATA_DIR / "parseproof.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    content_type TEXT,
    size INTEGER,
    pages INTEGER,
    sha TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    fields TEXT NOT NULL,
    rules TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    template_id TEXT,
    template_name TEXT,
    template TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT DEFAULT '',
    progress REAL DEFAULT 0,
    error TEXT,
    report TEXT,
    review TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    finished_at REAL,
    approved_at REAL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    template_id TEXT,
    template_name TEXT,
    created_at REAL NOT NULL
);
"""

JSON_COLUMNS = {"fields", "rules", "template", "report", "review"}


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    # The product was called Attest, then AdoVerse; carry the newest old database over once
    for old in ("adoverse.db", "attest.db"):
        if DB_PATH.exists() or not (DATA_DIR / old).exists():
            continue
        for suffix in ("", "-wal", "-shm"):
            if (DATA_DIR / f"{old}{suffix}").exists():
                (DATA_DIR / f"{old}{suffix}").rename(DATA_DIR / f"{DB_PATH.name}{suffix}")
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        # Added after the first release: runs started together belong to a batch
        if "batch_id" not in {r["name"] for r in c.execute("PRAGMA table_info(runs)")}:
            c.execute("ALTER TABLE runs ADD COLUMN batch_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS runs_batch ON runs (batch_id)")


def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    for k in JSON_COLUMNS & out.keys():
        if out[k] is not None:
            out[k] = json.loads(out[k])
    return out


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _insert(table: str, values: Dict[str, Any]) -> None:
    values = {k: json.dumps(v) if k in JSON_COLUMNS and v is not None else v for k, v in values.items()}
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    with connect() as c:
        c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))


def _update(table: str, row_id: str, values: Dict[str, Any]) -> None:
    values = {k: json.dumps(v) if k in JSON_COLUMNS and v is not None else v for k, v in values.items()}
    sets = ", ".join(f"{k} = ?" for k in values)
    with connect() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), row_id])


def _get(table: str, row_id: str) -> Optional[Dict[str, Any]]:
    with connect() as c:
        return _row(c.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone())


def _delete(table: str, row_id: str) -> None:
    with connect() as c:
        c.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))


# -----------------------------
# DOCUMENTS
# -----------------------------
def add_document(**values) -> Dict[str, Any]:
    doc = {"id": values.pop("id", None) or new_id(), "created_at": time.time(), **values}
    _insert("documents", doc)
    return doc


def get_document(doc_id: str):
    return _get("documents", doc_id)


def list_documents() -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute("""
            SELECT d.*, COUNT(r.id) AS run_count, MAX(r.created_at) AS last_run_at
            FROM documents d LEFT JOIN runs r ON r.document_id = d.id
            GROUP BY d.id ORDER BY d.created_at DESC""").fetchall()
    return [_row(r) for r in rows]


def delete_document(doc_id: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM runs WHERE document_id = ?", (doc_id,))
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


# -----------------------------
# TEMPLATES
# -----------------------------
def add_template(name: str, description: str, fields: list, rules: list, template_id: Optional[str] = None):
    now = time.time()
    tpl = {"id": template_id or new_id(), "name": name, "description": description, "fields": fields,
           "rules": rules, "created_at": now, "updated_at": now}
    _insert("templates", tpl)
    return tpl


def update_template(template_id: str, **values) -> None:
    _update("templates", template_id, {**values, "updated_at": time.time()})


def get_template(template_id: str):
    return _get("templates", template_id)


def list_templates() -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute("""
            SELECT t.*, COUNT(r.id) AS run_count
            FROM templates t LEFT JOIN runs r ON r.template_id = t.id
            GROUP BY t.id ORDER BY t.name COLLATE NOCASE""").fetchall()
    return [_row(r) for r in rows]


def delete_template(template_id: str) -> None:
    _delete("templates", template_id)


def template_count() -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM templates").fetchone()[0]


# -----------------------------
# RUNS
# -----------------------------
def add_run(document_id: str, template: Dict[str, Any], batch_id: Optional[str] = None) -> Dict[str, Any]:
    run = {"id": new_id(), "document_id": document_id, "template_id": template["id"],
           "template_name": template["name"],
           "template": {"fields": template["fields"], "rules": template["rules"]},
           "status": "queued", "stage": "Queued", "progress": 0, "review": {}, "created_at": time.time(),
           "batch_id": batch_id}
    _insert("runs", run)
    return run


def update_run(run_id: str, **values) -> None:
    _update("runs", run_id, values)


def get_run(run_id: str):
    with connect() as c:
        return _row(c.execute("""
            SELECT r.*, d.filename, d.pages, d.content_type
            FROM runs r JOIN documents d ON d.id = r.document_id WHERE r.id = ?""", (run_id,)).fetchone())


def list_runs(batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
    where, args = ("WHERE r.batch_id = ?", (batch_id,)) if batch_id else ("", ())
    with connect() as c:
        rows = c.execute(f"""
            SELECT r.id, r.document_id, r.template_id, r.template_name, r.status, r.stage, r.progress,
                   r.error, r.created_at, r.finished_at, r.approved_at, r.review, r.batch_id,
                   json_extract(r.report, '$.summary') AS summary,
                   json_extract(r.report, '$.seconds') AS seconds,
                   json_extract(r.report, '$.usage.total') AS tokens,
                   d.filename, d.pages, b.name AS batch_name
            FROM runs r JOIN documents d ON d.id = r.document_id
            LEFT JOIN batches b ON b.id = r.batch_id
            {where}
            ORDER BY r.created_at DESC""", args).fetchall()
    out = []
    for r in rows:
        item = _row(r)
        item["summary"] = json.loads(item["summary"]) if item.get("summary") else None
        out.append(item)
    return out


def get_runs(run_ids: List[str]) -> List[Dict[str, Any]]:
    """Runs with their reports (minus page texts, which only the review screen needs), in the order given."""
    found: Dict[str, Dict[str, Any]] = {}
    with connect() as c:
        for start in range(0, len(run_ids), 500):  # SQLite caps the number of query parameters
            chunk = run_ids[start:start + 500]
            rows = c.execute(f"""
                SELECT r.id, r.document_id, r.template_id, r.template_name, r.template, r.status, r.stage,
                       r.progress, r.error, json_remove(r.report, '$.page_texts') AS report, r.review,
                       r.created_at, r.finished_at, r.approved_at, r.batch_id, d.filename, d.pages, d.content_type
                FROM runs r JOIN documents d ON d.id = r.document_id
                WHERE r.id IN ({", ".join("?" for _ in chunk)})""", chunk).fetchall()
            found.update({r["id"]: _row(r) for r in rows})
    return [found[i] for i in run_ids if i in found]


def delete_run(run_id: str) -> None:
    _delete("runs", run_id)


# -----------------------------
# BATCHES
# -----------------------------
def add_batch(name: str, template: Dict[str, Any]) -> Dict[str, Any]:
    batch = {"id": new_id(), "name": name, "template_id": template["id"], "template_name": template["name"],
             "created_at": time.time()}
    _insert("batches", batch)
    return batch


def get_batch(batch_id: str):
    return _get("batches", batch_id)


def list_batches() -> List[Dict[str, Any]]:
    with connect() as c:
        rows = c.execute("""
            SELECT b.*,
                   COUNT(r.id) AS total,
                   SUM(r.status = 'done') AS done,
                   SUM(r.status = 'failed') AS failed,
                   SUM(r.status IN ('queued', 'running')) AS active,
                   SUM(r.approved_at IS NOT NULL) AS approved,
                   SUM(COALESCE(json_extract(r.report, '$.summary.PASS'), 0)) AS pass,
                   SUM(COALESCE(json_extract(r.report, '$.summary.FAIL'), 0)) AS fail,
                   SUM(COALESCE(json_extract(r.report, '$.summary.REVIEW'), 0)) AS review,
                   SUM(COALESCE(r.progress, 0)) AS progress_sum
            FROM batches b LEFT JOIN runs r ON r.batch_id = b.id
            GROUP BY b.id ORDER BY b.created_at DESC""").fetchall()
    out = []
    for r in rows:
        item = dict(r)
        for k in ("done", "failed", "active", "approved", "pass", "fail", "review"):
            item[k] = item[k] or 0
        item["progress"] = (item.pop("progress_sum") or 0) / item["total"] if item["total"] else 0
        out.append(item)
    return out


def delete_batch(batch_id: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM runs WHERE batch_id = ?", (batch_id,))
        c.execute("DELETE FROM batches WHERE id = ?", (batch_id,))


def fail_interrupted_runs() -> None:
    with connect() as c:
        c.execute("""UPDATE runs SET status = 'failed', error = 'Interrupted: the server was restarted.'
                     WHERE status IN ('queued', 'running')""")


# -----------------------------
# SETTINGS
# -----------------------------
def get_settings() -> Dict[str, str]:
    with connect() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings").fetchall()}


def set_setting(key: str, value: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

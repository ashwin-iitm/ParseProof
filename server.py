"""
server.py — ParseProof: document extraction with evidence-checked QC.

  Extraction: OpenAI native document input (openai_extract.py)
  QC:         per-field agents over the hybrid RAG page index (agents.py, doc_index.py)
  Storage:    SQLite + files under data/ (db.py)
  UI:         React app in web/, built to web/dist and served from here

Run:  python -m uvicorn server:app --port 8010      (or double-click start.bat)
"""

import json
import mimetypes
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
from dotenv import set_key
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import exports
from agents import default_models, file_hash, stream_pipeline
from config import BASE_DIR, DOCUMENT_DIR, ENV_FILE, logger
from openai_extract import check_connection, draft_template
from text_processing import extract_text_from_file
from templates_seed import STARTER_TEMPLATES

ALLOWED_TYPES = {".pdf", ".docx", ".txt", ".csv", ".xls", ".xlsx"}
MAX_UPLOAD_MB = 100
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
WEB_DIST = BASE_DIR / "web" / "dist"

# Windows registry often maps .js to text/plain, which browsers refuse for module scripts
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")

app = FastAPI(title="ParseProof", docs_url="/api/docs", openapi_url="/api/openapi.json")
# Documents processed at the same time; each one also checks up to AGENT_MAX_CONCURRENCY fields in parallel
RUN_CONCURRENCY = int(os.getenv("RUN_CONCURRENCY", 3))
MAX_BATCH_DOCUMENTS = 500
jobs = ThreadPoolExecutor(max_workers=RUN_CONCURRENCY, thread_name_prefix="run")


@app.on_event("startup")
def startup() -> None:
    db.init()
    saved_prices = db.get_settings().get("prices")
    if saved_prices:
        config.set_prices(json.loads(saved_prices))
    db.fail_interrupted_runs()
    # Add starter templates once each, so new ones appear but deleted ones don't come back
    seeded = set(json.loads(db.get_settings().get("seeded_templates") or "[]"))
    if not seeded:
        seeded = {t["name"] for t in db.list_templates()}
    existing = {t["name"] for t in db.list_templates()}
    for t in STARTER_TEMPLATES:
        if t["name"] not in seeded and t["name"] not in existing:
            db.add_template(t["name"], t["description"], t["fields"], t["rules"])
        seeded.add(t["name"])
    db.set_setting("seeded_templates", json.dumps(sorted(seeded)))


# -----------------------------
# SETTINGS
# -----------------------------
def current_models() -> Dict[str, str]:
    saved = db.get_settings()
    defaults = default_models()
    return {k: saved.get(f"{k}_model") or v for k, v in defaults.items()}


def key_configured() -> bool:
    return bool(config.OPENAI_API_KEY)


class PriceIn(BaseModel):
    model: str
    input: float
    output: float


class SettingsIn(BaseModel):
    openai_api_key: Optional[str] = None
    extract_model: Optional[str] = None
    qc_model: Optional[str] = None
    ocr_model: Optional[str] = None
    prices: Optional[List[PriceIn]] = None
    reset_prices: Optional[bool] = None


def price_rows(prices: Dict[str, dict]) -> List[Dict[str, Any]]:
    """Chat models first (the ones you pick below), then the embedding model and the local reranker."""
    def kind(name: str) -> str:
        return "local" if name in config.LOCAL_MODELS else "embedding" if name == config.EMBED_MODEL else "chat"
    rows = [{"model": k, "input": v["input"], "output": v["output"], "kind": kind(k)} for k, v in prices.items()]
    return sorted(rows, key=lambda r: ({"chat": 0, "embedding": 1, "local": 2}[r["kind"]], r["model"]))


@app.get("/api/settings")
def get_settings():
    key = config.OPENAI_API_KEY or ""
    return {
        "openai_key_set": key_configured(),
        "openai_key_hint": f"{key[:7]}…{key[-4:]}" if len(key) > 12 else "",
        "models": current_models(),
        "defaults": default_models(),
        "prices": price_rows(config.PRICES),
        "default_prices": price_rows(config.DEFAULT_PRICES),
        "prices_source": config.PRICES_SOURCE,
    }


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    if body.openai_api_key is not None:
        key = body.openai_api_key.strip()
        if not key.startswith("sk-"):
            raise HTTPException(400, "That doesn't look like an OpenAI API key (it should start with sk-).")
        set_key(str(ENV_FILE), "OPENAI_API_KEY", key)
        config.set_openai_key(key)
    for name in ("extract", "qc", "ocr"):
        value = getattr(body, f"{name}_model")
        if value is not None:
            db.set_setting(f"{name}_model", value.strip())
    if body.reset_prices:
        db.set_setting("prices", "")
        config.set_prices({k: v for k, v in config.DEFAULT_PRICES.items()}, edited=False)
    elif body.prices is not None:
        prices: Dict[str, dict] = {}
        for p in body.prices:
            name = p.model.strip()
            if not name:
                raise HTTPException(400, "Every price row needs a model name.")
            if name in prices:
                raise HTTPException(400, f"{name} is listed twice.")
            if p.input < 0 or p.output < 0:
                raise HTTPException(400, f"Prices for {name} can't be negative.")
            prices[name] = {"input": p.input, "output": p.output}
        db.set_setting("prices", json.dumps(prices))
        config.set_prices(prices)
    return get_settings()


@app.post("/api/settings/test")
def test_settings():
    if not key_configured():
        return {"ok": False, "error": "No API key is set."}
    return check_connection(current_models()["extract"])


# -----------------------------
# DOCUMENTS
# -----------------------------
@app.post("/api/documents")
def upload_document(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext or 'none'}'. Use PDF, Word, Excel, CSV or text.")
    doc_id = db.new_id()
    path = DOCUMENT_DIR / f"{doc_id}{ext}"
    with open(path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    size = path.stat().st_size
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        path.unlink(missing_ok=True)
        raise HTTPException(400, f"File is larger than {MAX_UPLOAD_MB} MB.")
    pages = None
    if ext == ".pdf":
        try:
            with fitz.open(path) as pdf:
                locked = pdf.needs_pass and not pdf.authenticate("")
                pages = pdf.page_count
        except Exception:
            path.unlink(missing_ok=True)
            raise HTTPException(400, "This PDF could not be opened. It may be damaged or password-protected.")
        if locked or not pages:
            path.unlink(missing_ok=True)
            raise HTTPException(400, "This PDF is password-protected. Open it, save an unlocked copy "
                                     "(for example Print → Save as PDF), and upload that copy.")
    doc = db.add_document(id=doc_id, filename=file.filename, path=str(path), size=size, pages=pages, sha=file_hash(path),
                          content_type=mimetypes.guess_type(file.filename)[0] or "application/octet-stream")
    return doc


@app.get("/api/documents")
def list_documents():
    return db.list_documents()


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: str):
    doc = db.get_document(doc_id)
    if not doc or not Path(doc["path"]).exists():
        raise HTTPException(404, "Document not found")
    return FileResponse(doc["path"], media_type=doc["content_type"], filename=doc["filename"],
                        content_disposition_type="inline")


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    Path(doc["path"]).unlink(missing_ok=True)
    db.delete_document(doc_id)
    return {"ok": True}


# -----------------------------
# TEMPLATES
# -----------------------------
class FieldIn(BaseModel):
    name: str
    label: str = ""
    description: str = ""
    type: str = "string"
    required: bool = False


class RuleIn(BaseModel):
    type: str = "sum"
    fields: List[str]
    equals: str
    tolerance: float = 0.01


class TemplateIn(BaseModel):
    name: str
    description: str = ""
    fields: List[FieldIn]
    rules: List[RuleIn] = []


def validate_template(body: TemplateIn) -> None:
    if not body.name.strip():
        raise HTTPException(400, "Template name is required.")
    if not body.fields:
        raise HTTPException(400, "Add at least one field.")
    names = [f.name for f in body.fields]
    for n in names:
        if not FIELD_NAME.match(n):
            raise HTTPException(400, f"Field key '{n}' must be lowercase letters, numbers and underscores, "
                                     "starting with a letter.")
    if len(set(names)) != len(names):
        raise HTTPException(400, "Field keys must be unique.")
    for f in body.fields:
        if f.type not in ("string", "number", "date"):
            raise HTTPException(400, f"Unknown type '{f.type}' for field '{f.name}'.")
    for r in body.rules:
        missing = [n for n in r.fields + [r.equals] if n not in names]
        if missing:
            raise HTTPException(400, f"Rule refers to unknown field(s): {', '.join(missing)}.")


class DraftIn(BaseModel):
    prompt: str = ""
    document_id: Optional[str] = None


def clean_draft(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Make an AI draft valid: proper keys, no duplicates, rules only over existing number fields."""
    fields, seen = [], set()
    for f in raw.get("fields", []):
        key = re.sub(r"[^a-z0-9_]+", "_", (f.get("name") or f.get("label") or "").lower()).strip("_")[:64]
        if key and not key[0].isalpha():
            key = f"f_{key}"[:64]
        if not key or key in seen:
            continue
        seen.add(key)
        fields.append({"name": key, "label": (f.get("label") or "").strip(), "description": (f.get("description") or "").strip(),
                       "type": f.get("type") if f.get("type") in ("string", "number", "date") else "string",
                       "required": bool(f.get("required"))})
    numbers = {f["name"] for f in fields if f["type"] == "number"}
    rules = [{"type": "sum", "fields": r["fields"], "equals": r["equals"], "tolerance": 0.01}
             for r in raw.get("rules", [])
             if r.get("fields") and set(r["fields"]) <= numbers and r.get("equals") in numbers
             and r["equals"] not in r["fields"]]
    return {"name": (raw.get("name") or "Untitled template").strip(), "description": (raw.get("description") or "").strip(),
            "fields": fields, "rules": rules}


@app.post("/api/templates/draft")
def draft_template_endpoint(body: DraftIn):
    """Drafts a template with AI. Nothing is saved; the editor shows it for review."""
    if not key_configured():
        raise HTTPException(400, "Add your OpenAI API key in Settings first.")
    if not body.prompt.strip() and not body.document_id:
        raise HTTPException(400, "Describe what to extract, or attach a sample document.")
    sample, sample_pages = None, None
    if body.document_id:
        doc = db.get_document(body.document_id)
        if not doc:
            raise HTTPException(404, "Document not found")
        sample = Path(doc["path"])
        if sample.suffix.lower() != ".pdf":
            sample_pages = extract_text_from_file(sample)
    try:
        raw = draft_template(body.prompt, current_models()["extract"], sample, sample_pages)
    except Exception as e:
        logger.exception("Template drafting failed")
        raise HTTPException(502, f"The model could not draft a template: {str(e)[:300]}")
    draft = clean_draft(raw)
    if not draft["fields"]:
        raise HTTPException(502, "The model returned no usable fields. Try describing the fields you need.")
    return draft


@app.get("/api/templates")
def list_templates():
    return db.list_templates()


@app.get("/api/templates/{template_id}")
def get_template(template_id: str):
    tpl = db.get_template(template_id)
    if not tpl:
        raise HTTPException(404, "Template not found")
    return tpl


@app.post("/api/templates")
def create_template(body: TemplateIn):
    validate_template(body)
    return db.add_template(body.name.strip(), body.description.strip(),
                           [f.model_dump() for f in body.fields], [r.model_dump() for r in body.rules])


@app.put("/api/templates/{template_id}")
def update_template(template_id: str, body: TemplateIn):
    if not db.get_template(template_id):
        raise HTTPException(404, "Template not found")
    validate_template(body)
    db.update_template(template_id, name=body.name.strip(), description=body.description.strip(),
                       fields=[f.model_dump() for f in body.fields], rules=[r.model_dump() for r in body.rules])
    return db.get_template(template_id)


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str):
    db.delete_template(template_id)
    return {"ok": True}


# -----------------------------
# RUNS
# -----------------------------
def execute_run(run_id: str) -> None:
    run = db.get_run(run_id)
    doc = db.get_document(run["document_id"])
    db.update_run(run_id, status="running", stage="Reading document", progress=0.02)
    try:
        for event in stream_pipeline(doc["path"], run["template"], models=current_models()):
            if "report" in event:
                db.update_run(run_id, status="done", stage="Complete", progress=1, report=event["report"],
                              finished_at=time.time())
            else:
                db.update_run(run_id, stage=event["stage"], progress=round(event["progress"], 3))
    except Exception as e:
        logger.exception("Run %s failed", run_id)
        message = str(e)
        if "api_key" in message.lower() or "401" in message:
            message = "OpenAI rejected the API key. Check it in Settings."
        db.update_run(run_id, status="failed", error=message[:1000], finished_at=time.time())


def start_run(document_id: str, template_id: str, batch_id: Optional[str] = None,
              template: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not key_configured():
        raise HTTPException(400, "Add your OpenAI API key in Settings first.")
    if not db.get_document(document_id):
        raise HTTPException(404, "Document not found")
    tpl = template or db.get_template(template_id)
    if not tpl:
        raise HTTPException(404, "Template not found")
    run = db.add_run(document_id, tpl, batch_id)
    jobs.submit(execute_run, run["id"])
    return run


class RunIn(BaseModel):
    document_id: str
    template_id: str


@app.post("/api/runs")
def create_run(body: RunIn):
    return start_run(body.document_id, body.template_id)


@app.get("/api/runs")
def list_runs():
    runs = db.list_runs()
    for r in runs:
        usage = r.pop("usage", None)
        r["cost_usd"] = config.usage_cost(usage)["cost_usd"] if usage else None
    return runs


def resolved(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Final value per field: the reviewer's decision if any, otherwise the QC result."""
    keys = ("field", "label", "value", "status", "reviewed", "source", "page", "evidence")
    return [{k: r[k] for k in keys} for r in exports.field_rows(run)] if run.get("report") else []


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    run["resolved"] = resolved(run)
    return slim(run)


def slim(run: Dict[str, Any]) -> Dict[str, Any]:
    """The review screen polls this, so leave out what it doesn't draw: page text for PDFs (the
    viewer renders the file itself) and the QC requests (loaded per field, on demand)."""
    report = run.get("report")
    if not report:
        return run
    is_pdf = run["filename"].lower().endswith(".pdf")
    results = [{**{k: v for k, v in r.items() if k != "qc_calls"}, "qc_call_count": len(r.get("qc_calls") or [])}
               for r in report.get("results", [])]
    run["report"] = {**report, "results": results, "page_texts": {} if is_pdf else report.get("page_texts", {})}
    if report.get("usage"):
        run["report"]["usage"] = config.usage_cost(report["usage"])
    return run


@app.get("/api/runs/{run_id}/qc-calls/{field}")
def qc_calls(run_id: str, field: str):
    run = db.get_run(run_id)
    result = next((r for r in ((run or {}).get("report") or {}).get("results", []) if r["field"] == field), None)
    if not result:
        raise HTTPException(404, "Field not found in this run")
    return result.get("qc_calls") or []


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    db.delete_run(run_id)
    return {"ok": True}


@app.post("/api/runs/{run_id}/rerun")
def rerun(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return start_run(run["document_id"], run["template_id"], run.get("batch_id"))


class ReviewIn(BaseModel):
    field: str
    value: Optional[str] = None
    source: str = "manual"  # extracted | verified | manual
    reset: bool = False


@app.put("/api/runs/{run_id}/review")
def review_field(run_id: str, body: ReviewIn):
    run = db.get_run(run_id)
    if not run or run["status"] != "done":
        raise HTTPException(400, "Only completed runs can be reviewed.")
    if run["approved_at"]:
        raise HTTPException(400, "This run is approved. Reopen it to make changes.")
    review = dict(run["review"])
    if body.reset:
        review.pop(body.field, None)
    else:
        review[body.field] = {"value": body.value, "source": body.source, "at": time.time()}
    db.update_run(run_id, review=review)
    return get_run(run_id)


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: str):
    run = db.get_run(run_id)
    if not run or run["status"] != "done":
        raise HTTPException(400, "Only completed runs can be approved.")
    db.update_run(run_id, approved_at=time.time())
    return get_run(run_id)


@app.post("/api/runs/{run_id}/reopen")
def reopen(run_id: str):
    db.update_run(run_id, approved_at=None)
    return get_run(run_id)


@app.get("/api/runs/{run_id}/export")
def export_run(run_id: str, format: str = "json"):
    run = db.get_run(run_id)
    if not run or run["status"] != "done":
        raise HTTPException(400, "Only completed runs can be exported.")
    if format in ("xlsx", "csv_detail", "csv_summary"):
        return export(runs=run_id, format="csv" if format.startswith("csv") else format,
                      layout="detail" if format == "csv_detail" else "summary_qc")
    rows = resolved(run)
    stem = Path(run["filename"]).stem
    if format == "csv":
        return export(runs=run_id, format="csv", layout="detail", headers="keys")
    payload = {
        "document": run["filename"],
        "template": run["template_name"],
        "approved": bool(run["approved_at"]),
        "data": {r["field"]: r["value"] for r in rows},
        "fields": rows,
    }
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})


# -----------------------------
# BATCHES (many documents, one template)
# -----------------------------
class BatchIn(BaseModel):
    template_id: str
    document_ids: List[str]
    name: str = ""


@app.post("/api/batches")
def create_batch(body: BatchIn):
    if not key_configured():
        raise HTTPException(400, "Add your OpenAI API key in Settings first.")
    ids = list(dict.fromkeys(body.document_ids))  # keep order, drop repeats
    if not ids:
        raise HTTPException(400, "Choose at least one document.")
    if len(ids) > MAX_BATCH_DOCUMENTS:
        raise HTTPException(400, f"A batch can hold up to {MAX_BATCH_DOCUMENTS} documents.")
    missing = [i for i in ids if not db.get_document(i)]
    if missing:
        raise HTTPException(404, f"{len(missing)} document(s) were not found. Upload them again.")
    tpl = db.get_template(body.template_id)
    if not tpl:
        raise HTTPException(404, "Template not found")
    name = body.name.strip() or f"{tpl['name']} · {datetime.now().strftime('%d %b %Y %H:%M')}"
    batch = db.add_batch(name, tpl)
    for doc_id in ids:
        start_run(doc_id, tpl["id"], batch["id"], tpl)
    return batch_detail(batch["id"])


@app.get("/api/batches")
def list_batches():
    return db.list_batches()


@app.get("/api/batches/{batch_id}")
def batch_detail(batch_id: str):
    batch = next((b for b in db.list_batches() if b["id"] == batch_id), None)
    if not batch:
        raise HTTPException(404, "Batch not found")
    runs = db.get_runs([r["id"] for r in db.list_runs(batch_id)][::-1])  # upload order
    tpl = db.get_template(batch["template_id"]) if batch["template_id"] else None
    fields = runs[0]["template"]["fields"] if runs else (tpl["fields"] if tpl else [])
    rows = []
    for run in runs:
        cells = exports.field_rows(run) if run["status"] == "done" else []
        rows.append({
            "run_id": run["id"], "document_id": run["document_id"], "filename": run["filename"],
            "pages": run["pages"], "status": run["status"], "stage": run["stage"], "progress": run["progress"],
            "error": run["error"], "approved_at": run["approved_at"],
            "summary": (run.get("report") or {}).get("summary"),
            "open_issues": sum(1 for c in cells if c["open"]),
            "cells": {c["field"]: {"value": c["value"], "status": c["status"], "reviewed": c["reviewed"],
                                   "source": c["source"]} for c in cells},
        })
    return {**batch, "fields": fields, "rows": rows}


@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str):
    db.delete_batch(batch_id)
    return {"ok": True}


@app.post("/api/batches/{batch_id}/approve-clean")
def approve_clean(batch_id: str):
    """Approve every finished document in the batch that has no open mismatches or reviews."""
    approved = 0
    for run in db.get_runs([r["id"] for r in db.list_runs(batch_id)]):
        if run["status"] == "done" and not run["approved_at"] and \
                not any(r["open"] for r in exports.field_rows(run)):
            db.update_run(run["id"], approved_at=time.time())
            approved += 1
    return {"approved": approved, "batch": batch_detail(batch_id)}


@app.post("/api/batches/{batch_id}/retry-failed")
def retry_failed(batch_id: str):
    failed = [r for r in db.list_runs(batch_id) if r["status"] == "failed"]
    for run in failed:
        start_run(run["document_id"], run["template_id"], batch_id)
        db.delete_run(run["id"])
    return {"retried": len(failed), "batch": batch_detail(batch_id)}


# -----------------------------
# EXPORT (any set of runs, as a table)
# -----------------------------
@app.get("/api/export")
def export(batch: Optional[str] = None, runs: Optional[str] = None, format: str = "xlsx",
           layout: str = "summary", headers: str = "labels", approved_only: bool = False):
    """
    format:  xlsx (workbook: data, QC status, QC detail, runs, key) | csv | json
    layout:  csv only. summary = one row per document; summary_qc = plus a QC column per field;
             detail = one row per field per document
    headers: labels (field names as people read them) | keys (snake_case, for loading into other systems)
    """
    if format not in ("xlsx", "csv", "json") or layout not in ("summary", "summary_qc", "detail"):
        raise HTTPException(400, "Unknown export format or layout.")
    if batch:
        b = db.get_batch(batch)
        if not b:
            raise HTTPException(404, "Batch not found")
        ids, title = [r["id"] for r in db.list_runs(batch)][::-1], b["name"]
    elif runs:
        ids = [i for i in runs.split(",") if i]
        title = ""
    else:
        raise HTTPException(400, "Choose a batch or runs to export.")
    selected = db.get_runs(ids)
    if approved_only:
        selected = [r for r in selected if r["approved_at"]]
    if not selected:
        raise HTTPException(400, "Nothing to export. No approved documents match." if approved_only
                            else "Nothing to export.")
    batch_names = {b["id"]: b["name"] for b in db.list_batches()}
    for r in selected:
        r["batch_name"] = batch_names.get(r.get("batch_id"))
    if not title:
        title = Path(selected[0]["filename"]).stem if len(selected) == 1 else \
            f"ParseProof export {datetime.now().strftime('%Y-%m-%d %H%M')}"
    stem = exports.filename_for(title) + ("-approved" if approved_only else "")
    keys = headers == "keys"

    if format == "xlsx":
        body, media, ext = exports.to_xlsx(selected, keys, title), \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    elif format == "csv":
        # BOM so Excel opens accented text and currency symbols correctly
        body, media, ext = "﻿" + exports.to_csv(selected, layout, keys), "text/csv; charset=utf-8", "csv"
        stem += "-detail" if layout == "detail" else ""
    else:
        body, media, ext = exports.to_json(selected), "application/json", "json"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{stem}.{ext}"'})


# -----------------------------
# WEB APP
# -----------------------------
if (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    target = WEB_DIST / path
    if path and target.is_file():
        return FileResponse(target)
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<p>The web app is not built yet. Run <code>npm run build</code> in web/.</p>", 503)

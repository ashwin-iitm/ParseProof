"""
exports.py — turns finished runs into tables for Excel, CSV and JSON.

Two shapes, both used by server.py:
  data table  one row per document, one column per template field (the reviewer's value if the
              field was resolved, otherwise the QC result)
  QC detail   one row per field per document, with the extracted value, the verified value,
              the evidence page and quote, and what the reviewer decided

The Excel workbook holds both plus an evidence sheet (a picture of the page each value came from,
with the quote highlighted), a QC status grid, a run log and a key to the colours.
"""

import csv
import io
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from config import usage_cost
from evidence_pictures import Pictures

STATUS_LABEL = {"PASS": "Verified", "FAIL": "Mismatch", "REVIEW": "Needs review", "ABSENT": "Not in document",
                "NOT_CHECKED": "Not checked"}
SOURCE_LABEL = {"extracted": "Extracted", "verified": "QC corrected", "manual": "Edited by reviewer"}
RUN_STATUS_LABEL = {"done": "Complete", "failed": "Failed", "queued": "Queued", "running": "Running"}

FILL = {
    "header": PatternFill("solid", fgColor="1F2937"),
    "FAIL": PatternFill("solid", fgColor="FBE3E4"),
    "REVIEW": PatternFill("solid", fgColor="FDF0D5"),
    "resolved": PatternFill("solid", fgColor="E3ECFB"),
    "PASS": PatternFill("solid", fgColor="E6F4EA"),
    "muted": PatternFill("solid", fgColor="F1F3F5"),
}
HEADER_FONT = Font(bold=True, color="FFFFFF")
LINK_FONT = Font(color="0563C1", underline="single")
PICTURE_WIDTH = 720  # px the page band is shown at in the Evidence sheet
PICTURE_MAX_HEIGHT = 520  # px; Excel rows stop at 409 pt
EMU = 9525  # drawing units per pixel
# An amount with at most a currency symbol or code around it: "$12,400.00", "INR 5,00,000", "(1,234)", "-7.5 USD"
CURRENCY = r"(?:[A-Z]{3}|Rs\.?|[^\w\s.,()-])?"
NUMBER = re.compile(rf"^\s*\(?-?\s*{CURRENCY}\s*-?\d[\d,]*(\.\d+)?\s*{CURRENCY}\s*\)?\s*$")


# -----------------------------
# ROWS
# -----------------------------
def field_rows(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per template field with the final value and everything QC found."""
    results = {r["field"]: r for r in (run.get("report") or {}).get("results", [])}
    review = run.get("review") or {}
    rows = []
    for spec in (run.get("template") or {}).get("fields", []):
        r = results.get(spec["name"], {})
        decision = review.get(spec["name"])
        status = r.get("status", "NOT_CHECKED")
        rows.append({
            "field": spec["name"],
            "label": spec.get("label") or spec["name"].replace("_", " ").capitalize(),
            "type": spec.get("type", "string"),
            "value": decision["value"] if decision else r.get("final_value"),
            "source": decision["source"] if decision else ("verified" if status == "FAIL" else "extracted"),
            "status": status,
            "reviewed": bool(decision),
            "open": status in ("FAIL", "REVIEW") and not decision,
            "extracted_value": r.get("extracted_value"),
            "extracted_page": r.get("extracted_page"),
            "extracted_quote": r.get("extracted_quote"),
            "confidence": r.get("confidence"),
            "verdict": r.get("verdict"),
            "correct_value": r.get("correct_value"),
            "evidence_page": r.get("evidence_page"),
            "evidence_quote": r.get("evidence_quote"),
            "pages_checked": r.get("pages_checked") or [],
            "located_by": r.get("located_by"),
            "notes": r.get("notes") or [],
            "reasoning": r.get("reasoning"),
            "page": r.get("evidence_page") or r.get("extracted_page"),
            "evidence": r.get("evidence_quote") or r.get("extracted_quote"),
        })
    return rows


def run_summary(run: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    report = run.get("report") or {}
    count = lambda s: sum(1 for r in rows if r["status"] == s)  # noqa: E731
    return {
        "verified": count("PASS"),
        "mismatches": count("FAIL"),
        "needs_review": count("REVIEW"),
        "not_in_document": count("ABSENT"),
        "resolved": sum(1 for r in rows if r["reviewed"]),
        "open_issues": sum(1 for r in rows if r["open"]),
        "seconds": report.get("seconds"),
        "llm_calls": report.get("llm_calls"),
        "pages_sent_to_qc": report.get("pages_sent_to_qc"),
        "ocr_pages": report.get("ocr_pages") or [],
        "models": report.get("models") or {},
        "tokens_in": (report.get("usage") or {}).get("input"),
        "tokens_out": (report.get("usage") or {}).get("output"),
        "tokens": (report.get("usage") or {}).get("total"),
        "cost_usd": round(usage_cost(report["usage"])["cost_usd"], 4) if report.get("usage") else None,
    }


def columns_for(runs: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    """Field columns across all runs, in template order: (key, label, type)."""
    seen: Dict[str, Tuple[str, str, str]] = {}
    for run in runs:
        for f in (run.get("template") or {}).get("fields", []):
            if f["name"] not in seen:
                seen[f["name"]] = (f["name"], f.get("label") or f["name"].replace("_", " ").capitalize(),
                                   f.get("type", "string"))
    return list(seen.values())


def typed(value: Any, ftype: str) -> Any:
    """Numbers become real numbers in Excel so totals and filters work; everything else stays as written."""
    if value is None or value == "":
        return None
    if ftype == "number" and isinstance(value, str) and NUMBER.match(value):
        negative = value.strip().startswith(("-", "("))
        digits = re.sub(r"[^\d.]", "", value)
        try:
            n = float(digits)
            n = -n if negative else n
            return int(n) if n.is_integer() and "." not in digits else n
        except ValueError:
            return value
    return value


def iso(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else None


def yes(v: bool) -> str:
    return "Yes" if v else "No"


DOC_COLUMNS = ["Document", "Template", "Batch", "Pages", "Run status", "Approved",
               "Verified", "Mismatches", "Needs review", "Resolved", "Open issues"]
DOC_KEYS = ["document", "template", "batch", "pages", "run_status", "approved",
            "verified", "mismatches", "needs_review", "resolved", "open_issues"]


def doc_cells(run: Dict[str, Any], s: Dict[str, Any]) -> List[Any]:
    done = run["status"] == "done"
    return [run["filename"], run.get("template_name"), run.get("batch_name"), run.get("pages"),
            RUN_STATUS_LABEL.get(run["status"], run["status"]), yes(bool(run.get("approved_at"))),
            s["verified"] if done else None, s["mismatches"] if done else None, s["needs_review"] if done else None,
            s["resolved"] if done else None, s["open_issues"] if done else None]


DETAIL_HEADERS = [
    ("document", "Document"), ("template", "Template"), ("field", "Field key"), ("label", "Field"),
    ("value", "Final value"), ("source", "Value source"), ("status", "QC status"), ("reviewed", "Resolved by reviewer"),
    ("extracted_value", "Extracted value"), ("extracted_page", "Extracted page"), ("extracted_quote", "Extractor quote"),
    ("confidence", "Extractor confidence"), ("correct_value", "QC corrected value"), ("evidence_page", "Evidence page"),
    ("evidence_quote", "Evidence quote"), ("pages_checked", "Pages checked"), ("located_by", "Located by"),
    ("notes", "QC notes"), ("reasoning", "QC reasoning"), ("approved", "Approved"),
]


def detail_values(run: Dict[str, Any], r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "document": run["filename"], "template": run.get("template_name"), "field": r["field"], "label": r["label"],
        "value": r["value"], "source": SOURCE_LABEL.get(r["source"], r["source"]),
        "status": STATUS_LABEL.get(r["status"], r["status"]), "reviewed": yes(r["reviewed"]),
        "extracted_value": r["extracted_value"], "extracted_page": r["extracted_page"],
        "extracted_quote": r["extracted_quote"],
        "confidence": round(r["confidence"], 2) if isinstance(r["confidence"], (int, float)) else None,
        "correct_value": r["correct_value"], "evidence_page": r["evidence_page"], "evidence_quote": r["evidence_quote"],
        "pages_checked": ", ".join(str(p) for p in r["pages_checked"]), "located_by": r["located_by"],
        "notes": "; ".join(r["notes"]), "reasoning": r["reasoning"], "approved": yes(bool(run.get("approved_at"))),
    }


# -----------------------------
# FORMATS
# -----------------------------
def to_csv(runs: List[Dict[str, Any]], layout: str, keys: bool) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    if layout == "detail":
        w.writerow([k if keys else h for k, h in DETAIL_HEADERS])
        for run in runs:
            for r in field_rows(run):
                v = detail_values(run, r)
                w.writerow([v[k] for k, _ in DETAIL_HEADERS])
        return buf.getvalue()

    cols = columns_for(runs)
    with_qc = layout == "summary_qc"
    header = list(DOC_KEYS if keys else DOC_COLUMNS)
    for key, label, _ in cols:
        header.append(key if keys else label)
        if with_qc:
            header.append(f"{key}__qc" if keys else f"{label} (QC)")
    w.writerow(header)
    for run in runs:
        rows = {r["field"]: r for r in field_rows(run)}
        line = doc_cells(run, run_summary(run, list(rows.values())))
        for key, _, _ in cols:
            r = rows.get(key)
            line.append(r["value"] if r and run["status"] == "done" else None)
            if with_qc:
                line.append(qc_cell(r) if r and run["status"] == "done" else None)
        w.writerow(line)
    return buf.getvalue()


def qc_cell(r: Dict[str, Any]) -> str:
    if r["reviewed"]:
        return f"Resolved ({SOURCE_LABEL.get(r['source'], r['source']).lower()})"
    return STATUS_LABEL.get(r["status"], r["status"])


def to_json(runs: List[Dict[str, Any]]) -> str:
    out = []
    for run in runs:
        rows = field_rows(run)
        out.append({
            "run_id": run["id"], "document": run["filename"], "template": run.get("template_name"),
            "batch": run.get("batch_name"), "status": run["status"], "error": run.get("error"),
            "approved": bool(run.get("approved_at")), "approved_at": iso(run.get("approved_at")),
            "summary": run_summary(run, rows) if run["status"] == "done" else None,
            "data": {r["field"]: r["value"] for r in rows} if run["status"] == "done" else None,
            "fields": [{k: r[k] for k in ("field", "label", "value", "source", "status", "reviewed", "extracted_value",
                                          "correct_value", "page", "evidence", "pages_checked", "notes")}
                       for r in rows] if run["status"] == "done" else [],
        })
    return json.dumps({"exported_at": iso(time.time()), "documents": out}, indent=2, ensure_ascii=False)


def _header(ws, labels: List[str]) -> None:
    ws.append(labels)
    for cell in ws[1]:
        cell.fill, cell.font = FILL["header"], HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30


def _widths(ws, widths: Dict[int, float]) -> None:
    for i, w in widths.items():
        ws.column_dimensions[get_column_letter(i)].width = w


def _cell_note(r: Dict[str, Any]) -> Optional[str]:
    if r["reviewed"]:
        return (f"Resolved by reviewer ({SOURCE_LABEL.get(r['source'], r['source']).lower()}). "
                f"QC said {STATUS_LABEL[r['status']].lower()}; extracted value was {r['extracted_value']!r}.")
    if r["status"] == "FAIL":
        return (f"Mismatch. Extracted {r['extracted_value']!r} (page {r['extracted_page']}); "
                f"QC found {r['correct_value']!r} on page {r['evidence_page']}: \"{r['evidence_quote']}\"")
    if r["status"] == "REVIEW":
        return "Needs review. " + ("; ".join(r["notes"]) or "QC could not confirm this value.")
    return None


def _link(cell, sheet: str, row: int) -> None:
    cell.hyperlink = Hyperlink(ref=cell.coordinate, location=f"'{sheet}'!A{row}", display=str(cell.value or ""))


def _evidence_sheet(wb: Workbook, per_run, keys: bool) -> Dict[Tuple[str, str], int]:
    """One row per value that has a source page: the quote, and a picture of that part of the page.
    Returns the row for each (run id, field) so the other sheets can link to it."""
    ws = wb.create_sheet("Evidence", 1)
    _header(ws, ["document", "field", "value", "status", "page", "quote", "picture"] if keys else
            ["Document", "Field", "Value", "QC status", "Page", "Quote", "Where it is on the page"])
    _widths(ws, {1: 28, 2: 20, 3: 20, 4: 13, 5: 6, 6: 36, 7: PICTURE_WIDTH / 7 + 2})
    rows_for: Dict[Tuple[str, str], int] = {}
    for run, rows in per_run:
        if run["status"] != "done":
            continue
        path = run.get("path") or ""
        pics = None
        if path.lower().endswith(".pdf"):
            try:
                pics = Pictures(path)
            except Exception:
                pics = None
        try:
            for r in rows:
                if not r["page"]:
                    continue
                ws.append([run["filename"], r["label"], typed(r["value"], r["type"]),
                           STATUS_LABEL.get(r["status"], r["status"]), r["page"], r["evidence"]])
                row = ws.max_row
                rows_for[(run["id"], r["field"])] = row
                fill = FILL["resolved"] if r["reviewed"] else FILL.get(r["status"])
                if fill:
                    ws.cell(row, 4).fill = fill
                for c in range(1, 7):
                    ws.cell(row, c).alignment = Alignment(wrap_text=True, vertical="top")
                shot = pics.picture(r["page"], r["evidence"], r["value"], r["label"]) if pics else None
                if not shot:
                    ws.cell(row, 7, "No picture: the source is not a PDF." if not pics else "Page not found.")
                    continue
                png, w, h, found = shot
                scale = min(1.0, (PICTURE_WIDTH if found else 360) / w, PICTURE_MAX_HEIGHT / h)
                img = XLImage(io.BytesIO(png))
                img.width, img.height = round(w * scale), round(h * scale)
                # Held inside its own cell, so filtering hides it and sorting moves it with its row
                img.anchor = TwoCellAnchor(editAs="twoCell",
                                           _from=AnchorMarker(col=6, row=row - 1, colOff=4 * EMU, rowOff=4 * EMU),
                                           to=AnchorMarker(col=6, row=row - 1, colOff=(img.width + 4) * EMU,
                                                           rowOff=(img.height + 4) * EMU))
                ws.add_image(img)
                ws.row_dimensions[row].height = max(30, img.height * 0.75 + 8)
                if not found:
                    note = "(The quote isn't in the page's text, for example a scanned page, so the whole page is shown.)"
                    ws.cell(row, 6).value = f"{r['evidence']}\n\n{note}" if r["evidence"] else note
        finally:
            if pics:
                pics.doc.close()
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:F{max(ws.max_row, 1)}"
    return rows_for


def to_xlsx(runs: List[Dict[str, Any]], keys: bool, title: str) -> bytes:
    wb = Workbook()
    cols = columns_for(runs)
    n_doc = len(DOC_COLUMNS)
    per_run = [(run, field_rows(run)) for run in runs]
    evidence_row = _evidence_sheet(wb, per_run, keys)

    # Data: one row per document, cells coloured by QC result
    data = wb.active
    data.title = "Data"
    _header(data, list(DOC_KEYS if keys else DOC_COLUMNS) + [k if keys else label for k, label, _ in cols])
    for run, rows in per_run:
        by = {r["field"]: r for r in rows}
        done = run["status"] == "done"
        data.append(doc_cells(run, run_summary(run, rows)) +
                    [typed(by[k]["value"], t) if done and k in by else None for k, _, t in cols])
        row = data.max_row
        if not done:
            for c in range(1, n_doc + len(cols) + 1):
                data.cell(row, c).fill = FILL["muted"]
            continue
        for j, (k, _, t) in enumerate(cols, start=n_doc + 1):
            r = by.get(k)
            if not r:
                continue
            cell = data.cell(row, j)
            fill = FILL["resolved"] if r["reviewed"] else FILL.get(r["status"]) if r["open"] else None
            if fill:
                cell.fill = fill
            if (run["id"], k) in evidence_row:
                _link(cell, "Evidence", evidence_row[(run["id"], k)])
            note = _cell_note(r)
            if note:
                cell.comment = Comment(note[:1500], "ParseProof", width=320, height=140)
            if t == "number" and isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.##########" if isinstance(cell.value, float) else "#,##0"
        if run.get("approved_at"):
            data.cell(row, 6).fill = FILL["PASS"]
    _widths(data, {1: 34, 2: 20, 3: 20, 4: 7, 5: 11, 6: 10, 7: 9, 8: 11, 9: 12, 10: 9, 11: 11,
                   **{n_doc + i: 22 for i in range(1, len(cols) + 1)}})
    data.freeze_panes = data.cell(2, 2)
    data.auto_filter.ref = data.dimensions

    # QC status: same grid, with the status written out
    grid = wb.create_sheet("QC status")
    _header(grid, ["Document", "Run status", "Approved"] + [k if keys else label for k, label, _ in cols])
    for run, rows in per_run:
        by = {r["field"]: r for r in rows}
        done = run["status"] == "done"
        grid.append([run["filename"], RUN_STATUS_LABEL.get(run["status"], run["status"]),
                     yes(bool(run.get("approved_at")))] +
                    [qc_cell(by[k]) if done and k in by else None for k, _, _ in cols])
        for j, (k, _, _) in enumerate(cols, start=4):
            r = by.get(k)
            if done and r:
                grid.cell(grid.max_row, j).fill = FILL["resolved"] if r["reviewed"] else FILL.get(r["status"], FILL["muted"])
    _widths(grid, {1: 34, 2: 11, 3: 10, **{3 + i: 18 for i in range(1, len(cols) + 1)}})
    grid.freeze_panes = grid.cell(2, 2)
    grid.auto_filter.ref = grid.dimensions

    # QC detail: one row per field per document
    detail = wb.create_sheet("QC detail")
    _header(detail, [k if keys else h for k, h in DETAIL_HEADERS] + ["picture" if keys else "Picture"])
    status_col = [k for k, _ in DETAIL_HEADERS].index("status") + 1
    for run, rows in per_run:
        if run["status"] != "done":
            continue
        for r in rows:
            v = detail_values(run, r)
            v["value"] = typed(v["value"], r["type"])
            detail.append([v[k] for k, _ in DETAIL_HEADERS])
            fill = FILL["resolved"] if r["reviewed"] else FILL.get(r["status"])
            if fill:
                detail.cell(detail.max_row, status_col).fill = fill
            if (run["id"], r["field"]) in evidence_row:
                cell = detail.cell(detail.max_row, len(DETAIL_HEADERS) + 1, f"View page {r['page']}")
                _link(cell, "Evidence", evidence_row[(run["id"], r["field"])])
                cell.font = LINK_FONT
    _widths(detail, {1: 30, 2: 18, 3: 20, 4: 22, 5: 22, 6: 16, 7: 13, 8: 11, 9: 22, 10: 9, 11: 44, 12: 11,
                     13: 22, 14: 9, 15: 44, 16: 12, 17: 12, 18: 40, 19: 44, 20: 10, 21: 13})
    for row in detail.iter_rows(min_row=2):
        for c in (11, 15, 18, 19):
            row[c - 1].alignment = Alignment(wrap_text=True, vertical="top")
    detail.freeze_panes = detail.cell(2, 5)
    detail.auto_filter.ref = detail.dimensions

    # Runs: how each document was processed
    log = wb.create_sheet("Runs")
    _header(log, ["Document", "Template", "Batch", "Run status", "Error", "Pages", "Seconds", "LLM calls",
                  "Tokens in", "Tokens out", "Tokens total", "Cost (USD)", "Pages sent to QC", "OCR pages", "Extract model", "QC model", "Started", "Finished", "Approved at", "Run ID"])
    for run, rows in per_run:
        s = run_summary(run, rows)
        log.append([run["filename"], run.get("template_name"), run.get("batch_name"),
                    RUN_STATUS_LABEL.get(run["status"], run["status"]), run.get("error"), run.get("pages"), s["seconds"],
                    s["llm_calls"], s["tokens_in"], s["tokens_out"], s["tokens"], s["cost_usd"], s["pages_sent_to_qc"], ", ".join(map(str, s["ocr_pages"])) or None,
                    s["models"].get("extract"), s["models"].get("qc"), iso(run.get("created_at")),
                    iso(run.get("finished_at")), iso(run.get("approved_at")), run["id"]])
    _widths(log, {1: 34, 2: 20, 3: 20, 4: 11, 5: 30, 6: 7, 7: 9, 8: 9, 9: 10, 10: 10, 11: 12, 12: 11, 13: 10,
                  14: 12, 15: 14, 16: 12, 17: 17, 18: 17, 19: 17, 20: 14})
    log.freeze_panes = "B2"

    # Key: what the colours and columns mean
    key = wb.create_sheet("Key")
    key.column_dimensions["A"].width = 24
    key.column_dimensions["B"].width = 90
    key.append([title])
    key["A1"].font = Font(bold=True, size=14)
    key.append([f"Exported {iso(time.time())} from ParseProof · {len(runs)} document(s)"])
    key.append([])
    for label, text, fill in [
        ("No colour", "Verified: a second model confirmed the value on its source page.", None),
        ("Red", "Mismatch: QC found a different value. The cell holds the QC value; hover for the evidence.", FILL["FAIL"]),
        ("Amber", "Needs review: QC could not confirm the value, or a rule check failed.", FILL["REVIEW"]),
        ("No colour, empty", "Not in document: an optional field neither the extractor nor QC found. Nothing to verify.", None),
        ("Blue", "Resolved: a reviewer chose or edited this value.", FILL["resolved"]),
        ("Grey row", "The run did not finish (failed or still running), so it has no values.", FILL["muted"]),
    ]:
        key.append([label, text])
        if fill:
            key.cell(key.max_row, 1).fill = fill
    key.append([])
    for label, text in [
        ("Data", "One row per document, one column per field. Numbers are stored as numbers so totals work. "
                 "Click a value to see where it is in the document."),
        ("Evidence", "Every value with its source page, the quote, and a picture of that part of the page with the "
                     "quote highlighted in yellow. A scanned page is shown whole."),
        ("QC status", "The same grid with the QC result for every value."),
        ("QC detail", "One row per field per document: extracted value, QC value, evidence page and quote, notes, "
                      "and a link to the picture."),
        ("Runs", "Processing details per document: time, model calls, tokens used, estimated OpenAI cost in US dollars, pages checked, errors."),
    ]:
        key.append([label, text])
        key.cell(key.max_row, 1).font = Font(bold=True)
    for row in key.iter_rows(min_row=4):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename_for(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-")[:60] or "parseproof-export"
    return slug

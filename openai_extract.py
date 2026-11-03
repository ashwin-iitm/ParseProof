"""
openai_extract.py — field extraction with OpenAI's native document input.

PDFs are sent as files, so the model reads both the text layer and the page images
(scans, stamps, tables). Other formats are sent as page text. Output is forced into a
strict JSON schema: value, original page number, verbatim quote and confidence per field.
Large PDFs are split into page ranges; agents.py runs the ranges in parallel.

Also provides OCR for pages without a text layer, so the QC index (doc_index.py) can
search scanned documents.
"""

import base64
import json
import time
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

from config import client, logger, record_usage

EXTRACT_SYSTEM = """You are a precise document data extraction engine.
Rules:
- Use ONLY what is written in the document. Never guess or calculate a value.
- For each field return the value exactly as written (keep currency, units and formatting),
  the ORIGINAL page number it is on, and a short VERBATIM quote (copied exactly, under
  200 characters) that contains the value.
- Values like addresses span several lines. Include every line of the block, in order, and copy the
  quote character for character from the document. Never skip a line in the middle of a block.
- confidence: 0-1, how sure you are that this is the right value for this field.
- If a field is not present, return value null, page null, quote null, confidence 0."""


def _uses_temperature(model: str) -> bool:
    # Reasoning models (o-series, gpt-5) reject the temperature parameter
    return not (model.startswith("o") or model.startswith("gpt-5"))


def extraction_schema(field_names: List[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["fields"],
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "value", "page", "quote", "confidence"],
                    "properties": {
                        "name": {"type": "string", "enum": field_names},
                        "value": {"type": ["string", "null"]},
                        "page": {"type": ["integer", "null"]},
                        "quote": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                    },
                },
            }
        },
    }


def _fields_brief(fields: List[dict]) -> str:
    return json.dumps(
        [{"name": f["name"], "description": f.get("description", ""), "type": f.get("type", "string")}
         for f in fields],
        indent=2,
    )


def _respond(model: str, content: list, fields: List[dict], step: str = "Extraction") -> List[dict]:
    kwargs = {"temperature": 0} if _uses_temperature(model) else {}
    t = time.perf_counter()
    resp = client.responses.create(
        model=model,
        instructions=EXTRACT_SYSTEM,
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_schema", "name": "extraction",
                         "schema": extraction_schema([f["name"] for f in fields]), "strict": True}},
        timeout=240,  # up to 40 PDF pages per call
        **kwargs,
    )
    record_usage(model, resp.usage, step, time.perf_counter() - t)
    return json.loads(resp.output_text).get("fields", [])


def pdf_page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def extract_pdf_range(path: Path, first: int, last: int, total: int,
                      fields: List[dict], model: str) -> List[dict]:
    """Extract from pages first..last (1-based, inclusive) of a PDF, sent as a file."""
    with fitz.open(path) as src, fitz.open() as part:
        part.insert_pdf(src, from_page=first - 1, to_page=last - 1)
        data = base64.b64encode(part.tobytes(garbage=3, deflate=True)).decode()

    where = (f"This file is pages {first}-{last} of a {total}-page document. Page 1 of this file is "
             f"page {first} of the original. Report ORIGINAL page numbers ({first}-{last})."
             if (first, last) != (1, total) else f"This file is the complete {total}-page document.")
    content = [
        {"type": "input_file", "filename": f"{path.stem}_p{first}-{last}.pdf",
         "file_data": f"data:application/pdf;base64,{data}"},
        {"type": "input_text", "text": f"{where}\n\nFields to extract:\n{_fields_brief(fields)}"},
    ]
    return _respond(model, content, fields, f"Extraction: PDF pages {first}-{last}")


def extract_text_pages(pages: List[str], numbers: List[int], fields: List[dict], model: str) -> List[dict]:
    """Extract from non-PDF documents (Word, Excel, CSV, text) sent as labelled page text."""
    body = "\n\n".join(f"=== PAGE {n} ===\n{pages[n - 1]}" for n in numbers)
    content = [{"type": "input_text",
                "text": f"Fields to extract:\n{_fields_brief(fields)}\n\nDocument pages:\n{body}"}]
    return _respond(model, content, fields, f"Extraction: pages {numbers[0]}-{numbers[-1]} as text")


def ocr_page(path: Path, page_no: int, model: str) -> str:
    """Transcribe a page that has no text layer (a scan), so QC can search it."""
    with fitz.open(path) as doc:
        png = doc[page_no - 1].get_pixmap(dpi=150).tobytes("png")
    kwargs = {"temperature": 0} if _uses_temperature(model) else {}
    t = time.perf_counter()
    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [
            {"type": "input_image", "image_url": f"data:image/png;base64,{base64.b64encode(png).decode()}"},
            {"type": "input_text", "text": "Transcribe all text on this page exactly, preserving line breaks "
                                           "and reading order. Output only the text."},
        ]}],
        **kwargs,
    )
    record_usage(model, resp.usage, f"OCR: page {page_no}", time.perf_counter() - t)
    return resp.output_text or ""


TEMPLATE_SYSTEM = """You design data-extraction templates for business documents.
A template is a list of fields; each field is extracted as ONE value from the document and later
verified against the exact page it came from. Rules:
- Single values only. For repeating data (claims on a loss run, line items on an invoice) create
  summary fields that are written on the document (totals, counts, largest item), not per-row fields.
- Only fields whose value is literally written in the document. No summaries, opinions or calculations.
- name: snake_case key (lowercase letters, digits, underscores, starts with a letter).
- label: short human label in sentence case.
- description: what the value is and where/how it usually appears, including common synonyms
  ("valued as of", "evaluation date"). This is what the extraction model reads, so be specific.
- type: "number" for amounts and counts, "date" for dates, otherwise "string".
- required: true only for fields every such document must have.
- Template name: a short human title in sentence case, e.g. "Workers comp loss run" (not a key).
- rules: whenever fields you included add up, add the sum check: e.g. paid + reserves = incurred,
  open + closed claims = total claims, subtotal + tax = total. Never add one that doesn't hold.
- 6 to 20 fields unless the user asks for something else. Follow the user's request exactly when given.
- If a sample document is attached, base the fields on what that document actually contains."""


def _template_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "description", "fields", "rules"],
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "label", "description", "type", "required"],
                    "properties": {
                        "name": {"type": "string"},
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                        "type": {"type": "string", "enum": ["string", "number", "date"]},
                        "required": {"type": "boolean"},
                    },
                },
            },
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["fields", "equals"],
                    "properties": {"fields": {"type": "array", "items": {"type": "string"}},
                                   "equals": {"type": "string"}},
                },
            },
        },
    }


SAMPLE_PAGES = 30  # pages of a sample document shown when drafting a template


def draft_template(prompt: str, model: str, sample: Optional[Path] = None,
                   sample_pages: Optional[List[str]] = None) -> dict:
    """Ask the model to design a template from a description and/or a sample document."""
    request = prompt.strip() or "Suggest the key fields to extract from this kind of document."
    content: list = []
    if sample is not None and sample.suffix.lower() == ".pdf":
        with fitz.open(sample) as src, fitz.open() as part:
            part.insert_pdf(src, from_page=0, to_page=min(src.page_count, SAMPLE_PAGES) - 1)
            data = base64.b64encode(part.tobytes(garbage=3, deflate=True)).decode()
        content.append({"type": "input_file", "filename": sample.name,
                        "file_data": f"data:application/pdf;base64,{data}"})
    elif sample_pages:
        text = "\n\n".join(f"=== PAGE {i} ===\n{p}" for i, p in enumerate(sample_pages[:SAMPLE_PAGES], 1))
        content.append({"type": "input_text", "text": f"Sample document:\n{text[:120000]}"})
    content.append({"type": "input_text", "text": f"What the user wants to extract:\n{request}"})

    kwargs = {"temperature": 0.2} if _uses_temperature(model) else {}
    resp = client.responses.create(
        model=model,
        instructions=TEMPLATE_SYSTEM,
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_schema", "name": "template", "schema": _template_schema(), "strict": True}},
        timeout=180,
        **kwargs,
    )
    return json.loads(resp.output_text)


def check_connection(model: Optional[str] = None) -> dict:
    """Cheap call used by the settings page to confirm the API key works."""
    try:
        models = {m.id for m in client.models.list()}
        return {"ok": True, "model_available": (model in models) if model else None}
    except Exception as e:
        logger.warning("OpenAI connection check failed: %s", e)
        return {"ok": False, "error": str(e)[:300]}

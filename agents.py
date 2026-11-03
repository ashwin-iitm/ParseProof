"""
agents.py — Extraction agent + QC agent wired together with LangGraph.

Main pipeline:

    ingest ──(extraction supplied)────────────────────────────────┐
       └──> extract_batch x N (parallel) ──> merge_extraction ─────┤
                                                                   v
                                  qc_field x fields (parallel, one QC agent each)
                                                                   v
                                                        rules ──> report

- ingest:   reads page text, OCRs pages with no text layer, builds (or loads) the
            page-level hybrid RAG index used by QC.
- extract:  OpenAI native document input (openai_extract.py), PDFs split into page ranges.
- QC agent: verifies each field against only the page(s) it came from, using the RAG index.

QC agent (per-field subgraph):

    locate ──(cited page / quote verified)──> verify ──> finalize
       └──(no usable citation)──> search ──────┘  │
                                    ^              │
                                    └──────────────┘  (not found, incorrect or evidence not on
                                                       page, and the agent has not searched yet)
"""

import base64
import contextvars
import hashlib
import json
import operator
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Any, Dict, Iterator, List, Optional, Tuple, TypedDict

import fitz  # PyMuPDF
import pandas as pd
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from rapidfuzz import fuzz

from config import (
    client, logger, record_usage, start_meter, EXTRACT_MODEL, QC_MODEL, OCR_MODEL, EXTRACT_BATCH_CHARS, EXTRACT_PAGES_PER_CALL,
    QC_SEARCH_PAGES, AGENT_MAX_CONCURRENCY, QUOTE_MATCH_THRESHOLD, INDEX_DIR,
)
from doc_index import PageIndex, normalize
from openai_extract import extract_pdf_range, extract_text_pages, ocr_page
from text_processing import extract_text_from_file

# Indexes in memory, keyed by file hash (also saved under INDEX_DIR)
_INDEXES: Dict[str, PageIndex] = {}

PASS, FAIL, REVIEW, NOT_CHECKED = "PASS", "FAIL", "REVIEW", "NOT_CHECKED"
OCR_MIN_CHARS = 25  # a PDF page with less text than this is treated as a scan
INDEX_VERSION = 3  # bump when page text extraction changes (v3: column-aware text blocks)
QC_MAX_IMAGES = 2  # page images sent with a full check (the text of every page it reads is sent too)
QC_IMAGE_DPI = 110


def default_models() -> Dict[str, str]:
    return {"extract": EXTRACT_MODEL, "qc": QC_MODEL, "ocr": OCR_MODEL}


# -----------------------------
# HELPERS
# -----------------------------
def llm_json(model: str, system: str, user: str, images: Optional[List[str]] = None, step: str = "") -> dict:
    """images: base64 PNGs shown to the model after the text."""
    kwargs = {} if model.startswith(("o", "gpt-5")) else {"temperature": 0}
    content: Any = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}}
            for b64 in images]
    for attempt in range(2):
        t = time.perf_counter()
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            **kwargs,
        )
        record_usage(model, resp.usage, step + (" (retry: invalid JSON)" if attempt else ""), time.perf_counter() - t)
        try:
            return json.loads(resp.choices[0].message.content)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON (attempt %d)", attempt + 1)
    raise ValueError("LLM did not return valid JSON")


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def as_page(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> List[float]:
    return [float(n.replace(",", "")) for n in NUMBER.findall(text)]


def value_in_quote(value: Any, quote: str) -> bool:
    """Is a corrected value actually stated in the evidence? Digits must match exactly, and every
    number in the value must be a whole number in the quote: a correction of 0 needs a real 0 amount,
    not just a 0 inside some other number."""
    if is_empty(value):
        return False
    wanted = numbers_in(str(value))
    if wanted:
        in_quote = set(numbers_in(quote))  # as numbers, so 03/07/2026 matches 3/7/2026 and 50,000.00 matches 50,000
        return all(n in in_quote for n in wanted)
    return fuzz.partial_ratio(normalize(value), normalize(quote)) >= QUOTE_MATCH_THRESHOLD


def same_value(a: Any, b: Any) -> bool:
    """The checker's "correction" is the extracted value again: the same letters and digits once
    symbols and spaces are dropped (548867 and $548,867), or the same numbers (1,234.00 and 1234)."""
    if is_empty(a) or is_empty(b):
        return False
    alnum = lambda x: re.sub(r"[^0-9a-z]", "", str(x).lower())  # noqa: E731
    if alnum(a) and alnum(a) == alnum(b):
        return True
    na, nb = numbers_in(str(a)), numbers_in(str(b))
    letters = lambda x: re.sub(r"[^a-z]", "", str(x).lower())  # noqa: E731
    return bool(na) and na == nb and letters(a) == letters(b)


def same_words(a: Any, b: Any) -> bool:
    """Text values that differ only by repeated parts, order or punctuation (an address whose city,
    state and PIN are printed twice). Short values and single words are left to the QC model."""
    wa, wb = (set(re.findall(r"[a-z0-9/]+", normalize(x))) for x in (a, b))
    return len(wa) >= 4 and wa == wb


def pages_block(idx: PageIndex, pages: List[int]) -> str:
    return "\n\n".join(f"=== PAGE {p} ===\n{idx.page_text(p)}" for p in pages)


def page_images(path: Path, pages: List[int]) -> List[str]:
    """Render PDF pages so the QC model sees the layout, like the extractor did."""
    if path.suffix.lower() != ".pdf":
        return []
    out = []
    with fitz.open(path) as doc:
        for p in pages[:QC_MAX_IMAGES]:
            if 1 <= p <= doc.page_count:
                out.append(base64.b64encode(doc[p - 1].get_pixmap(dpi=QC_IMAGE_DPI).tobytes("png")).decode())
    return out


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def normalize_schema(schema: Any) -> Tuple[List[dict], List[dict]]:
    """Accepts {"fields": [...], "rules": [...]} or a bare list of fields / field names."""
    rules = []
    if isinstance(schema, dict):
        rules = schema.get("rules", [])
        schema = schema.get("fields", [])
    fields = []
    for f in schema:
        if isinstance(f, str):
            f = {"name": f}
        fields.append({"name": f["name"], "label": f.get("label") or "", "description": f.get("description", ""),
                       "type": f.get("type", "string"), "required": bool(f.get("required", False))})
    return fields, rules


def normalize_extraction(raw: Any, fields: List[dict]) -> Dict[str, dict]:
    """Accepts {name: value}, {name: {value, page, quote}} or [{name, value, page, quote}]."""
    if isinstance(raw, list):
        raw = {r["name"]: r for r in raw}
    out = {}
    for f in fields:
        item = raw.get(f["name"])
        if not isinstance(item, dict):
            item = {"value": item}
        value = item.get("value")
        if isinstance(value, str):
            value = re.sub(r"\s*\n\s*", " ", value.strip())  # multi-line blocks become one line
        out[f["name"]] = {"name": f["name"], "value": value, "page": as_page(item.get("page")),
                          "quote": item.get("quote"), "confidence": item.get("confidence")}
    return out


# -----------------------------
# STATE
# -----------------------------
class PipelineState(TypedDict, total=False):
    file_path: str
    fields: List[dict]
    rules: List[dict]
    models: Dict[str, str]
    extraction: Dict[str, dict]
    extraction_source: str
    qc_fields: Optional[List[str]]
    run_qc: bool
    started_at: float
    doc_id: str
    num_pages: int
    ocr_pages: List[int]
    index_reused: bool
    extract_jobs: List[List[int]]
    extraction_candidates: Annotated[List[dict], operator.add]
    qc_results: Annotated[List[dict], operator.add]
    qc_pending: Annotated[List[dict], operator.add]
    llm_calls: Annotated[int, operator.add]
    final_results: List[dict]
    report: dict


class FieldQCState(TypedDict, total=False):
    doc_id: str
    file_path: str
    spec: dict
    extracted: dict
    qc_model: str
    candidate_pages: List[int]
    pages_checked: List[int]
    located_by: str
    citation_ok: Optional[bool]
    searched: bool
    reasked: bool
    verdict: dict
    evidence_ok: bool
    evidence_page: Optional[int]
    notes: List[str]
    qc_calls: List[dict]
    llm_calls: int
    result: dict


# -----------------------------
# INGEST (text + OCR + RAG index)
# -----------------------------
def load_index(path: Path, ocr_model: str) -> Tuple[str, PageIndex, List[int], bool]:
    """Build or load the page index for a document. Returns (doc_id, index, OCR'd pages, reused)."""
    doc_id = file_hash(path)
    if doc_id in _INDEXES:
        return doc_id, _INDEXES[doc_id], [], True
    folder = INDEX_DIR / f"{doc_id}_v{INDEX_VERSION}"
    if PageIndex.exists(folder):
        _INDEXES[doc_id] = PageIndex.load(folder)
        return doc_id, _INDEXES[doc_id], [], True

    logger.info("Indexing %s", path.name)
    pages = extract_text_from_file(path)
    ocr_pages = []
    if path.suffix.lower() == ".pdf":
        ocr_pages = [i for i, t in enumerate(pages, 1) if len(t.strip()) < OCR_MIN_CHARS]
        if ocr_pages:
            logger.info("OCR for %d page(s) without a text layer", len(ocr_pages))
            # The run's call log lives in a context variable. Copy it here, in this thread, one copy per
            # page: copied inside the pool it would be the pool thread's empty context.
            contexts = [contextvars.copy_context() for _ in ocr_pages]
            with ThreadPoolExecutor(max_workers=AGENT_MAX_CONCURRENCY) as pool:
                texts = list(pool.map(lambda job: job[0].run(ocr_page, path, job[1], ocr_model), zip(contexts, ocr_pages)))
            for p, text in zip(ocr_pages, texts):
                pages[p - 1] = text
    index = PageIndex(pages)
    index.save(folder)
    _INDEXES[doc_id] = index
    return doc_id, index, ocr_pages, False


def plan_extraction(path: Path, idx: PageIndex) -> List[List[int]]:
    """PDFs: page ranges sent as files. Other formats: page-text batches."""
    n = len(idx)
    if path.suffix.lower() == ".pdf":
        return [list(range(s, min(s + EXTRACT_PAGES_PER_CALL, n + 1)))
                for s in range(1, n + 1, EXTRACT_PAGES_PER_CALL)]
    batches, cur, size = [], [], 0
    for i, text in enumerate(idx.pages, 1):
        if cur and size + len(text) > EXTRACT_BATCH_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(text)
    if cur:
        batches.append(cur)
    return batches


def ingest(state: PipelineState) -> dict:
    path = Path(state["file_path"])
    doc_id, idx, ocr_pages, reused = load_index(path, state["models"]["ocr"])
    return {"doc_id": doc_id, "num_pages": len(idx), "ocr_pages": ocr_pages, "index_reused": reused,
            "extract_jobs": plan_extraction(path, idx), "llm_calls": len(ocr_pages)}


# -----------------------------
# EXTRACTION AGENT (OpenAI document input)
# -----------------------------
def extract_batch(payload: dict) -> dict:
    path = Path(payload["file_path"])
    idx = _INDEXES[payload["doc_id"]]
    pages = payload["pages"]
    if path.suffix.lower() == ".pdf":
        items = extract_pdf_range(path, pages[0], pages[-1], len(idx), payload["fields"], payload["model"])
    else:
        items = extract_text_pages(idx.pages, pages, payload["fields"], payload["model"])

    candidates = []
    for item in items:
        page = as_page(item.get("page"))
        # The model's page numbers can drift; the verbatim quote is the ground truth
        if item.get("quote"):
            found, _ = idx.find_quote(item["quote"], pages)
            if found is None:
                found, _ = idx.find_quote(item["quote"])
            page = found or page
        candidates.append({**item, "page": page if page and 1 <= page <= len(idx) else None})
    return {"extraction_candidates": candidates, "llm_calls": 1}


def merge_extraction(state: PipelineState) -> dict:
    """Several page ranges may report the same field: keep the most confident non-empty value."""
    names = {f["name"] for f in state["fields"]}
    best: Dict[str, dict] = {}
    for c in state.get("extraction_candidates", []):
        if c.get("name") not in names or is_empty(c.get("value")):
            continue
        cur = best.get(c["name"])
        if cur is None or (c.get("confidence") or 0) > (cur.get("confidence") or 0):
            best[c["name"]] = c
    return {"extraction": normalize_extraction(best, state["fields"]), "extraction_source": "openai"}


GROUND_SYSTEM = """You extracted fields from a document, but for the fields below the quote you gave
is not in the document's text, so the value may be misread. Re-read the pages below. The page text is
the document's own text; the images show its layout.
- Copy the value and the quote character for character from the page text.
- Values like addresses span several lines: include every line of the block, in order. Use the image
  to see which lines belong to the block; never join lines from a different box or column.
- page: the page number the quote is on. If the field is not on these pages, use null for all three.
Return JSON: {"fields": [{"name": str, "value": str|null, "page": int|null, "quote": str|null}]}"""


def ground_extraction(state: PipelineState) -> dict:
    """The extractor checks its own work: a value whose quote isn't on the page is re-read once
    from that page's text before QC sees it. A re-read only counts if its quote is on the page."""
    idx = _INDEXES[state["doc_id"]]
    extraction = state["extraction"]
    loose = {name: ex for name, ex in extraction.items()
             if not is_empty(ex.get("value")) and ex.get("quote") and ex.get("page")
             and idx.find_quote(ex["quote"])[0] is None}
    if not loose:
        return {}

    pages = sorted({ex["page"] for ex in loose.values() if 1 <= ex["page"] <= len(idx)})[:QC_MAX_IMAGES]
    specs = [f for f in state["fields"] if f["name"] in loose]
    before = [{"name": n, "value": ex["value"], "page": ex["page"], "quote": ex["quote"]} for n, ex in loose.items()]
    brief = [{k: f.get(k) for k in ("name", "description", "type")} for f in specs]
    user = (f"Fields:\n{json.dumps(brief, indent=2)}\n\n"
            f"Your first answers (quotes not found in the text):\n{json.dumps(before, indent=2, ensure_ascii=False)}\n\n"
            f"Pages:\n{pages_block(idx, pages)}")
    try:
        out = llm_json(state["models"]["extract"], GROUND_SYSTEM, user, page_images(Path(state["file_path"]), pages),
                       step=f"Self-check: {', '.join(loose)}")
    except Exception as e:  # the first answer still goes to QC
        logger.warning("Re-reading ungrounded fields failed: %s", e)
        return {"llm_calls": 1}

    fixed = dict(extraction)
    for item in out.get("fields") or []:
        name = item.get("name")
        if name not in loose or is_empty(item.get("value")) or not item.get("quote"):
            continue
        found, _ = idx.find_quote(item["quote"])
        if found is None:
            continue
        old = loose[name]
        value = re.sub(r"\s*\n\s*", " ", str(item["value"]).strip())  # page text keeps its line breaks
        fixed[name] = {**old, "value": value, "quote": item["quote"], "page": found,
                       "regrounded_from": old["value"]}
    return {"extraction": fixed, "llm_calls": 1}


# -----------------------------
# QC AGENT (per-field subgraph, uses the RAG index)
# -----------------------------
QC_SYSTEM = """You are a meticulous QC auditor checking one extracted field against the source pages.
Decide:
- "correct": the pages support the extracted value. Formatting differences are fine
  (e.g. 45200 vs 45,200.00, 2026-03-15 vs 15 March 2026) as long as the meaning is identical.
- "incorrect": the pages show a different value for this field. Give the correct value.
  If the extracted value is null/empty but the field IS present, that is also "incorrect".
- "not_found": these pages do not contain this field.
- Never calculate or infer a value. correct_value must be stated explicitly in evidence_quote.
- If the pages only discuss a related but different topic (e.g. late-payment interest when the field
  is the payment due period), the answer is "not_found", not "incorrect".
- Page images are attached. Use them for layout: which lines belong to which box, column or label.
  The page text may list lines in a different order than they appear visually.
- Values like addresses span several lines. An extracted value that contains the same block (with
  different line breaks, or with/without the person's name or a repeated city/state/PIN) is "correct".
  Never build a value by joining lines that are not next to each other on the page.
- If the extracted value is empty and these pages don't show the field, the answer is "not_found"
  (that confirms the field is absent). Use "incorrect" only when the pages show a value for the field.
Always give evidence_quote: a short VERBATIM quote (copied exactly, under 200 characters) from the
pages that proves your verdict, and the page number it is on. Copy one continuous piece of the page:
never shorten it with "..." and never describe the page in your own words. Use null for both only
when not_found.
Return JSON: {"verdict": "correct"|"incorrect"|"not_found", "correct_value": str|null,
"evidence_quote": str|null, "evidence_page": int|null, "reasoning": str}"""


def qc_locate(s: FieldQCState) -> dict:
    idx = _INDEXES[s["doc_id"]]
    ex = s.get("extracted") or {}
    notes = list(s.get("notes", []))
    quote, page = ex.get("quote"), ex.get("page")

    if is_empty(ex.get("value")):
        notes.append("Nothing was extracted; searched the document to confirm the field is absent.")
        return {"candidate_pages": [], "notes": notes}

    if quote:
        if page:
            p, _ = idx.find_quote(quote, [page])
            if p:
                return {"candidate_pages": [p], "located_by": "citation", "citation_ok": True}
        p, _ = idx.find_quote(quote)
        if p:
            notes.append(f"Extractor cited page {page}, but its quote is on page {p}." if page
                         else f"Extractor gave no page; its quote is on page {p}.")
            return {"candidate_pages": [p], "located_by": "quote_match", "citation_ok": False, "notes": notes}
        notes.append("Extractor's quote does not appear in the document text.")
        return {"candidate_pages": [], "citation_ok": False, "notes": notes}

    if page and 1 <= page <= len(idx):
        return {"candidate_pages": [page], "located_by": "cited_page"}
    return {"candidate_pages": [], "notes": notes}


def qc_search(s: FieldQCState) -> dict:
    idx = _INDEXES[s["doc_id"]]
    spec, ex = s["spec"], s.get("extracted") or {}
    value = "" if is_empty(ex.get("value")) else str(ex["value"])
    query = f"{spec['name'].replace('_', ' ')} {spec.get('description', '')} {value}".strip()
    checked = s.get("pages_checked", [])
    hits = idx.search(query, k=QC_SEARCH_PAGES + len(checked), step=f"QC search: {spec['name']}")
    new_pages = [h["page"] for h in hits if h["page"] not in checked][:QC_SEARCH_PAGES]
    # Re-verify against the cited page AND the search hits together, so the auditor can choose
    return {"candidate_pages": checked + new_pages if new_pages else [], "searched": True, "located_by": "search"}


REASK = ("Your evidence_quote is not on these pages word for word. Answer again with the same JSON. "
         "Copy evidence_quote as ONE continuous piece of the page text, exactly as written: a whole line or "
         "table row that contains the value. Do not join a column heading to a value and do not use '...'.")


def clean_verdict(v: dict) -> dict:
    """Models sometimes write the word null instead of a JSON null."""
    cv = v.get("correct_value")
    if isinstance(cv, str) and cv.strip().lower() in ("null", "none", "n/a", ""):
        v = {**v, "correct_value": None}
    return v


def qc_verify(s: FieldQCState) -> dict:
    idx = _INDEXES[s["doc_id"]]
    spec, ex = s["spec"], s.get("extracted") or {}
    pages = s["candidate_pages"]
    user = (
        f"Field: {spec['name']}\nDescription: {spec.get('description') or '-'}\nType: {spec.get('type')}\n"
        f"Extracted value: {json.dumps(ex.get('value'))}\n\nSource pages:\n{pages_block(idx, pages)}"
    )
    images = page_images(Path(s["file_path"]), pages) if s.get("file_path") else []
    if images:
        user += f"\n\nImages of pages {', '.join(map(str, pages[:QC_MAX_IMAGES]))} follow, in that order."
    step = f"QC check: {spec['name']}" + (" (after search)" if s.get("searched") else "")

    def ask(text: str, label: str) -> Tuple[dict, dict]:
        verdict = clean_verdict(llm_json(s["qc_model"], QC_SYSTEM, text, images, step=label))
        # Keep the request as sent (images stand in as labels) so reviewers can see what QC was given
        content = [{"type": "text", "text": text}] + [
            {"type": "image_url", "image_url": {"url": f"<page {p} as PNG, {QC_IMAGE_DPI} dpi>", "detail": "high"}}
            for p in pages[:len(images)]]
        call = {"model": s["qc_model"], "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": QC_SYSTEM},
                             {"role": "user", "content": content if images else text}],
                "response": verdict}
        return verdict, call

    def proof_on_page(verdict: dict) -> Optional[int]:
        """Don't trust the auditor blindly either: its evidence must really be on the page."""
        if not verdict.get("evidence_quote"):
            return None
        cited = as_page(verdict.get("evidence_page"))
        p, _ = idx.find_quote(verdict["evidence_quote"], [cited] if cited in pages else pages)
        return p

    verdict, call = ask(user, step)
    calls = [call]
    evidence_page = proof_on_page(verdict)
    if verdict.get("evidence_quote") and evidence_page is None and not s.get("reasked"):
        # One more try on the same pages, telling it what was wrong (counts as a model call)
        retry_text = f"{user}\n\nYour previous answer:\n{json.dumps(verdict, ensure_ascii=False)}\n\n{REASK}"
        verdict, call = ask(retry_text, step + " (re-ask: proof not on the page)")
        calls.append(call)
        evidence_page = proof_on_page(verdict)
    evidence_ok = evidence_page is not None

    notes = list(s.get("notes", []))
    if len(calls) > 1:
        notes.append("The checker's first proof wasn't on the page word for word, so it was asked once more.")
    if verdict.get("evidence_quote") and not evidence_ok:
        notes.append("QC model's evidence quote was not found on the pages it was given.")
    elif (evidence_ok and verdict.get("verdict") == "incorrect"
          # an empty field with no correction is handled as "not found" when the field is decided
          and not (is_empty(ex.get("value")) and is_empty(verdict.get("correct_value")))
          and not value_in_quote(verdict.get("correct_value"), verdict["evidence_quote"])):
        evidence_ok = False
        notes.append(f"QC model's correction '{verdict.get('correct_value')}' is not stated in its evidence.")
    checked = s.get("pages_checked", [])
    return {
        "verdict": verdict, "evidence_ok": evidence_ok, "evidence_page": evidence_page, "notes": notes,
        "pages_checked": checked + [p for p in pages if p not in checked],
        "llm_calls": s.get("llm_calls", 0) + len(calls), "reasked": s.get("reasked") or len(calls) > 1,
        "qc_calls": s.get("qc_calls", []) + calls,
    }


def qc_finalize(s: FieldQCState) -> dict:
    spec, ex = s["spec"], s.get("extracted") or {}
    verdict = s.get("verdict") or {}
    v = verdict.get("verdict")
    notes = list(s.get("notes", []))
    # "Incorrect" with no corrected value, on a field that was left empty, means the field isn't there
    if v == "incorrect" and is_empty(ex.get("value")) and is_empty(verdict.get("correct_value")):
        v = "not_found"
        verdict = {**verdict, "verdict": v}

    if v == "correct" and s.get("evidence_ok"):
        status = PASS
    elif v == "incorrect" and s.get("evidence_ok") and same_value(ex.get("value"), verdict.get("correct_value")):
        status, v = PASS, "correct"
        notes.append("QC's suggested value is the same as the extracted one (only formatting differs), "
                     "so it counts as verified.")
    elif (v == "incorrect" and s.get("evidence_ok") and spec.get("type", "string") == "string"
          and same_words(ex.get("value"), verdict.get("correct_value"))):
        status, v = PASS, "correct"
        notes.append("QC's suggested value has the same words as the extracted one (only repeats, order or "
                     "punctuation differ), so it counts as verified.")
    elif v == "incorrect" and s.get("evidence_ok"):
        status = FAIL
    elif v == "not_found" and is_empty(ex.get("value")) and not spec.get("required"):
        status = PASS
        notes.append("Confirmed absent on the pages checked.")
    else:
        status = REVIEW
        if not s.get("pages_checked"):
            notes.append("No relevant page could be located.")

    if ex.get("regrounded_from"):
        notes.insert(0, f"The extractor's first read (\"{ex['regrounded_from']}\") wasn't backed by the page, "
                        f"so it re-read page {ex.get('page')} before QC.")

    return {"result": {
        "field": spec["name"],
        "extracted_value": ex.get("value"),
        "extracted_page": ex.get("page"),
        "extracted_quote": ex.get("quote"),
        "confidence": ex.get("confidence"),
        "status": status,
        "verdict": v,
        "correct_value": verdict.get("correct_value") if v == "incorrect" else None,
        "evidence_quote": verdict.get("evidence_quote"),
        "evidence_page": s.get("evidence_page"),
        "pages_checked": s.get("pages_checked", []),
        "located_by": s.get("located_by", "none"),
        "citation_ok": s.get("citation_ok"),
        "reasoning": verdict.get("reasoning"),
        "notes": notes,
        "qc_calls": s.get("qc_calls", []),
    }}


def route_after_locate(s: FieldQCState) -> str:
    return "verify" if s.get("candidate_pages") else "search"


def route_after_search(s: FieldQCState) -> str:
    return "verify" if s.get("candidate_pages") else "finalize"


def route_after_verify(s: FieldQCState) -> str:
    v = (s.get("verdict") or {}).get("verdict")
    # Not found, or a proof Python couldn't confirm: search other pages once. A correction whose proof
    # Python confirmed on the page is already settled (it becomes a Mismatch), so it doesn't search.
    needs_more = v == "not_found" or not s.get("evidence_ok")
    return "search" if needs_more and not s.get("searched") else "finalize"


def build_qc_agent():
    g = StateGraph(FieldQCState)
    g.add_node("locate", qc_locate)
    g.add_node("search", qc_search)
    g.add_node("verify", qc_verify)
    g.add_node("finalize", qc_finalize)
    g.add_edge(START, "locate")
    g.add_conditional_edges("locate", route_after_locate, ["verify", "search"])
    g.add_conditional_edges("search", route_after_search, ["verify", "finalize"])
    g.add_conditional_edges("verify", route_after_verify, ["search", "finalize"])
    g.add_edge("finalize", END)
    return g.compile()


QC_AGENT = build_qc_agent()


def qc_field(payload: dict) -> dict:
    out = QC_AGENT.invoke({**payload, "notes": list(payload.get("notes") or []), "pages_checked": [],
                              "qc_calls": list(payload.get("qc_calls") or []), "llm_calls": 0, "searched": False,
                              "reasked": False})
    return {"qc_results": [out["result"]], "llm_calls": out.get("llm_calls", 0)}


# -----------------------------
# PAGE CHECK: one checker call per page for every field whose quote is on that page
# -----------------------------
QC_PAGE_SYSTEM = QC_SYSTEM.split("Return JSON:")[0].replace(
    "checking one extracted field against the source pages.",
    "checking several extracted fields against the same source pages. Judge each field on its own, "
    "as if it were the only one.") + """There may be no page image: then judge from the page text, where table rows are listed line by line.
Return JSON: {"fields": [{"name": str, "verdict": "correct"|"incorrect"|"not_found", "correct_value": str|null,
"evidence_quote": str|null, "evidence_page": int|null, "reasoning": str}]}, one entry per field, in the order given."""
PAGE_GROUP_MAX = 12  # fields per page check


def qc_page(payload: dict) -> dict:
    """Confirms the easy fields cheaply. Only "correct" with a proof Python finds on the page is final;
    every other field goes on to the full per-field check (page image, search, re-ask)."""
    idx = _INDEXES[payload["doc_id"]]
    page, items = payload["page"], payload["items"]
    path = Path(payload["file_path"])
    # The page text is enough when the PDF has a text layer; a scanned page also gets its image
    images = page_images(path, [page]) if page in payload.get("ocr_pages", []) else []
    brief = [{"name": it["spec"]["name"], "description": it["spec"].get("description") or "-",
              "type": it["spec"].get("type"), "extracted_value": (it["extracted"] or {}).get("value")} for it in items]
    user = (f"Fields to check:\n{json.dumps(brief, indent=2, ensure_ascii=False)}\n\n"
            f"Source page:\n{pages_block(idx, [page])}")
    if images:
        user += f"\n\nAn image of page {page} follows."
    try:
        out = llm_json(payload["qc_model"], QC_PAGE_SYSTEM, user, images,
                       step=f"QC check: page {page} ({len(items)} field{'s' if len(items) > 1 else ''})")
    except Exception as e:  # the full checks still run
        logger.warning("Page check failed: %s", e)
        out = {}
    answers = {}
    for a in out.get("fields") or []:
        if isinstance(a, dict) and a.get("name"):
            answers[a["name"]] = clean_verdict(a)
    content = [{"type": "text", "text": user}] + [
        {"type": "image_url", "image_url": {"url": f"<page {page} as PNG, {QC_IMAGE_DPI} dpi>", "detail": "high"}}
        for _ in images]
    call = {"model": payload["qc_model"], "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": QC_PAGE_SYSTEM},
                         {"role": "user", "content": content if images else user}],
            "response": {"fields": list(answers.values())}}

    results, pending = [], []
    for it in items:
        spec, ex = it["spec"], it["extracted"] or {}
        verdict = answers.get(spec["name"]) or {}
        evidence_page = None
        if verdict.get("evidence_quote"):
            evidence_page, _ = idx.find_quote(verdict["evidence_quote"], [page])
        state = {"spec": spec, "extracted": ex, "verdict": verdict, "evidence_ok": evidence_page is not None,
                 "evidence_page": evidence_page, "notes": list(it["locate"].get("notes") or []),
                 "pages_checked": [page], "located_by": it["locate"].get("located_by", "citation"),
                 "citation_ok": it["locate"].get("citation_ok"), "qc_calls": [call]}
        result = qc_finalize(state)["result"] if verdict else None
        if result and result["status"] == PASS:
            result["notes"].append(f"Confirmed in one check of page {page} together with the other fields on it.")
            results.append(result)
        else:
            pending.append({"doc_id": payload["doc_id"], "file_path": payload["file_path"], "spec": spec,
                            "qc_model": payload["qc_model"], "extracted": ex, "qc_calls": [call],
                            "notes": [f"The check of page {page} didn't confirm this field, so it was checked on its own "
                                      "with the page image."]})
    return {"qc_results": results, "qc_pending": pending, "llm_calls": 1}


ABSENT_MAX_PAGES = 4  # pages read when confirming that empty fields really aren't in the document


def qc_absent(payload: dict) -> dict:
    """Fields the extractor left empty: search for each (an embedding and the local reranker, nearly
    free), then one text-only check of those pages for all of them. A field confirmed absent and not
    required is final; one the checker finds, or a required one, gets the full per-field check."""
    idx = _INDEXES[payload["doc_id"]]
    items = payload["items"]
    ranked: Dict[int, float] = {}
    for it in items:
        spec = it["spec"]
        query = f"{spec['name'].replace('_', ' ')} {spec.get('description', '')}".strip()
        for rank, hit in enumerate(idx.search(query, k=QC_SEARCH_PAGES, step=f"QC search: {spec['name']}")):
            ranked[hit["page"]] = min(ranked.get(hit["page"], 99), rank)
    pages = sorted(ranked, key=lambda p: (ranked[p], p))[:ABSENT_MAX_PAGES]
    if not pages:
        return {"qc_pending": items}
    brief = [{"name": it["spec"]["name"], "description": it["spec"].get("description") or "-",
              "type": it["spec"].get("type"), "extracted_value": None} for it in items]
    user = (f"The extractor found nothing for these fields. Check whether the pages contain them.\n\n"
            f"Fields to check:\n{json.dumps(brief, indent=2, ensure_ascii=False)}\n\n"
            f"Source pages:\n{pages_block(idx, pages)}")
    try:
        out = llm_json(payload["qc_model"], QC_PAGE_SYSTEM, user,
                       step=f"QC check: confirm {len(items)} empty field{'s' if len(items) > 1 else ''} absent")
    except Exception as e:
        logger.warning("Absence check failed: %s", e)
        out = {}
    answers = {a["name"]: clean_verdict(a) for a in out.get("fields") or [] if isinstance(a, dict) and a.get("name")}
    call = {"model": payload["qc_model"], "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": QC_PAGE_SYSTEM}, {"role": "user", "content": user}],
            "response": {"fields": list(answers.values())}}
    results, pending = [], []
    for it in items:
        spec, ex = it["spec"], it["extracted"] or {}
        verdict = answers.get(spec["name"]) or {}
        # "incorrect" with no value on an empty field is read as not found (see qc_finalize)
        absent = verdict.get("verdict") == "not_found" or (
            verdict.get("verdict") == "incorrect" and is_empty(verdict.get("correct_value")))
        if absent:
            # Not required: confirmed absent. Required: it's missing, which needs a person either way,
            # so it goes to Needs review without another, costlier check
            notes = ["Nothing was extracted; searched the document to confirm the field is absent.",
                     f"Checked together with the other empty fields on pages {', '.join(map(str, pages))}."]
            if spec.get("required"):
                notes.append("This field is required and wasn't found, so it needs your decision.")
            state = {"spec": spec, "extracted": ex, "verdict": {**verdict, "verdict": "not_found"}, "evidence_ok": False,
                     "evidence_page": None, "pages_checked": pages, "located_by": "search", "qc_calls": [call], "notes": notes}
            results.append(qc_finalize(state)["result"])
        else:
            pending.append({**it, "qc_calls": [call],
                            "notes": [f"The check of pages {', '.join(map(str, pages))} for empty fields "
                                      "found something or the field is required, so it was checked on its own."]})
    return {"qc_results": results, "qc_pending": pending, "llm_calls": 1}


def qc_direct(payload: dict) -> dict:
    """Fields Python couldn't place on a page (no value, or a quote not in the document) skip the page check."""
    return {"qc_pending": payload["items"]}


def followup_sends(state: PipelineState):
    pending = state.get("qc_pending") or []
    return [Send("qc_field", p) for p in pending] or "rules"


# -----------------------------
# RULES + REPORT
# -----------------------------
def parse_number(value: Any) -> Optional[float]:
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return None


def flag(result: dict, note: str) -> None:
    result["notes"].append(note)
    if result["status"] == PASS:
        result["status"] = REVIEW


def rules(state: PipelineState) -> dict:
    by_name = {r["field"]: r for r in state.get("qc_results", [])}
    results = []
    for spec in state["fields"]:
        r = by_name.get(spec["name"])
        if r is None:  # field not selected for QC
            ex = state["extraction"].get(spec["name"], {})
            r = {"field": spec["name"], "extracted_value": ex.get("value"), "extracted_page": ex.get("page"),
                 "extracted_quote": ex.get("quote"), "confidence": ex.get("confidence"),
                 "status": NOT_CHECKED, "pages_checked": [], "notes": []}
        r["label"] = spec.get("label") or ""
        r["type"] = spec.get("type", "string")
        r["final_value"] = r.get("correct_value") if r["status"] == FAIL else r.get("extracted_value")
        value = r["final_value"]

        if spec.get("required") and is_empty(value):
            flag(r, "Required field is empty.")
        elif not is_empty(value) and spec.get("type") == "number" and parse_number(value) is None:
            flag(r, f"Value '{value}' is not a valid number.")
        elif not is_empty(value) and spec.get("type") == "date":
            if pd.isna(pd.to_datetime(str(value), errors="coerce")) and \
                    pd.isna(pd.to_datetime(str(value), errors="coerce", dayfirst=True)):
                flag(r, f"Value '{value}' is not a valid date.")
        results.append(r)

    by_name = {r["field"]: r for r in results}
    for rule in state.get("rules", []):
        if rule.get("type") != "sum":
            continue
        parts = [parse_number(by_name.get(f, {}).get("final_value")) for f in rule["fields"]]
        total = parse_number(by_name.get(rule["equals"], {}).get("final_value"))
        if None in parts or total is None:
            continue
        if abs(sum(parts) - total) > rule.get("tolerance", 0.01):
            msg = f"Rule failed: {' + '.join(rule['fields'])} = {sum(parts):,.2f}, but {rule['equals']} = {total:,.2f}."
            for name in rule["fields"] + [rule["equals"]]:
                if name in by_name:
                    flag(by_name[name], msg)

    return {"final_results": results}


def report(state: PipelineState) -> dict:
    idx = _INDEXES[state["doc_id"]]
    results = state["final_results"]
    summary = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, REVIEW, NOT_CHECKED)}

    # Pages a human needs to open: for FAIL the evidence + the extractor's cited page,
    # for REVIEW everything the agent looked at
    review_pages = set()
    for r in results:
        if r["status"] == FAIL:
            review_pages.update(p for p in (r.get("evidence_page"), r.get("extracted_page")) if p)
        elif r["status"] == REVIEW:
            review_pages.update(r.get("pages_checked") or [])
    review_pages = sorted(review_pages)

    # Where each quote appears, so a reviewer can jump to every page that shows it
    for r in results:
        r["extracted_quote_pages"] = idx.pages_with(r.get("extracted_quote"))
        r["evidence_pages"] = idx.pages_with(r.get("evidence_quote")) if r.get("evidence_page") else []
    return {"report": {
        "doc_id": state["doc_id"],
        "file": Path(state["file_path"]).name,
        "num_pages": state["num_pages"],
        "ocr_pages": state.get("ocr_pages", []),
        "extraction_source": state.get("extraction_source"),
        "models": state["models"],
        "summary": summary,
        "llm_calls": state.get("llm_calls", 0),
        "pages_sent_to_qc": sum(len(r.get("pages_checked") or []) for r in results),
        "review_pages": review_pages,
        "seconds": round(time.time() - state["started_at"], 1),
        "data": {r["field"]: r["final_value"] for r in results},
        "results": results,
        # Text of every page a result points at, so a UI can show the source for any field
        "page_texts": {p: idx.page_text(p) for p in sorted(
            set(review_pages)
            | {r.get("evidence_page") for r in results if r.get("evidence_page")}
            | {r.get("extracted_page") for r in results if r.get("extracted_page")}
        ) if 1 <= p <= len(idx)},
    }}


# -----------------------------
# PIPELINE GRAPH
# -----------------------------
def qc_sends(state: PipelineState):
    """Python locates every field's quote first. Fields on the same page are checked together;
    fields it can't place go straight to the full per-field check."""
    if not state.get("run_qc", True):
        return "rules"
    wanted = state.get("qc_fields") or [f["name"] for f in state["fields"]]
    base = {"doc_id": state["doc_id"], "file_path": state["file_path"], "qc_model": state["models"]["qc"]}
    by_page: Dict[int, list] = {}
    direct, empty = [], []
    for f in state["fields"]:
        if f["name"] not in wanted:
            continue
        ex = state["extraction"].get(f["name"])
        loc = qc_locate({"doc_id": state["doc_id"], "extracted": ex, "notes": []})
        pages = loc.get("candidate_pages") or []
        if len(pages) == 1:
            by_page.setdefault(pages[0], []).append({"spec": f, "extracted": ex, "locate": loc})
        elif is_empty((ex or {}).get("value")):
            empty.append({**base, "spec": f, "extracted": ex})
        else:
            direct.append({**base, "spec": f, "extracted": ex})
    sends = []
    for page, items in sorted(by_page.items()):
        for i in range(0, len(items), PAGE_GROUP_MAX):
            sends.append(Send("qc_page", {**base, "page": page, "items": items[i:i + PAGE_GROUP_MAX],
                                          "ocr_pages": state.get("ocr_pages", [])}))
    if empty:
        sends.append(Send("qc_absent", {**base, "items": empty}))
    if direct:
        sends.append(Send("qc_direct", {"items": direct}))
    return sends or "rules"


def route_after_ingest(state: PipelineState):
    if state.get("extraction"):
        return qc_sends(state)
    return [Send("extract_batch", {"doc_id": state["doc_id"], "file_path": state["file_path"],
                                   "fields": state["fields"], "pages": pages, "model": state["models"]["extract"]})
            for pages in state["extract_jobs"]]


def build_pipeline():
    g = StateGraph(PipelineState)
    g.add_node("ingest", ingest)
    g.add_node("extract_batch", extract_batch)
    g.add_node("merge_extraction", merge_extraction)
    g.add_node("ground_extraction", ground_extraction)
    g.add_node("qc_page", qc_page)
    g.add_node("qc_direct", qc_direct)
    g.add_node("qc_absent", qc_absent)
    g.add_node("qc_followup", lambda state: {})
    g.add_node("qc_field", qc_field)
    g.add_node("rules", rules)
    g.add_node("report", report)
    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", route_after_ingest, ["extract_batch", "qc_page", "qc_direct", "qc_absent", "rules"])
    g.add_edge("extract_batch", "merge_extraction")
    g.add_edge("merge_extraction", "ground_extraction")
    g.add_conditional_edges("ground_extraction", qc_sends, ["qc_page", "qc_direct", "qc_absent", "rules"])
    # Page checks and direct fields meet here; whatever isn't confirmed gets the full per-field check
    g.add_edge("qc_page", "qc_followup")
    g.add_edge("qc_direct", "qc_followup")
    g.add_edge("qc_absent", "qc_followup")
    g.add_conditional_edges("qc_followup", followup_sends, ["qc_field", "rules"])
    g.add_edge("qc_field", "rules")
    g.add_edge("rules", "report")
    g.add_edge("report", END)
    return g.compile()


PIPELINE = build_pipeline()


def _initial_state(file_path, schema, extraction, qc_fields, run_qc, models) -> Dict[str, Any]:
    fields, rule_list = normalize_schema(schema)
    state: Dict[str, Any] = {"file_path": str(file_path), "fields": fields, "rules": rule_list,
                             "models": {**default_models(), **(models or {})},
                             "qc_fields": qc_fields, "run_qc": run_qc, "started_at": time.time()}
    if extraction is not None:
        state["extraction"] = normalize_extraction(extraction, fields)
        state["extraction_source"] = "supplied"
    return state


def stream_pipeline(file_path: str, schema: Any, extraction: Any = None, qc_fields: Optional[List[str]] = None,
                    run_qc: bool = True, models: Optional[Dict[str, str]] = None) -> Iterator[dict]:
    """
    Runs the pipeline and yields progress events:
      {"stage": str, "progress": 0..1}  while running
      {"report": {...}}                 at the end
    """
    state = _initial_state(file_path, schema, extraction, qc_fields, run_qc, models)
    n_fields = len(state["fields"]) if run_qc else 0
    n_batches, done_batches, done_fields = 1, 0, 0
    meter = start_meter()  # LangGraph copies this context into its worker threads
    finished: Dict[str, float] = {}  # node -> seconds since start when it last finished
    index_reused = False
    yield {"stage": "Reading document", "progress": 0.03}
    for update in PIPELINE.stream(state, {"max_concurrency": AGENT_MAX_CONCURRENCY}, stream_mode="updates"):
        for node, out in update.items():
            finished[node] = time.perf_counter() - meter.started
            if node == "ingest":
                index_reused = bool(out.get("index_reused"))
            if node == "ingest":
                n_batches = len(out.get("extract_jobs") or [1])
                stage = "Checking fields" if state.get("extraction") else "Extracting fields"
                yield {"stage": stage, "progress": 0.15}
            elif node == "extract_batch":
                done_batches += 1
                yield {"stage": f"Extracting fields ({done_batches}/{n_batches} page ranges)",
                       "progress": 0.15 + 0.35 * done_batches / n_batches}
            elif node == "merge_extraction":
                yield {"stage": "Verifying fields against the document", "progress": 0.5}
            elif node in ("qc_field", "qc_page", "qc_absent"):
                done_fields += 1 if node == "qc_field" else len(out.get("qc_results") or [])
                yield {"stage": f"Verifying fields ({done_fields}/{n_fields})",
                       "progress": 0.5 + 0.45 * done_fields / max(n_fields, 1)}
            elif node == "rules":
                yield {"stage": "Running rule checks", "progress": 0.97}
            elif node == "report":
                yield {"report": {**out["report"], "usage": meter.summary(),
                                  "timings": {"phases": phase_times(finished), "index_reused": index_reused}}}


PHASES = [("ingest", "Read pages, OCR and build the index"), ("merge_extraction", "Extraction"),
          ("ground_extraction", "Self-check"), ("rules", "QC checks"), ("report", "Rules and report")]


def phase_times(finished: Dict[str, float]) -> List[dict]:
    """Seconds per phase, from when each phase's last node finished. Phases that didn't run are left out."""
    out, last = [], 0.0
    for node, name in PHASES:
        if node in finished:
            out.append({"phase": name, "seconds": round(finished[node] - last, 2)})
            last = finished[node]
    return out


def run_pipeline(file_path: str, schema: Any, extraction: Any = None,
                 qc_fields: Optional[List[str]] = None, run_qc: bool = True,
                 models: Optional[Dict[str, str]] = None) -> dict:
    """
    schema:     {"fields": [{name, description, type, required}], "rules": [...]} or a list of fields.
    extraction: optional output of another extractor. If omitted, OpenAI extraction runs.
    qc_fields:  optional subset of field names to audit (default: all).
    """
    for event in stream_pipeline(file_path, schema, extraction, qc_fields, run_qc, models):
        if "report" in event:
            return event["report"]
    raise RuntimeError("Pipeline finished without a report")

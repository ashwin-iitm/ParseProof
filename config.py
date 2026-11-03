import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import logging

# -----------------------------
# CONFIG
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
DIMS = 1536  # embedding dims for text-embedding-3-small

# Reranker for QC search: a small cross-encoder that runs locally
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Extraction + QC agents (agents.py)
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "gpt-4.1")  # reads PDFs natively (text + page images)
QC_MODEL = os.getenv("QC_MODEL", "gpt-4.1-mini")  # a separate, cheaper model checks the extractor; gpt-4o catches more for ~6x the price
OCR_MODEL = os.getenv("OCR_MODEL", "gpt-4.1-mini")  # transcribes scanned pages so QC can search them
EXTRACT_PAGES_PER_CALL = int(os.getenv("EXTRACT_PAGES_PER_CALL", 40))  # PDF pages sent per extraction call
EXTRACT_BATCH_CHARS = int(os.getenv("EXTRACT_BATCH_CHARS", 40000))  # page text per call for non-PDF files
QC_SEARCH_PAGES = int(os.getenv("QC_SEARCH_PAGES", 3))  # pages sent to the QC LLM when it has to search
QUOTE_MATCH_THRESHOLD = int(os.getenv("QUOTE_MATCH_THRESHOLD", 85))  # fuzzy score (0-100) to accept a quote
AGENT_MAX_CONCURRENCY = int(os.getenv("AGENT_MAX_CONCURRENCY", 8))

# Product data (server.py): SQLite database, stored documents, saved RAG indexes
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
INDEX_DIR = DATA_DIR / "indexes"
DOCUMENT_DIR = DATA_DIR / "documents"
for _d in (INDEX_DIR, DOCUMENT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parseproof")

# -----------------------------
# OPENAI CLIENT
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not found in environment. Set it before running.")

# A placeholder keeps the app bootable without a key; the settings page can set one later
# Short default timeout so a stalled connection is retried quickly (the SDK default is 10 minutes);
# long document extraction calls pass their own timeout
client = OpenAI(api_key=OPENAI_API_KEY or "not-configured", timeout=60, max_retries=3)


def set_openai_key(key: str) -> None:
    """Update the key everywhere at runtime (modules hold a reference to the same client)."""
    global OPENAI_API_KEY
    OPENAI_API_KEY = key
    os.environ["OPENAI_API_KEY"] = key
    client.api_key = key


# -----------------------------
# TOKEN METER (per run)
# -----------------------------
import contextvars
import threading
import time
from typing import Optional

_METER: contextvars.ContextVar = contextvars.ContextVar("usage_meter", default=None)


class UsageMeter:
    """Records every model call made while it is active (one per run): OpenAI calls with their
    tokens, and the local reranker with none. Totals per model are added up from the calls."""

    def __init__(self):
        self._lock = threading.Lock()
        self.started = time.perf_counter()
        self.calls: list = []

    def add(self, model: str, input_tokens: int, output_tokens: int, seconds: float = 0.0,
            step: str = "", detail: Optional[str] = None) -> None:
        end = time.perf_counter() - self.started
        with self._lock:
            self.calls.append({"step": step, "model": model, "input": input_tokens, "output": output_tokens,
                               "seconds": round(seconds, 2), "at": round(max(end - seconds, 0.0), 2),
                               "detail": detail})

    def summary(self) -> dict:
        with self._lock:
            calls = sorted(self.calls, key=lambda c: c["at"])
        models: dict = {}
        for c in calls:
            m = models.setdefault(c["model"], {"calls": 0, "input": 0, "output": 0, "seconds": 0.0})
            m["calls"] += 1
            m["input"] += c["input"]
            m["output"] += c["output"]
            m["seconds"] = round(m["seconds"] + c["seconds"], 2)
        models = {k: {**v, "total": v["input"] + v["output"]} for k, v in models.items()}
        return {"input": sum(m["input"] for m in models.values()),
                "output": sum(m["output"] for m in models.values()),
                "total": sum(m["total"] for m in models.values()),
                "models": models, "calls": [{"n": i + 1, **c} for i, c in enumerate(calls)]}


def start_meter() -> "UsageMeter":
    meter = UsageMeter()
    _METER.set(meter)
    return meter


def record_usage(model: str, usage, step: str = "", seconds: float = 0.0, detail: Optional[str] = None) -> None:
    """Responses API reports input/output_tokens; chat and embeddings report prompt/completion_tokens."""
    meter = _METER.get()
    if meter is None or usage is None:
        return
    inp = getattr(usage, "input_tokens", None)
    if inp is None:
        inp = getattr(usage, "prompt_tokens", 0)
    out = getattr(usage, "output_tokens", None)
    if out is None:
        out = getattr(usage, "completion_tokens", 0) or 0
    meter.add(model, int(inp or 0), int(out or 0), seconds, step, detail)


def record_local(model: str, seconds: float, step: str, detail: Optional[str] = None) -> None:
    """A model that runs on this computer (the reranker): no tokens, no cost, but it takes time."""
    meter = _METER.get()
    if meter is not None:
        meter.add(model, 0, 0, seconds, step, detail)


# -----------------------------
# PRICES (USD per 1M tokens, OpenAI standard tier)
# -----------------------------
# From https://developers.openai.com/api/docs/pricing on 2026-11-03. Update here when OpenAI
# changes them; costs are worked out when a run is shown, so old runs use the new prices too.
PRICES_CHECKED = "2026-11-03"
PRICES = {
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    # Runs on this computer, so it costs nothing
    RERANKER_MODEL: {"input": 0.0, "output": 0.0},
}
LOCAL_MODELS = {RERANKER_MODEL}


def usage_cost(usage: dict) -> dict:
    """Adds cost_usd to each model and a total. A model missing from PRICES gets None, and the
    total then only covers the priced ones (priced_all says whether that is everything)."""
    models, total, priced_all = {}, 0.0, True
    for name, m in (usage.get("models") or {}).items():
        price = PRICES.get(name)
        cost = None if price is None else (m["input"] * price["input"] + m["output"] * price["output"]) / 1e6
        if cost is None:
            priced_all = False
        else:
            total += cost
        models[name] = {**m, "cost_usd": cost, "local": name in LOCAL_MODELS}
    calls = []
    for c in usage.get("calls") or []:
        price = PRICES.get(c["model"])
        cost = None if price is None else (c["input"] * price["input"] + c["output"] * price["output"]) / 1e6
        calls.append({**c, "cost_usd": cost, "local": c["model"] in LOCAL_MODELS})
    return {**usage, "models": models, "calls": calls, "cost_usd": total, "priced_all": priced_all,
            "prices_checked": PRICES_CHECKED}

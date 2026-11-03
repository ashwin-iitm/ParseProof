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
MAX_CHARS = int(os.getenv("MAX_CHARS", 1000))
OVERLAP_CHARS = int(os.getenv("OVERLAP_CHARS", 200))

# Reranker model (used for reranking candidates, not gating)
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Relevance threshold - FAISS vector similarity threshold for "relatedness"
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", 0.15))  # Option A

# QA model to call - you requested gpt-4o-mini ("40 MINI")
QA_MODEL = os.getenv("QA_MODEL", "gpt-4o-mini")

# Extraction + QC agents (agents.py)
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "gpt-4.1")  # reads PDFs natively (text + page images)
QC_MODEL = os.getenv("QC_MODEL", "gpt-4o")  # a different model than the extractor catches different mistakes
OCR_MODEL = os.getenv("OCR_MODEL", "gpt-4.1-mini")  # transcribes scanned pages so QC can search them
EXTRACT_PAGES_PER_CALL = int(os.getenv("EXTRACT_PAGES_PER_CALL", 40))  # PDF pages sent per extraction call
EXTRACT_BATCH_CHARS = int(os.getenv("EXTRACT_BATCH_CHARS", 40000))  # page text per call for non-PDF files
QC_SEARCH_PAGES = int(os.getenv("QC_SEARCH_PAGES", 3))  # pages sent to the QC LLM when it has to search
QUOTE_MATCH_THRESHOLD = int(os.getenv("QUOTE_MATCH_THRESHOLD", 85))  # fuzzy score (0-100) to accept a quote
AGENT_MAX_CONCURRENCY = int(os.getenv("AGENT_MAX_CONCURRENCY", 8))
REPORT_DIR = Path(os.getenv("REPORT_DIR", BASE_DIR / "reports"))

# Product data (server.py): SQLite database, stored documents, saved RAG indexes
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
INDEX_DIR = DATA_DIR / "indexes"
DOCUMENT_DIR = DATA_DIR / "documents"
for _d in (INDEX_DIR, DOCUMENT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Upload directory and key file
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
KEY_FILE = Path(os.getenv("FERNET_KEY_FILE", BASE_DIR / "secret.key"))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("secure-rag")

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

_METER: contextvars.ContextVar = contextvars.ContextVar("usage_meter", default=None)


class UsageMeter:
    """Adds up the tokens of every OpenAI call made while it is active (one per run)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.models = {}

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            m = self.models.setdefault(model, {"calls": 0, "input": 0, "output": 0})
            m["calls"] += 1
            m["input"] += input_tokens
            m["output"] += output_tokens

    def summary(self) -> dict:
        with self._lock:
            models = {k: {**v, "total": v["input"] + v["output"]} for k, v in self.models.items()}
        return {"input": sum(m["input"] for m in models.values()),
                "output": sum(m["output"] for m in models.values()),
                "total": sum(m["total"] for m in models.values()),
                "models": models}


def start_meter() -> "UsageMeter":
    meter = UsageMeter()
    _METER.set(meter)
    return meter


def record_usage(model: str, usage) -> None:
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
    meter.add(model, int(inp or 0), int(out or 0))

import pandas as pd
from pathlib import Path
from typing import List, Tuple
from config import logger, MAX_CHARS, OVERLAP_CHARS

# Optional imports (graceful)
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import docx  # python-docx
except Exception:
    docx = None

# tiktoken optional
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except Exception:
    TIKTOKEN_AVAILABLE = False

# -----------------------------
# FILE TEXT EXTRACTION
# -----------------------------
def extract_text_from_file(file_path: Path) -> List[str]:
    ext = file_path.suffix.lower()
    logger.info(f"Extracting text from {file_path} (ext={ext})")

    if ext == ".txt":
        return [file_path.read_text(encoding="utf-8", errors="ignore")]

    if ext in [".csv", ".xls", ".xlsx"]:
        if ext in [".xls", ".xlsx"]:
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)
        rows = df.astype(str).apply(lambda r: " | ".join(r), axis=1).tolist()
        return rows or [""]

    if ext == ".docx":
        if docx is None:
            raise ValueError("python-docx not installed")
        doc = docx.Document(file_path)
        paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        return paras or [""]

    if ext == ".pdf":
        if fitz is None:
            raise ValueError("PyMuPDF (fitz) not installed")
        doc = fitz.open(file_path)
        pages = []
        for p in doc:
            try:
                # Text blocks top-to-bottom, left-to-right. The stored order can split an
                # address (name in one place, street lines in another), and plain line sorting
                # interleaves side-by-side columns; blocks keep each column's lines together.
                blocks = sorted((b for b in p.get_text("blocks") if b[6] == 0), key=lambda b: (round(b[1]), b[0]))
                pages.append("\n".join(b[4].strip("\n") for b in blocks))
            except Exception as e:
                logger.exception("Error extracting PDF page: %s", e)
                pages.append("")
        return pages or [""]

    raise ValueError(f"Unsupported file type: {ext}")

# -----------------------------
# TEXT CHUNKING (RECURSIVE)
# -----------------------------
def recursive_chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> List[str]:
    separators = ["\n\n", "\n", ". ", " ", ""]

    def split_with_seps(s: str, seps: List[str]) -> List[str]:
        if not seps:
            out = []
            step = max_chars - overlap if max_chars > overlap else max_chars
            for i in range(0, len(s), step):
                out.append(s[i:i + max_chars])
            return out

        sep = seps[0]
        parts = s.split(sep)
        chunks = []
        cur_parts = []
        cur_len = 0

        for part in parts:
            part_len = len(part)
            additional = (len(sep) if cur_parts else 0)
            if cur_len + part_len + additional > max_chars:
                if cur_parts:
                    chunks.append(sep.join(cur_parts))
                cur_parts = [part]
                cur_len = part_len
            else:
                cur_parts.append(part)
                cur_len += part_len + additional

        if cur_parts:
            chunks.append(sep.join(cur_parts))

        verified = []
        for c in chunks:
            if len(c) > max_chars:
                verified.extend(split_with_seps(c, seps[1:]))
            else:
                verified.append(c)
        return verified

    return split_with_seps(text, separators)

def chunk_texts(pages: List[str]) -> Tuple[List[str], List[dict]]:
    combined = "\n\n".join([f"[PAGE:{i+1}]\n{p}" for i, p in enumerate(pages)])
    raw_chunks = recursive_chunk_text(combined, MAX_CHARS, OVERLAP_CHARS)
    chunks = []
    metadata = []
    for i, c in enumerate(raw_chunks):
        est_page = 1
        pos = c.find("[PAGE:")
        if pos != -1:
            try:
                est_page = int(c[pos + 6: c.find("]", pos)])
            except Exception:
                pass
        chunks.append(c)
        metadata.append({"start_pos": i, "estimated_page": est_page})
    return chunks, metadata

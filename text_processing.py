import pandas as pd
from pathlib import Path
from typing import List
from config import logger

# Optional imports (graceful)
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import docx  # python-docx
except Exception:
    docx = None


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

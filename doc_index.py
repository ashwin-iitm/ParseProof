"""
doc_index.py — page-level hybrid index shared by the extraction and QC agents.

Every page is one retrieval unit, so QC can always point to an exact page.
Retrieval = FAISS + BM25 -> RRF -> cross-encoder.
"""

import json
import re
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz

from config import client, record_local, record_usage, EMBED_MODEL, QUOTE_MATCH_THRESHOLD, RERANKER_MODEL
from vector_store import create_embeddings, build_faiss_index, RERANKER

RRF_K = 60
EMBED_CHARS = 24000   # keep a page under the embedding model's token limit
RERANK_WINDOW = 1500  # cross-encoder sees ~512 tokens, so score pages in windows
RERANK_OVERLAP = 300


def tokenize(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


class PageIndex:
    def __init__(self, pages: List[str]):
        self.pages = [p or "" for p in pages]
        texts = [p[:EMBED_CHARS] if p.strip() else "[empty page]" for p in self.pages]
        self.faiss = build_faiss_index(create_embeddings(texts))
        self._prepare()

    def _prepare(self) -> None:
        self._norm = [normalize(p) for p in self.pages]
        self.bm25 = BM25Okapi([tokenize(p) or ["_"] for p in self.pages])

    # Saved per document so a server restart doesn't re-embed (embeddings cost money)
    @staticmethod
    def exists(folder: Path) -> bool:
        return (folder / "pages.json").exists() and (folder / "pages.faiss").exists()

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pages.json").write_text(json.dumps(self.pages), encoding="utf-8")
        faiss.write_index(self.faiss, str(folder / "pages.faiss"))

    @classmethod
    def load(cls, folder: Path) -> "PageIndex":
        obj = cls.__new__(cls)
        obj.pages = json.loads((folder / "pages.json").read_text(encoding="utf-8"))
        obj.faiss = faiss.read_index(str(folder / "pages.faiss"))
        obj._prepare()
        return obj

    def __len__(self) -> int:
        return len(self.pages)

    def page_text(self, page_no: int) -> str:
        """1-based page number."""
        return self.pages[page_no - 1] if 1 <= page_no <= len(self.pages) else ""

    def search(self, query: str, k: int = 3, candidates: int = 10, step: str = "Search") -> List[dict]:
        """Return the k most relevant pages as [{"page": 1-based, "score": float}]."""
        n = len(self.pages)
        if n == 0:
            return []

        t = time.perf_counter()
        resp = client.embeddings.create(model=EMBED_MODEL, input=[query])
        record_usage(EMBED_MODEL, resp.usage, f"{step}: embed the question", time.perf_counter() - t)
        q_emb = np.array(resp.data[0].embedding, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(q_emb)
        _, I = self.faiss.search(q_emb, min(candidates, n))
        vec_rank = [int(i) for i in I[0] if i >= 0]  # FAISS pads missing results with -1

        bm_scores = self.bm25.get_scores(tokenize(query))
        bm_rank = [int(i) for i in np.argsort(bm_scores)[::-1][:candidates] if bm_scores[i] > 0]

        combined = {}
        for ranking in (vec_rank, bm_rank):
            for rank, i in enumerate(ranking):
                combined[i] = combined.get(i, 0) + 1 / (RRF_K + rank + 1)
        top = sorted(combined, key=combined.get, reverse=True)[:candidates]
        if not top:
            return []

        # Page score = best cross-encoder score over its windows
        pairs, owners = [], []
        stride = RERANK_WINDOW - RERANK_OVERLAP
        for i in top:
            text = self.pages[i] or " "
            for start in range(0, max(len(text), 1), stride):
                pairs.append([query, text[start:start + RERANK_WINDOW]])
                owners.append(i)
                if start + RERANK_WINDOW >= len(text):
                    break
        t = time.perf_counter()
        scores = RERANKER.predict(pairs)
        record_local(RERANKER_MODEL, time.perf_counter() - t, f"{step}: rerank",
                     f"{len(top)} pages, {len(pairs)} windows")
        best = {}
        for i, s in zip(owners, scores):
            best[i] = max(best.get(i, float("-inf")), float(s))

        ranked = sorted(best.items(), key=lambda x: x[1], reverse=True)[:k]
        return [{"page": i + 1, "score": s} for i, s in ranked]

    def find_quote(self, quote: Optional[str], pages: Optional[Sequence[int]] = None,
                   threshold: int = QUOTE_MATCH_THRESHOLD) -> Tuple[Optional[int], float]:
        """Fuzzy-locate a verbatim quote. Returns (page or None if below threshold, best score)."""
        q = normalize(quote or "")
        if len(q) < 3:
            return None, 0.0
        candidates = [p for p in (pages or range(1, len(self.pages) + 1)) if 1 <= p <= len(self.pages)]
        best_page, best_score = None, 0.0
        for p in candidates:
            score = fuzz.partial_ratio(q, self._norm[p - 1])
            if score > best_score:
                best_page, best_score = p, score
        if best_score >= threshold:
            return best_page, best_score
        # A quote can span lines that the page text doesn't keep together (a multi-line address
        # next to another column). Accept it when every piece is on one page.
        for p in candidates:
            if segments_on_page(q, self._norm[p - 1]) or words_in_order(q, self._norm[p - 1]):
                return p, float(threshold)
        return None, best_score

    def pages_with(self, quote: Optional[str], threshold: int = QUOTE_MATCH_THRESHOLD) -> List[int]:
        """Every page the quote is on (a name or address printed in each page's header)."""
        q = normalize(quote or "")
        if len(q) < 3:
            return []
        return [i + 1 for i, page in enumerate(self._norm)
                if fuzz.partial_ratio(q, page) >= threshold or segments_on_page(q, page) or words_in_order(q, page)]


def words_in_order(q: str, page: str, max_gap: int = 8) -> bool:
    """All words of the quote occur on the page in the same order, with only a few other words
    between them. Catches a block whose lines the PDF text interleaves with another column
    ("12 Lake Street Account Status Active Green Park ..."). Needs at least 4 words."""
    qt, pt = tokenize(q), tokenize(page)
    if len(qt) < 4:
        return False
    for start in (i for i, t in enumerate(pt) if t == qt[0]):
        at = start
        for word in qt[1:]:
            nxt = next((j for j in range(at + 1, min(at + 2 + max_gap, len(pt))) if pt[j] == word), None)
            if nxt is None:
                break
            at = nxt
        else:
            return True
    return False


def segments_on_page(q: str, page: str) -> bool:
    """Every comma/line segment of the quote occurs on the page and together they cover ~all of it."""
    parts = [s.strip() for s in re.split(r"[,\n;|]|\s{2,}", q)]
    parts = [s for s in parts if len(s) >= 3]
    if len(parts) < 2:
        return False
    covered = sum(len(s) for s in parts if s in page)
    return all(s in page for s in parts) and covered >= 0.85 * len(q.replace(" ", "").replace(",", ""))

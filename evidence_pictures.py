"""
evidence_pictures.py — a picture of where each value came from, for the Excel export.

For a value with an evidence page and quote, the quote is found on the PDF page and the band of
the page around it is rendered with the quote highlighted, full page width, so a table row shows
every column. A page without a text layer (a scan) is shown whole, since there is nothing to find.
"""

import io
import re
from typing import Any, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

DPI = 110
SCAN_DPI = 60
ABOVE, BELOW = 90, 36   # points of page kept above and below the quote (column headers, the next row)
MAX_GAP = 8             # other words allowed between two quote words (text interleaved with another column)
QUOTE_FILL, QUOTE_LINE = (255, 214, 0, 60), (230, 170, 0, 255)    # the quote: light yellow
VALUE_FILL, VALUE_LINE = (255, 170, 0, 110), (200, 90, 0, 255)    # the value inside it: stronger


def _tokens(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


Words = List[Tuple[fitz.Rect, str]]


def _words(page: fitz.Page, textpage: fitz.TextPage) -> Words:
    """Every token on the page with the box of the word it is in ("$862,938" gives 862 and 938)."""
    return [(fitz.Rect(w[:4]), t) for w in page.get_text("words", textpage=textpage) for t in _tokens(w[4])]


def _word_run(words: Words, quote: str) -> List[fitz.Rect]:
    """The page words that spell the whole quote in order, with a few other words allowed between them
    (a block whose lines the PDF interleaves with another column)."""
    qt = _tokens(quote)
    for start, (_, t) in enumerate(words):
        if not qt or t != qt[0]:
            continue
        rects, at = [words[start][0]], start
        for want in qt[1:]:
            nxt = next((j for j in range(at + 1, min(at + 2 + MAX_GAP, len(words))) if words[j][1] == want), None)
            if nxt is None:
                break
            rects.append(words[nxt][0])
            at = nxt
        else:
            return rects
    return []


def _value_cell(words: Words, value: str, quote: str, field: str) -> List[fitz.Rect]:
    """Where the value itself is printed. A table quote ("Totals Claims 71") is read across the
    header and the row, so its words aren't together on the page. When the value is printed more
    than once ($282,627 under both Reserve and Incurred), take the one nearest a word of the field's
    name (the "Incurred" column header for "Largest claim incurred"), then nearest the quote's words."""
    vt = _tokens(value)
    if not vt:
        return []
    found = [[r for r, _ in words[i:i + len(vt)]] for i in range(len(words) - len(vt) + 1)
             if [t for _, t in words[i:i + len(vt)]] == vt]
    if len(found) < 2:
        return found[0] if found else []
    hints = {t for t in _tokens(field) if len(t) >= 3} - set(vt)
    labels = set(_tokens(quote)) - set(vt)

    def gap(c: fitz.Rect, label: str) -> Optional[float]:
        near = [abs(r.x0 - c.x0) + abs(r.y0 - c.y0) for r, t in words if t == label]
        return min(near) if near else None

    def distance(rects: List[fitz.Rect]) -> Tuple[float, float]:
        c = rects[0]
        to_field = [d for d in (gap(c, h) for h in hints) if d is not None]
        return (min(to_field) if to_field else 0.0, sum(gap(c, label) or 0.0 for label in labels))

    return min(found, key=distance)


def locate(page: fitz.Page, textpage: fitz.TextPage, words: Words, quote: Optional[str], value: Any = None,
           field: str = "") -> Tuple[List[fitz.Rect], List[fitz.Rect]]:
    """(quote boxes, value boxes) on the page. The value is marked on its own when it is part of the
    quote, or when the quote can't be found; both are empty when neither is on the page."""
    flat = re.sub(r"\s+", " ", str(quote or "")).strip()
    vt = _tokens(str(value)) if value not in (None, "") else []
    quote_rects = _quote(page, textpage, words, quote)
    in_quote = set(vt) <= set(_tokens(flat))
    value_rects = _value_cell(words, str(value), flat, field) if vt and (in_quote or not quote_rects) else []
    return quote_rects, value_rects


def _quote(page: fitz.Page, textpage: fitz.TextPage, words: Words, quote: Optional[str]) -> List[fitz.Rect]:
    """Boxes covering the quote: the exact text, its pieces, or its words in order."""
    raw = str(quote or "")
    flat = re.sub(r"\s+", " ", raw).strip()
    if len(flat) >= 2:
        hits = page.search_for(flat, textpage=textpage)
        if hits:
            return hits
        # A quote shortened with "..." or spanning lines the PDF keeps apart: find each piece
        pieces = [p.strip() for p in re.split(r"\.\.\.|…|\n|\s\|\s|\s{3,}", raw) if len(p.strip()) >= 3]
        if len(pieces) > 1:
            found = [hits[0] for hits in (page.search_for(p, textpage=textpage) for p in pieces) if hits]
            if 2 * len(found) >= len(pieces):
                return found
    return _word_run(words, flat)


class Pictures:
    """One open PDF. Each page's text is read once, however many fields cite it."""

    def __init__(self, path: str):
        self.doc = fitz.open(path)
        self._pages: dict = {}
        self._whole: dict = {}

    def __enter__(self) -> "Pictures":
        return self

    def __exit__(self, *_) -> None:
        self.doc.close()

    def _page(self, page_no: int) -> Tuple[fitz.Page, Optional[fitz.TextPage], Words]:
        if page_no not in self._pages:
            page = self.doc[page_no - 1]
            textpage = page.get_textpage()
            if textpage.extractText().strip():
                self._pages[page_no] = page, textpage, _words(page, textpage)
            else:
                self._pages[page_no] = page, None, []
        return self._pages[page_no]

    def picture(self, page_no: int, quote: Optional[str], value: Any = None,
                field: str = "") -> Optional[Tuple[bytes, int, int, bool]]:
        """(PNG bytes, width px, height px, found) for the quote's page, or None if the page doesn't exist."""
        if not page_no or not 1 <= page_no <= self.doc.page_count:
            return None
        page, textpage, words = self._page(page_no)
        quote_rects, value_rects = locate(page, textpage, words, quote, value, field) if textpage else ([], [])
        rects = quote_rects + value_rects
        if not rects:
            if page_no not in self._whole:
                pix = page.get_pixmap(dpi=SCAN_DPI)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                self._whole[page_no] = _png(img), img.width, img.height, False
            return self._whole[page_no]

        box = fitz.Rect(rects[0])
        for r in rects[1:]:
            box |= r
        full = page.rect
        clip = fitz.Rect(full.x0, max(full.y0, box.y0 - ABOVE), full.x1, min(full.y1, box.y1 + BELOW))
        pix = page.get_pixmap(dpi=DPI, clip=clip)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
        scale = DPI / 72
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for group, fill, line, width in ((quote_rects, QUOTE_FILL, QUOTE_LINE, 1),
                                         (value_rects, VALUE_FILL, VALUE_LINE, 3)):
            for r in group:
                x0, y0 = (r.x0 - clip.x0) * scale - 2, (r.y0 - clip.y0) * scale - 2
                x1, y1 = (r.x1 - clip.x0) * scale + 2, (r.y1 - clip.y0) * scale + 2
                draw.rectangle([x0, y0, x1, y1], fill=fill, outline=line, width=width)
        img = Image.alpha_composite(img, overlay).convert("RGB")
        return _png(img), img.width, img.height, True


def _png(img: Image.Image) -> bytes:
    # A page picture is mostly white and black text: 64 colours keeps it sharp at a fraction of the size
    buf = io.BytesIO()
    img.quantize(colors=64, method=Image.Quantize.FASTOCTREE).save(buf, "PNG")
    return buf.getvalue()

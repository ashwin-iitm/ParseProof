import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import { Spinner } from "@/components/ui";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

interface Props {
  url: string;
  isPdf: boolean;
  page: number;
  numPages: number;
  onPageChange: (page: number) => void;
  highlights: (string | null | undefined)[];
  pageTexts?: Record<string, string>;
}

/**
 * pdf.js splits a line into several text items (often one per word), so a quote is matched
 * against the page's whole text with whitespace removed, then every item it covers is marked.
 */
function findQuoteItems(items: object[], quotes: string[]): Set<number> {
  type Item = { str?: string; transform?: number[] };
  const all = items.map((item, i) => ({ i, item: item as Item })).filter(({ item }) => "str" in item);
  // Stored order first; then visual order (top-to-bottom, left-to-right), because the server
  // reads pages in visual order and the PDF may store a block's lines far apart
  const visual = [...all].sort((a, b) => {
    const [ay, ax] = [a.item.transform?.[5] ?? 0, a.item.transform?.[4] ?? 0];
    const [by, bx] = [b.item.transform?.[5] ?? 0, b.item.transform?.[4] ?? 0];
    return Math.abs(by - ay) > 2 ? by - ay : ax - bx;
  });
  const marked = new Set<number>();
  for (const quote of quotes) {
    const q = quote.toLowerCase().replace(/\s+/g, "");
    if (q.length < 3) continue;
    for (const order of [all, visual]) {
      let text = "";
      const owner: number[] = [];
      for (const { i, item } of order) {
        const s = String(item.str).toLowerCase().replace(/\s+/g, "");
        for (let k = 0; k < s.length; k++) owner.push(i);
        text += s;
      }
      let found = false;
      for (let at = text.indexOf(q); at >= 0; at = text.indexOf(q, at + q.length)) {
        found = true;
        for (let k = at; k < at + q.length; k++) marked.add(owner[k]);
      }
      if (found) break;
    }
    if (marked.size === 0) markSegments(all, quote, marked);
  }
  return marked;
}

/** Fallback for quotes spanning lines that the PDF stores apart: mark each comma/line segment. */
function markSegments(all: { i: number; item: { str?: string } }[], quote: string, marked: Set<number>) {
  let text = "";
  const owner: number[] = [];
  for (const { i, item } of all) {
    const s = String(item.str).toLowerCase().replace(/\s+/g, "");
    for (let k = 0; k < s.length; k++) owner.push(i);
    text += s;
  }
  for (const seg of quote.toLowerCase().split(/[,\n;|]|\s{2,}/)) {
    const s = seg.replace(/\s+/g, "");
    if (s.length < 4 && !(/\d/.test(s) && s.length >= 3)) continue;
    const at = text.indexOf(s);
    if (at >= 0) for (let k = at; k < at + s.length; k++) marked.add(owner[k]);
  }
}

function highlightText(text: string, quotes: string[]) {
  const patterns = quotes
    .filter((q) => q && q.trim().length > 2)
    .map((q) => q.trim().split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+"));
  if (!patterns.length) return text;
  const parts = text.split(new RegExp(`(${patterns.join("|")})`, "gi"));
  return parts.map((p, i) =>
    i % 2 ? (
      <mark key={i} className="rounded-sm bg-mark px-0.5 text-ink">
        {p}
      </mark>
    ) : (
      p
    ),
  );
}

export default function DocumentViewer({ url, isPdf, page, numPages, onPageChange, highlights, pageTexts }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [zoom, setZoom] = useState(1);
  const [pdfPages, setPdfPages] = useState<number>(numPages);
  const quotes = useMemo(() => highlights.filter((q): q is string => !!q), [highlights]);
  const quoteKey = quotes.join("|");
  // The page's text items, kept so a new field on the same page only re-marks the text layer
  // instead of painting the whole page again (slow on statements full of table lines)
  const [items, setItems] = useState<{ page: number; items: object[] } | null>(null);
  const [locked, setLocked] = useState(false);
  const marked = useMemo(
    () => (items && items.page === page ? findQuoteItems(items.items, quotes) : new Set<number>()),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, page, quoteKey],
  );
  const onText = useCallback((content: { items: object[] }) => setItems({ page, items: content.items }), [page]);
  const renderer = useCallback(
    ({ str, itemIndex }: { str: string; itemIndex: number }) => (marked.has(itemIndex) ? `<mark>${esc(str)}</mark>` : esc(str)),
    [marked],
  );
  const total = isPdf ? pdfPages || numPages : numPages;

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, Math.min(e.contentRect.width - 48, 920))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const scrollToMark = useCallback(() => {
    const mark = scroller.current?.querySelector("mark");
    if (mark) mark.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (!isPdf) requestAnimationFrame(scrollToMark);
  }, [isPdf, page, quotes, scrollToMark]);

  const go = (p: number) => onPageChange(Math.min(Math.max(1, p), total || 1));

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#e9e7e1]">
      <div className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-line bg-panel px-3">
        <div className="flex items-center gap-1">
          <button className="rounded p-1.5 text-ink-2 hover:bg-ink/5 hover:text-ink disabled:opacity-40" onClick={() => go(page - 1)} disabled={page <= 1} aria-label="Previous page">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[88px] text-center text-sm text-ink-2">
            Page <span className="font-medium text-ink">{page}</span> of {total || "–"}
          </span>
          <button className="rounded p-1.5 text-ink-2 hover:bg-ink/5 hover:text-ink disabled:opacity-40" onClick={() => go(page + 1)} disabled={!!total && page >= total} aria-label="Next page">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        {isPdf && (
          <div className="flex items-center gap-1">
            <button className="rounded p-1.5 text-ink-2 hover:bg-ink/5 hover:text-ink disabled:opacity-40" onClick={() => setZoom((z) => Math.max(0.6, +(z - 0.15).toFixed(2)))} disabled={zoom <= 0.6} aria-label="Zoom out">
              <Minus className="h-4 w-4" />
            </button>
            <button className="min-w-[48px] rounded px-1 py-1 text-center text-xs text-ink-2 hover:bg-ink/5" onClick={() => setZoom(1)} title="Fit width">
              {Math.round(zoom * 100)}%
            </button>
            <button className="rounded p-1.5 text-ink-2 hover:bg-ink/5 hover:text-ink disabled:opacity-40" onClick={() => setZoom((z) => Math.min(2.5, +(z + 0.15).toFixed(2)))} disabled={zoom >= 2.5} aria-label="Zoom in">
              <Plus className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <div ref={scroller} className="min-h-0 flex-1 overflow-auto px-6 py-6">
        {isPdf ? (
          locked ? (
            <p className="py-16 text-center text-sm text-fail">This PDF is password-protected, so it can't be shown here. Upload an unlocked copy.</p>
          ) : (
          <Document
            file={url}
            onLoadSuccess={(pdf) => setPdfPages(pdf.numPages)}
            onPassword={() => setLocked(true)}
            loading={<div className="flex h-64 items-center justify-center"><Spinner /></div>}
            error={<p className="py-16 text-center text-sm text-fail">The PDF could not be displayed.</p>}
            className="flex justify-center"
          >
            <Page
              key={page}
              pageNumber={page}
              width={width * zoom}
              devicePixelRatio={Math.min(2, window.devicePixelRatio || 1)}
              renderAnnotationLayer={false}
              onGetTextSuccess={onText}
              customTextRenderer={renderer}
              onRenderTextLayerSuccess={scrollToMark}
              loading={<div style={{ width: width * zoom, height: width * zoom * 1.3 }} className="bg-surface" />}
              className="shadow-[0_1px_3px_rgb(27_29_33/0.12),0_8px_24px_rgb(27_29_33/0.08)]"
            />
          </Document>
          )
        ) : (
          <div className="mx-auto max-w-[820px] bg-surface px-10 py-10 shadow-[0_1px_3px_rgb(27_29_33/0.12),0_8px_24px_rgb(27_29_33/0.08)]">
            {pageTexts?.[String(page)] ? (
              <pre className="whitespace-pre-wrap font-mono text-[13px] leading-6 text-ink">{highlightText(pageTexts[String(page)], quotes)}</pre>
            ) : (
              <p className="text-sm text-ink-3">This page has no evidence attached. Select a field to see its source.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

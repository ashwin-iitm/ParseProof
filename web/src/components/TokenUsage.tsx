import { useEffect, useRef, useState } from "react";
import type { Usage } from "@/api";

const n = (v: number) => v.toLocaleString();

/** "52,310 tokens" in the run header; click for the split per model. */
export default function TokenUsage({ usage }: { usage: Usage }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <span ref={box} className="relative">
      <button className="tabular-nums text-accent hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {n(usage.total)} tokens
      </button>
      {open && (
        <span className="absolute left-0 top-6 z-30 block w-[380px] rounded-lg border border-line bg-surface p-3 text-xs text-ink shadow-lg">
          <span className="mb-2 block font-semibold">Tokens used by this run</span>
          <table className="w-full tabular-nums">
            <thead>
              <tr className="text-left text-ink-3">
                <th className="pb-1 font-medium">Model</th>
                <th className="pb-1 text-right font-medium">Calls</th>
                <th className="pb-1 text-right font-medium">In</th>
                <th className="pb-1 text-right font-medium">Out</th>
                <th className="pb-1 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(usage.models).map(([model, m]) => (
                <tr key={model} className="border-t border-line">
                  <td className="py-1 font-mono">{model}</td>
                  <td className="py-1 text-right">{m.calls}</td>
                  <td className="py-1 text-right">{n(m.input)}</td>
                  <td className="py-1 text-right">{n(m.output)}</td>
                  <td className="py-1 text-right font-medium">{n(m.total)}</td>
                </tr>
              ))}
              <tr className="border-t border-line-strong font-semibold">
                <td className="py-1">All</td>
                <td className="py-1 text-right">{Object.values(usage.models).reduce((a, m) => a + m.calls, 0)}</td>
                <td className="py-1 text-right">{n(usage.input)}</td>
                <td className="py-1 text-right">{n(usage.output)}</td>
                <td className="py-1 text-right">{n(usage.total)}</td>
              </tr>
            </tbody>
          </table>
          <span className="mt-2 block leading-[16px] text-ink-3">
            Embeddings are counted only when a document's search index is first built. A re-run of the same file reuses it.
          </span>
        </span>
      )}
    </span>
  );
}

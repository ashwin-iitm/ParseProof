import { useEffect, useRef, useState } from "react";
import type { Usage } from "@/api";
import { usd } from "@/lib/format";

const n = (v: number) => v.toLocaleString();

/** "81,082 tokens · $0.206" in the run header; click for the split per model. */
export default function TokenUsage({ usage }: { usage: Usage }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  const cost = usage.cost_usd != null ? `${usage.priced_all === false ? "≥ " : ""}${usd(usage.cost_usd)}` : null;

  return (
    <span ref={box} className="relative">
      <button className="tabular-nums text-accent hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {n(usage.total)} tokens{cost && ` · ${cost}`}
      </button>
      {open && (
        <span className="absolute left-0 top-6 z-30 block w-[440px] max-w-[calc(100vw-32px)] rounded-lg border border-line bg-surface p-3 text-xs text-ink shadow-lg">
          <span className="mb-2 block font-semibold">Tokens and cost of this run</span>
          <table className="w-full tabular-nums">
            <thead>
              <tr className="text-left text-ink-3">
                <th className="pb-1 font-medium">Model</th>
                <th className="pb-1 text-right font-medium">Calls</th>
                <th className="pb-1 text-right font-medium">In</th>
                <th className="pb-1 text-right font-medium">Out</th>
                <th className="pb-1 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(usage.models).map(([model, m]) => (
                <tr key={model} className="border-t border-line">
                  <td className="py-1 font-mono">{model}</td>
                  <td className="py-1 text-right">{m.calls}</td>
                  <td className="py-1 text-right">{n(m.input)}</td>
                  <td className="py-1 text-right">{n(m.output)}</td>
                  <td className="py-1 text-right font-medium">{m.cost_usd != null ? usd(m.cost_usd) : "no price"}</td>
                </tr>
              ))}
              <tr className="border-t border-line-strong font-semibold">
                <td className="py-1">All</td>
                <td className="py-1 text-right">{Object.values(usage.models).reduce((a, m) => a + m.calls, 0)}</td>
                <td className="py-1 text-right">{n(usage.input)}</td>
                <td className="py-1 text-right">{n(usage.output)}</td>
                <td className="py-1 text-right">{cost ?? "–"}</td>
              </tr>
            </tbody>
          </table>
          <span className="mt-2 block leading-[16px] text-ink-3">
            Estimated from OpenAI's standard prices{usage.prices_checked ? ` (checked ${usage.prices_checked})` : ""}. Your OpenAI bill is the final word.
            {usage.priced_all === false && " A model without a price in config.py is left out of the total."} Embeddings are counted only when a document's search
            index is first built; a re-run of the same file reuses it.
          </span>
        </span>
      )}
    </span>
  );
}

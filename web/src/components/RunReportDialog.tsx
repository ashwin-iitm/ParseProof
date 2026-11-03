import { useEffect } from "react";
import { Download, X } from "lucide-react";
import type { Run, Usage } from "@/api";
import { duration, usd } from "@/lib/format";

const n = (v: number) => v.toLocaleString();
const secs = (v: number) => `${v.toFixed(v < 10 ? 2 : 1)} s`;
const money = (v: number | null | undefined, local?: boolean) => (local ? "free" : v == null ? "no price" : usd(v));

function download(name: string, type: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

const csvCell = (v: unknown) => {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

function toCsv(run: Run, usage: Usage) {
  const rows: unknown[][] = [
    ["ParseProof run report"],
    ["Document", run.filename],
    ["Template", run.template_name],
    ["Run ID", run.id],
    ["Time taken (s)", run.report?.seconds],
    ["Model calls", usage.calls?.length ?? Object.values(usage.models).reduce((a, m) => a + m.calls, 0)],
    ["Input tokens", usage.input],
    ["Output tokens", usage.output],
    ["Total tokens", usage.total],
    ["Estimated cost (USD)", usage.cost_usd?.toFixed(6)],
    ["Prices checked", usage.prices_checked],
    [],
    ["By model"],
    ["Model", "Runs on", "Calls", "Input tokens", "Output tokens", "Time (s)", "Cost (USD)"],
    ...Object.entries(usage.models).map(([model, m]) => [
      model, m.local ? "this computer" : "OpenAI", m.calls, m.input, m.output, m.seconds ?? "", m.cost_usd?.toFixed(6) ?? "",
    ]),
  ];
  if (run.report?.timings?.phases.length) {
    rows.push([], ["By phase"], ["Phase", "Time (s)"], ...run.report.timings.phases.map((p) => [p.phase, p.seconds]));
  }
  if (usage.calls?.length) {
    rows.push([], ["Every call"], ["#", "Started at (s)", "Step", "Model", "Detail", "Input tokens", "Output tokens", "Time (s)", "Cost (USD)"]);
    usage.calls.forEach((c) => rows.push([c.n, c.at, c.step, c.model, c.detail ?? "", c.input, c.output, c.seconds, c.cost_usd?.toFixed(6) ?? ""]));
  }
  return "﻿" + rows.map((r) => r.map(csvCell).join(",")).join("\r\n");
}

/** Every model call of one run: tokens, time and cost, with totals per model and per phase. */
export default function RunReportDialog({ run, onClose }: { run: Run; onClose: () => void }) {
  const report = run.report!;
  const usage = report.usage!;
  const calls = usage.calls ?? [];
  const phases = report.timings?.phases ?? [];
  const totalCalls = calls.length || Object.values(usage.models).reduce((a, m) => a + m.calls, 0);
  const stem = run.filename.replace(/\.[^.]+$/, "");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const stats: [string, string][] = [
    ["Time taken", duration(report.seconds)],
    ["Model calls", n(totalCalls)],
    ["Input tokens", n(usage.input)],
    ["Output tokens", n(usage.output)],
    ["Estimated cost", usage.cost_usd != null ? `${usage.priced_all === false ? "≥ " : ""}${usd(usage.cost_usd)}` : "–"],
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Run report"
        className="flex max-h-[88vh] w-full max-w-[960px] flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Run report</h2>
            <p className="truncate text-xs text-ink-3">{run.filename}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              className="inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-xs font-medium text-ink-2 hover:bg-ink/5 hover:text-ink"
              onClick={() => download(`${stem} - run report.csv`, "text/csv;charset=utf-8", toCsv(run, usage))}
            >
              <Download className="h-3.5 w-3.5" aria-hidden /> CSV
            </button>
            <button
              className="inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-xs font-medium text-ink-2 hover:bg-ink/5 hover:text-ink"
              onClick={() =>
                download(
                  `${stem} - run report.json`,
                  "application/json",
                  JSON.stringify({ run_id: run.id, document: run.filename, template: run.template_name, seconds: report.seconds, timings: report.timings, usage }, null, 2),
                )
              }
            >
              <Download className="h-3.5 w-3.5" aria-hidden /> JSON
            </button>
            <button className="rounded p-2 text-ink-3 hover:bg-ink/5 hover:text-ink" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
          <dl className="grid grid-cols-5 gap-3 max-sm:grid-cols-2">
            {stats.map(([label, value]) => (
              <div key={label} className="rounded border border-line bg-paper px-3 py-2">
                <dt className="text-[11px] font-medium uppercase tracking-[0.04em] text-ink-3">{label}</dt>
                <dd className="mt-0.5 text-md font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="grid gap-5 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <section>
              <h3 className="mb-1.5 text-xs font-semibold text-ink-2">By model</h3>
              <table className="w-full text-xs tabular-nums">
                <thead>
                  <tr className="text-left text-ink-3">
                    <th className="pb-1 font-medium">Model</th>
                    <th className="pb-1 text-right font-medium">Calls</th>
                    <th className="pb-1 text-right font-medium">In</th>
                    <th className="pb-1 text-right font-medium">Out</th>
                    <th className="pb-1 text-right font-medium">Time</th>
                    <th className="pb-1 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(usage.models).map(([model, m]) => (
                    <tr key={model} className="border-t border-line">
                      <td className="py-1.5 pr-2">
                        <span className="font-mono">{model.replace("cross-encoder/", "")}</span>
                        <span className="block text-[11px] text-ink-3">{m.local ? "on this computer" : "OpenAI"}</span>
                      </td>
                      <td className="py-1.5 text-right">{m.calls}</td>
                      <td className="py-1.5 text-right">{m.local ? "–" : n(m.input)}</td>
                      <td className="py-1.5 text-right">{m.local ? "–" : n(m.output)}</td>
                      <td className="py-1.5 text-right">{m.seconds != null ? secs(m.seconds) : "–"}</td>
                      <td className="py-1.5 text-right font-medium">{money(m.cost_usd, m.local)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section>
              <h3 className="mb-1.5 text-xs font-semibold text-ink-2">By phase</h3>
              {phases.length ? (
                <table className="w-full text-xs tabular-nums">
                  <tbody>
                    {phases.map((p) => (
                      <tr key={p.phase} className="border-t border-line first:border-0">
                        <td className="py-1.5">{p.phase}</td>
                        <td className="py-1.5 text-right">{secs(p.seconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-ink-3">Not recorded for this run. Re-run it to see the time per phase.</p>
              )}
              {report.timings?.index_reused && (
                <p className="mt-2 text-[11px] leading-4 text-ink-3">
                  This file's search index was already built, so its pages weren't sent to the embedding model or OCR again.
                </p>
              )}
            </section>
          </div>

          <section>
            <h3 className="mb-1.5 text-xs font-semibold text-ink-2">Every call, in order</h3>
            {calls.length ? (
              <div className="overflow-x-auto rounded border border-line">
                <table className="w-full min-w-[720px] text-xs tabular-nums">
                  <thead className="bg-panel">
                    <tr className="text-left text-ink-3">
                      <th className="px-2 py-1.5 font-medium">#</th>
                      <th className="px-2 py-1.5 font-medium">At</th>
                      <th className="px-2 py-1.5 font-medium">Step</th>
                      <th className="px-2 py-1.5 font-medium">Model</th>
                      <th className="px-2 py-1.5 text-right font-medium">In</th>
                      <th className="px-2 py-1.5 text-right font-medium">Out</th>
                      <th className="px-2 py-1.5 text-right font-medium">Time</th>
                      <th className="px-2 py-1.5 text-right font-medium">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calls.map((c) => (
                      <tr key={c.n} className="border-t border-line">
                        <td className="px-2 py-1.5 text-ink-3">{c.n}</td>
                        <td className="whitespace-nowrap px-2 py-1.5 text-ink-3">{c.at.toFixed(1)} s</td>
                        <td className="px-2 py-1.5">
                          {c.step}
                          {c.detail && <span className="block text-[11px] text-ink-3">{c.detail}</span>}
                        </td>
                        <td className="whitespace-nowrap px-2 py-1.5 font-mono">{c.model.replace("cross-encoder/", "")}</td>
                        <td className="px-2 py-1.5 text-right">{c.local ? "–" : n(c.input)}</td>
                        <td className="px-2 py-1.5 text-right">{c.local ? "–" : n(c.output)}</td>
                        <td className="px-2 py-1.5 text-right">{secs(c.seconds)}</td>
                        <td className="px-2 py-1.5 text-right">{money(c.cost_usd, c.local)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-ink-3">This run was made before calls were logged one by one. Re-run it to see every call.</p>
            )}
          </section>

          <p className="text-[11px] leading-4 text-ink-3">
            Cost is estimated from OpenAI's standard prices{usage.prices_checked ? ` (checked ${usage.prices_checked})` : ""}; your OpenAI bill is the final word. The
            reranker runs on this computer and is free. “At” is when the call started, counted from the start of the run; calls overlap because many run at the same
            time, so their times add up to more than the time taken.
          </p>
        </div>
      </div>
    </div>
  );
}

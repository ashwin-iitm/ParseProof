import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Copy, X } from "lucide-react";
import { api } from "@/api";
import { Spinner } from "@/components/ui";

/** Shows the exact request (and reply) the QC model got for one field. */
export default function QcCallDialog({ runId, field, label, onClose }: { runId: string; field: string; label: string; onClose: () => void }) {
  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);
  // Loaded only when opened: these requests hold page text and would make the run payload heavy
  const query = useQuery({ queryKey: ["qc-calls", runId, field], queryFn: () => api.qcCalls(runId, field), staleTime: Infinity });
  const calls = query.data ?? [];
  const text = calls[active] ? JSON.stringify(calls[active], null, 2) : "";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`QC request for ${label}`}
        className="flex max-h-[85vh] w-full max-w-[860px] flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">QC request · {label}</h2>
            <p className="text-xs text-ink-3">{calls[active] ? `Sent to ${calls[active].model}. ` : ""}Page images are shown as labels.</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button className="inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-xs font-medium text-ink-2 hover:bg-ink/5 hover:text-ink disabled:opacity-40" onClick={copy} disabled={!text}>
              {copied ? <Check className="h-3.5 w-3.5 text-pass" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy JSON"}
            </button>
            <button className="rounded p-2 text-ink-3 hover:bg-ink/5 hover:text-ink" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        {calls.length > 1 && (
          <div className="flex gap-1 border-b border-line px-4 py-2" role="tablist">
            {calls.map((_, i) => (
              <button
                key={i}
                role="tab"
                aria-selected={active === i}
                onClick={() => setActive(i)}
                className={clsx("h-7 rounded px-2.5 text-xs font-medium", active === i ? "bg-ink text-paper" : "text-ink-2 hover:bg-ink/5")}
              >
                {i === 0 ? "First check" : `Check after search ${i}`}
              </button>
            ))}
          </div>
        )}
        {query.isLoading ? (
          <div className="flex h-40 items-center justify-center"><Spinner /></div>
        ) : query.isError ? (
          <p className="px-4 py-8 text-center text-sm text-fail">{(query.error as Error).message}</p>
        ) : (
          <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap bg-paper px-4 py-3 font-mono text-xs leading-5 text-ink [overflow-wrap:anywhere]">
            {text}
          </pre>
        )}
      </div>
    </div>
  );
}

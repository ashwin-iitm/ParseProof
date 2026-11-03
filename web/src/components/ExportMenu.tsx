import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronDown, Download } from "lucide-react";
import { api, type ExportOptions } from "@/api";
import { Button, Checkbox } from "@/components/ui";

const CHOICES: { label: string; hint: string; options: ExportOptions }[] = [
  { label: "Excel workbook", hint: "Data table, a picture of where each value is in the document, QC status, QC detail and run log", options: { format: "xlsx" } },
  { label: "CSV · data table", hint: "One row per document, one column per field", options: { format: "csv", layout: "summary" } },
  { label: "CSV · data table with QC", hint: "Adds a QC status column after every field", options: { format: "csv", layout: "summary_qc" } },
  { label: "CSV · QC detail", hint: "One row per field: values, pages, evidence, notes", options: { format: "csv", layout: "detail" } },
  { label: "JSON", hint: "For loading into another system", options: { format: "json" } },
];

interface Props {
  target: { batch?: string; runs?: string[] };
  /** Offer "approved documents only" (batches and multi-run selections). */
  approvedFilter?: boolean;
  disabled?: boolean;
  label?: string;
  variant?: "primary" | "secondary";
}

export default function ExportMenu({ target, approvedFilter = true, disabled, label = "Export", variant = "secondary" }: Props) {
  const [open, setOpen] = useState(false);
  const [approvedOnly, setApprovedOnly] = useState(false);
  const [keys, setKeys] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Button variant={variant} icon={<Download className="h-4 w-4" />} onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={disabled}>
        {label}
        <ChevronDown className={clsx("h-3.5 w-3.5", variant === "primary" ? "text-white/70" : "text-ink-3")} aria-hidden />
      </Button>
      {open && (
        <div className="absolute right-0 top-9 z-30 w-[300px] rounded-lg border border-line bg-surface py-1 shadow-float" role="menu">
          {CHOICES.map((c) => (
            <a
              key={c.label}
              role="menuitem"
              href={api.exportUrl(target, { ...c.options, headers: keys ? "keys" : "labels", approvedOnly })}
              onClick={() => setOpen(false)}
              className="block px-3 py-2 hover:bg-panel"
            >
              <span className="block text-sm font-medium text-ink">{c.label}</span>
              <span className="block text-xs text-ink-3">{c.hint}</span>
            </a>
          ))}
          <div className="mt-1 space-y-2 border-t border-line px-3 pb-2 pt-2.5">
            {approvedFilter && <Checkbox id="export-approved" checked={approvedOnly} onChange={setApprovedOnly} label="Approved documents only" />}
            <Checkbox id="export-keys" checked={keys} onChange={setKeys} label="Use field keys as column headers" />
          </div>
        </div>
      )}
    </div>
  );
}

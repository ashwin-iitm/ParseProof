import { useRef, useState } from "react";
import { FileText, Paperclip, X } from "lucide-react";
import { api, type TemplateDraft } from "@/api";
import { Button, Checkbox, Textarea } from "@/components/ui";

const EXAMPLES = [
  "Loss run: insured, carrier, policy number, valuation date, total paid, reserves and incurred",
  "Certificate of insurance: insured, each policy's number, carrier, limits and expiry",
  "Bank statement: account holder, account number, period, opening and closing balance",
];

interface Props {
  /** A document already chosen elsewhere (New run). Offered as the sample. */
  sampleName?: string | null;
  /** Resolves the chosen document to an uploaded id, uploading it if needed. */
  resolveSample?: () => Promise<string | null>;
  onDraft: (draft: TemplateDraft, sampleId: string | null) => void;
  onCancel: () => void;
}

export default function AIComposer({ sampleName, resolveSample, onDraft, onCancel }: Props) {
  const [prompt, setPrompt] = useState("");
  const [useSample, setUseSample] = useState(true);
  const [attached, setAttached] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const hasSample = sampleName ? useSample : !!attached;

  const draft = async () => {
    setError(null);
    setBusy(true);
    try {
      let sampleId: string | null = null;
      if (sampleName && useSample && resolveSample) sampleId = await resolveSample();
      else if (attached) sampleId = (await api.upload(attached)).id;
      onDraft(await api.draftTemplate(prompt, sampleId), sampleId);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-line bg-surface">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">Create a template with AI</h2>
          <p className="mt-0.5 text-xs text-ink-3">Describe the fields you need. You'll review and edit the draft before saving it.</p>
        </div>
        <button className="rounded p-1 text-ink-3 hover:bg-ink/5 hover:text-ink" onClick={onCancel} aria-label="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-3 px-4 py-4">
        <Textarea
          autoFocus
          rows={4}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Loss run summary for commercial auto: insured, carrier, policy number, policy period, valuation date, number of claims, total paid, reserves and incurred"
          aria-label="What to extract"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !busy) draft();
          }}
        />
        {!prompt && (
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setPrompt(ex)}
                className="max-w-full truncate rounded-full border border-line-strong px-2.5 py-0.5 text-xs text-ink-2 transition-colors duration-150 hover:border-ink-3 hover:text-ink"
              >
                {ex.split(":")[0]}
              </button>
            ))}
          </div>
        )}

        {sampleName ? (
          <Checkbox checked={useSample} onChange={setUseSample} id="use-sample" label={`Use ${sampleName} as a sample so the fields match what it contains`} />
        ) : attached ? (
          <div className="flex items-center gap-2 text-sm text-ink-2">
            <FileText className="h-4 w-4 text-ink-3" aria-hidden />
            <span className="min-w-0 truncate">{attached.name}</span>
            <button className="text-ink-3 hover:text-ink" onClick={() => setAttached(null)} aria-label="Remove sample">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <button className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline" onClick={() => fileInput.current?.click()}>
            <Paperclip className="h-3.5 w-3.5" aria-hidden />
            Attach a sample document (optional)
          </button>
        )}
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.docx,.xlsx,.xls,.csv,.txt"
          className="hidden"
          onChange={(e) => {
            setAttached(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />

        {error && <p className="text-sm text-fail">{error}</p>}

        <div className="flex items-center justify-between gap-3 pt-1">
          <span className="text-xs text-ink-3">{busy ? (hasSample ? "Reading the sample and drafting fields…" : "Drafting fields…") : "Ctrl + Enter to draft"}</span>
          <Button variant="primary" loading={busy} disabled={!prompt.trim() && !hasSample} onClick={draft}>
            Draft template
          </Button>
        </div>
      </div>
    </div>
  );
}

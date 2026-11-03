import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertCircle, ArrowLeft, Braces, Check, CircleDashed, Pencil, RotateCcw, Undo2 } from "lucide-react";
import { api, type FieldResult, type ReviewDecision, type Run } from "@/api";
import { Button, Input, ProgressBar, Skeleton, Spinner, StatusTag } from "@/components/ui";
import DocumentViewer from "@/components/DocumentViewer";
import ExportMenu from "@/components/ExportMenu";
import QcCallDialog from "@/components/QcCallDialog";
import TokenUsage from "@/components/TokenUsage";
import { useToast } from "@/components/toast";
import { duration, fieldLabel, show } from "@/lib/format";

const STAGES = ["Reading document", "Extracting fields", "Verifying fields", "Running rule checks"];

function stageIndex(stage: string) {
  if (stage.startsWith("Verifying")) return 2;
  if (stage.startsWith("Extracting") || stage.startsWith("Checking")) return 1;
  if (stage.startsWith("Running rule")) return 3;
  return 0;
}

const needsAttention = (r: FieldResult) => r.status === "FAIL" || r.status === "REVIEW";

interface FieldRowProps {
  runId: string;
  models?: { extract?: string; qc?: string };
  r: FieldResult;
  decision?: ReviewDecision;
  selected: boolean;
  locked: boolean;
  onSelect: () => void;
  onJump: (page: number) => void;
  onDecide: (body: { value?: string | null; source?: string; reset?: boolean }) => Promise<void>;
}

const VERDICTS: Record<string, string> = {
  correct: "Matches the page",
  incorrect: "Page shows a different value:",
  not_found: "Not found on the pages it read",
};

const WHO = {
  ai: { label: "AI", className: "bg-accent/10 text-accent" },
  python: { label: "Python", className: "bg-ink/[0.06] text-ink-2" },
  person: { label: "You", className: "bg-pass/10 text-pass" },
};

function Step({ who, model, title, children }: { who: keyof typeof WHO; model?: string; title: string; children: ReactNode }) {
  return (
    <li className="space-y-1.5 rounded border border-line bg-paper/60 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={clsx("rounded px-1.5 py-px text-[11px] font-semibold uppercase tracking-[0.04em]", WHO[who].className)}>
          {WHO[who].label}
          {model ? ` · ${model}` : ""}
        </span>
        <span className="text-xs font-medium text-ink-2">{title}</span>
      </div>
      {children}
    </li>
  );
}

function ValueLine({ value, strong }: { value: string | null | undefined; strong?: boolean }) {
  return (
    <p className={clsx("font-mono text-[13px] [overflow-wrap:anywhere]", value == null || value === "" ? "text-ink-3" : "text-ink", strong && "font-medium")}>
      {show(value)}
    </p>
  );
}

function Quote({ text }: { text: string }) {
  return <blockquote className="border-l-2 border-line-strong pl-2 text-[13px] leading-5 text-ink-2 [overflow-wrap:anywhere]">“{text}”</blockquote>;
}

/** What Python's own check found, with every page the text appears on. */
function PythonCheck({ ok, yes, no, pages, onJump }: { ok: boolean; yes: string; no: string; pages: number[]; onJump: (p: number) => void }) {
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
      <span className={clsx("rounded px-1.5 py-px text-[11px] font-semibold uppercase tracking-[0.04em]", WHO.python.className)}>Python</span>
      {ok ? <Check className="h-3.5 w-3.5 text-pass" aria-hidden /> : <AlertCircle className="h-3.5 w-3.5 text-review" aria-hidden />}
      <span className="text-ink-2">{ok ? `${yes} page${pages.length > 1 ? "s" : ""}` : no}</span>
      {ok &&
        pages.map((p, i) => (
          <span key={p} className="text-ink-3">
            <button className="text-accent hover:underline" onClick={() => onJump(p)}>
              {p}
            </button>
            {i < pages.length - 1 ? "," : ""}
          </span>
        ))}
    </p>
  );
}

function finalSource(r: FieldResult, decision?: ReviewDecision) {
  if (decision) {
    if (decision.source === "verified") return "You chose QC's value.";
    if (decision.source === "extracted") return "You kept the extractor's value.";
    return "You typed this value.";
  }
  if (r.status === "PASS") return "The extractor's value, confirmed by QC and by Python's check of the page.";
  if (r.status === "FAIL") return "QC's value: QC found a different value and Python confirmed its evidence is on the page. Accept it or change it.";
  return "The extractor's value. QC couldn't confirm it, so it needs your decision.";
}

function FieldRow({ runId, models, r, decision, selected, locked, onSelect, onJump, onDecide }: FieldRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [showQc, setShowQc] = useState(false);
  const value = decision ? decision.value : r.final_value;
  // Older runs only know the one page Python matched; newer ones list every page
  const quotePages = r.extracted_quote_pages?.length ? r.extracted_quote_pages : r.extracted_page && r.citation_ok !== false ? [r.extracted_page] : [];
  const quoteFound = r.extracted_quote_pages ? r.extracted_quote_pages.length > 0 : r.citation_ok === true || r.located_by === "quote_match";
  const evidencePages = r.evidence_pages?.length ? r.evidence_pages : r.evidence_page ? [r.evidence_page] : [];
  const decide = async (body: Parameters<typeof onDecide>[0]) => {
    setBusy(true);
    try {
      await onDecide(body);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={clsx("border-b border-line transition-colors duration-150", selected ? "bg-surface" : "hover:bg-surface/60")}>
      <button className="flex w-full items-start gap-3 px-5 py-3 text-left" onClick={onSelect} aria-expanded={selected}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-sm font-medium text-ink">{fieldLabel(r)}</span>
            <StatusTag status={r.status} resolved={!!decision && needsAttention(r)} />
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className={clsx("truncate font-mono text-[13px]", value == null || value === "" ? "text-ink-3" : "text-ink")}>{show(value)}</span>
            {r.status === "FAIL" && !decision && r.extracted_value && (
              <span className="truncate font-mono text-xs text-ink-3 line-through decoration-fail/60">{r.extracted_value}</span>
            )}
          </div>
        </div>
      </button>

      {selected && (
        <div className="space-y-3 px-5 pb-4">
          <ol className="space-y-2.5">
            <Step who="ai" model={models?.extract} title="Extractor read">
              <ValueLine value={r.extracted_value} />
              {r.extracted_quote && <Quote text={r.extracted_quote} />}
              <PythonCheck
                ok={quoteFound}
                yes="Quote found on"
                no={r.extracted_quote ? "Quote not found anywhere in the document" : "Nothing was extracted"}
                pages={quotePages}
                onJump={onJump}
              />
            </Step>

            <Step who="ai" model={models?.qc} title="QC checker">
              <p className="text-[13px] text-ink">
                <span className={clsx("font-medium", r.verdict === "correct" ? "text-pass" : r.verdict === "incorrect" ? "text-fail" : "text-review")}>
                  {VERDICTS[r.verdict ?? ""] ?? "Not checked"}
                </span>
                {r.verdict === "incorrect" && r.correct_value && (
                  <span className="ml-1.5 font-mono font-medium text-fail [overflow-wrap:anywhere]">{r.correct_value}</span>
                )}
              </p>
              {r.evidence_quote && <Quote text={r.evidence_quote} />}
              {r.verdict && r.verdict !== "not_found" && (
                <PythonCheck
                  ok={!!r.evidence_page}
                  yes="Evidence found on"
                  no="Evidence not found on the pages QC was given"
                  pages={evidencePages}
                  onJump={onJump}
                />
              )}
              {r.reasoning && <p className="text-xs leading-[18px] text-ink-2">{r.reasoning}</p>}
              {r.pages_checked.length > 0 && (
                <p className="text-xs text-ink-3">
                  Read page{r.pages_checked.length > 1 ? "s" : ""} {r.pages_checked.join(", ")}
                  {r.located_by === "search" ? " (found by search)" : ""}
                </p>
              )}
              {!!r.qc_call_count && (
                <button
                  className="inline-flex h-7 items-center gap-1.5 rounded border border-line px-2 text-xs font-medium text-ink-2 hover:border-ink-3 hover:text-ink"
                  onClick={() => setShowQc(true)}
                  title="See the exact JSON sent to the QC model for this field"
                >
                  <Braces className="h-3.5 w-3.5" aria-hidden />
                  QC request JSON
                </button>
              )}
            </Step>

            <Step who={decision ? "person" : "python"} title="Final value">
              <ValueLine value={value} strong />
              <p className="text-xs text-ink-2">{finalSource(r, decision)}</p>
            </Step>
          </ol>
          {showQc && <QcCallDialog runId={runId} field={r.field} label={fieldLabel(r)} onClose={() => setShowQc(false)} />}

          {r.notes.length > 0 && (
            <div className="space-y-1 text-xs leading-[18px] text-ink-2">
              {r.notes.map((n, i) => (
                <p key={i} className="flex gap-1.5">
                  <AlertCircle className="mt-[1px] h-3.5 w-3.5 shrink-0 text-review" aria-hidden />
                  {n}
                </p>
              ))}
            </div>
          )}

          {!locked &&
            (editing ? (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  decide({ value: draft.trim() || null, source: "manual" });
                }}
              >
                <Input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} className="font-mono text-[13px]" aria-label={`Value for ${fieldLabel(r)}`} />
                <Button type="submit" variant="primary" loading={busy}>
                  Save
                </Button>
                <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </form>
            ) : (
              <div className="flex flex-wrap gap-2">
                {decision ? (
                  <Button size="sm" variant="ghost" icon={<Undo2 className="h-3.5 w-3.5" />} loading={busy} onClick={() => decide({ reset: true })}>
                    Undo decision
                  </Button>
                ) : (
                  <>
                    {r.status === "FAIL" && (
                      <Button size="sm" variant="primary" icon={<Check className="h-3.5 w-3.5" />} loading={busy} onClick={() => decide({ value: r.correct_value, source: "verified" })}>
                        Use verified value
                      </Button>
                    )}
                    {needsAttention(r) && (
                      <Button size="sm" loading={busy && r.status !== "FAIL"} onClick={() => decide({ value: r.extracted_value, source: "extracted" })}>
                        Keep extracted
                      </Button>
                    )}
                  </>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Pencil className="h-3.5 w-3.5" />}
                  onClick={() => {
                    setDraft(String(value ?? ""));
                    setEditing(true);
                  }}
                >
                  Edit value
                </Button>
              </div>
            ))}
        </div>
      )}
    </li>
  );
}

function Progress({ run }: { run: Run }) {
  const current = stageIndex(run.stage);
  return (
    <div className="px-5 py-6">
      <h2 className="text-md font-semibold">Working on it</h2>
      <p className="mt-1 text-sm text-ink-2">{run.stage || "Queued"}</p>
      <div className="mt-4">
        <ProgressBar value={run.progress} />
      </div>
      <ol className="mt-6 space-y-3">
        {STAGES.map((s, i) => (
          <li key={s} className={clsx("flex items-center gap-2.5 text-sm", i < current ? "text-ink-2" : i === current ? "font-medium text-ink" : "text-ink-3")}>
            {i < current ? <Check className="h-4 w-4 text-pass" aria-hidden /> : i === current ? <Spinner className="text-accent" /> : <CircleDashed className="h-4 w-4" aria-hidden />}
            {s}
          </li>
        ))}
      </ol>
      <p className="mt-8 text-xs leading-[18px] text-ink-3">
        OpenAI reads the full document, then each field is checked by a second model against only the page it came from.
        Large documents are split into page ranges and processed in parallel.
      </p>
    </div>
  );
}

export default function RunReview() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<"attention" | "all" | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.run(id),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1200 : false),
  });
  const run = query.data;
  const report = run?.report ?? null;
  const results = useMemo(() => report?.results ?? [], [report]);
  const attention = results.filter(needsAttention);
  const activeFilter = filter ?? (attention.length ? "attention" : "all");
  const visible = activeFilter === "attention" ? attention : results;
  const open = attention.filter((r) => !run?.review[r.field]).length;
  const locked = !!run?.approved_at;
  const current = results.find((r) => r.field === selected) ?? null;

  useEffect(() => {
    if (run?.status === "done" || run?.status === "failed") qc.invalidateQueries({ queryKey: ["runs"] });
  }, [run?.status, qc]);

  const select = (r: FieldResult) => {
    const isSame = r.field === selected;
    setSelected(isSame ? null : r.field);
    const p = r.evidence_page ?? r.extracted_page;
    if (!isSame && p) setPage(p);
  };

  // Open the first field that needs a decision once results arrive
  useEffect(() => {
    if (!report || selected) return;
    const first = report.results.find(needsAttention) ?? report.results[0];
    if (first) select(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report]);

  // j / k step through the visible fields
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || !visible.length) return;
      if (e.key !== "j" && e.key !== "k") return;
      const i = visible.findIndex((r) => r.field === selected);
      const next = visible[Math.min(Math.max(0, i + (e.key === "j" ? 1 : -1)), visible.length - 1)];
      if (next && next.field !== selected) select(next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const setRun = (r: Run) => qc.setQueryData(["run", id], r);
  const decide = async (field: string, body: { value?: string | null; source?: string; reset?: boolean }) => {
    try {
      setRun(await api.review(id, { field, ...body }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const approve = useMutation({
    mutationFn: () => (locked ? api.reopen(id) : api.approve(id)),
    onSuccess: (r) => {
      setRun(r);
      qc.invalidateQueries({ queryKey: ["runs"] });
      toast(r.approved_at ? "Run approved" : "Run reopened for changes");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const rerun = useMutation({
    mutationFn: () => api.rerun(id),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${r.id}`);
      setSelected(null);
      setFilter(null);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  if (query.isError) {
    return (
      <div className="p-10 text-center">
        <p className="text-sm text-fail">{(query.error as Error).message}</p>
        <Link to="/" className="mt-3 inline-block text-sm text-accent hover:underline">
          Back to runs
        </Link>
      </div>
    );
  }

  const isPdf = !!run && (run.content_type === "application/pdf" || run.filename.toLowerCase().endsWith(".pdf"));
  const numPages = report?.num_pages ?? run?.pages ?? 1;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
        <Link
          to={run?.batch_id ? `/batches/${run.batch_id}` : "/"}
          className="flex items-center gap-1.5 rounded px-2 py-1 text-sm text-ink-2 hover:bg-ink/5 hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          {run?.batch_id ? "Batch" : "Runs"}
        </Link>
        <div className="h-5 w-px bg-line" aria-hidden />
        <div className="min-w-0 flex-1">
          {run ? (
            <>
              <h1 className="truncate text-sm font-semibold">{run.filename}</h1>
              <div className="flex min-w-0 items-baseline gap-1 text-xs text-ink-3">
                {/* The token popover sits outside the truncated line so it isn't clipped */}
                {report?.usage && (
                  <span className="shrink-0">
                    <TokenUsage usage={report.usage} /> ·
                  </span>
                )}
                <p className="min-w-0 truncate">
                  {run.template_name}
                  {report && ` · ${report.num_pages} pages · ${duration(report.seconds)} · ${report.llm_calls} model calls`}
                  {report && report.ocr_pages.length > 0 && ` · ${report.ocr_pages.length} scanned pages read with OCR`}
                </p>
              </div>
            </>
          ) : (
            <Skeleton className="h-4 w-56" />
          )}
        </div>
        {run && (run.status === "done" || run.status === "failed") && (
          <div className="flex items-center gap-2">
            <Button variant="ghost" icon={<RotateCcw className="h-4 w-4" />} loading={rerun.isPending} onClick={() => rerun.mutate()} className="max-sm:hidden">
              Re-run
            </Button>
            {run.status === "done" && (
              <>
                <ExportMenu target={{ runs: [run.id] }} approvedFilter={false} />
                {locked ? (
                  <Button onClick={() => approve.mutate()} loading={approve.isPending} title="Reopen to make changes">
                    <Check className="h-4 w-4 text-pass" aria-hidden />
                    Approved
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    loading={approve.isPending}
                    onClick={() => {
                      if (open > 0 && !confirm(`${open} field${open > 1 ? "s" : ""} still need${open > 1 ? "" : "s"} a decision. Approve anyway?`)) return;
                      approve.mutate();
                    }}
                  >
                    Approve
                  </Button>
                )}
              </>
            )}
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1 max-lg:flex-col">
        <aside className="flex w-[440px] shrink-0 flex-col border-r border-line bg-paper max-lg:max-h-[55%] max-lg:w-full max-lg:border-b max-lg:border-r-0">
          {!run ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : run.status === "queued" || run.status === "running" ? (
            <Progress run={run} />
          ) : run.status === "failed" ? (
            <div className="px-5 py-6">
              <h2 className="flex items-center gap-2 text-md font-semibold text-fail">
                <AlertCircle className="h-4 w-4" aria-hidden />
                This run failed
              </h2>
              <p className="mt-2 break-words text-sm text-ink-2">{run.error}</p>
              <div className="mt-4 flex gap-2">
                <Button variant="primary" icon={<RotateCcw className="h-4 w-4" />} loading={rerun.isPending} onClick={() => rerun.mutate()}>
                  Try again
                </Button>
                {run.error?.includes("Settings") && <Button onClick={() => navigate("/settings")}>Open settings</Button>}
              </div>
            </div>
          ) : report ? (
            <>
              <div className="border-b border-line px-5 py-4">
                <p className="text-sm text-ink">
                  <span className="font-semibold">{report.summary.PASS}</span> of {results.length} fields verified on their source page.
                  {attention.length > 0 && (
                    <>
                      {" "}
                      {open > 0 ? (
                        <span className="font-semibold">{open} need{open > 1 ? "" : "s"} your decision.</span>
                      ) : (
                        <span className="text-pass">All decisions made.</span>
                      )}
                    </>
                  )}
                </p>
                {report.review_pages.length > 0 && (
                  <p className="mt-1 text-xs text-ink-3">
                    Pages to check:{" "}
                    {report.review_pages.map((p, i) => (
                      <span key={p}>
                        {i > 0 && ", "}
                        <button className="text-accent hover:underline" onClick={() => setPage(p)}>
                          {p}
                        </button>
                      </span>
                    ))}{" "}
                    of {report.num_pages}
                  </p>
                )}
                <div className="mt-3 inline-flex rounded border border-line-strong bg-surface p-0.5 text-xs" role="tablist">
                  {(
                    [
                      ["attention", `Needs attention · ${attention.length}`],
                      ["all", `All fields · ${results.length}`],
                    ] as const
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      role="tab"
                      aria-selected={activeFilter === key}
                      onClick={() => setFilter(key)}
                      className={clsx(
                        "rounded-[4px] px-2.5 py-1 font-medium transition-colors duration-150",
                        activeFilter === key ? "bg-ink text-paper" : "text-ink-2 hover:text-ink",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <ul className="min-h-0 flex-1 overflow-y-auto">
                {visible.length === 0 ? (
                  <li className="px-5 py-10 text-center text-sm text-ink-2">
                    Nothing needs attention. Every field was verified on its source page.
                    <button className="mt-2 block w-full text-accent hover:underline" onClick={() => setFilter("all")}>
                      Show all fields
                    </button>
                  </li>
                ) : (
                  visible.map((r) => (
                    <FieldRow
                      key={r.field}
                      runId={run.id}
                      models={report.models}
                      r={r}
                      decision={run.review[r.field]}
                      selected={r.field === selected}
                      locked={locked}
                      onSelect={() => select(r)}
                      onJump={setPage}
                      onDecide={(body) => decide(r.field, body)}
                    />
                  ))
                )}
              </ul>
              <p className="border-t border-line px-5 py-2 text-xs text-ink-3">
                <kbd className="font-mono">j</kbd> / <kbd className="font-mono">k</kbd> to move between fields
              </p>
            </>
          ) : null}
        </aside>

        <div className="min-h-0 min-w-0 flex-1">
          {run ? (
            <DocumentViewer
              url={api.documentUrl(run.document_id)}
              isPdf={isPdf}
              page={page}
              numPages={numPages}
              onPageChange={setPage}
              highlights={current ? [current.evidence_quote, current.extracted_quote] : []}
              pageTexts={report?.page_texts}
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <Spinner />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

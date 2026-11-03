import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertCircle, ArrowLeft, CheckCheck, RotateCcw, Trash2 } from "lucide-react";
import { api, type Batch, type BatchCell, type BatchRow } from "@/api";
import { Button, ProgressBar, QC_META, Skeleton } from "@/components/ui";
import ExportMenu from "@/components/ExportMenu";
import { useToast } from "@/components/toast";
import { fieldLabel, relativeTime } from "@/lib/format";

type Filter = "all" | "attention" | "ready" | "approved" | "failed";

const FILTERS: { id: Filter; label: string; test: (r: BatchRow) => boolean }[] = [
  { id: "all", label: "All", test: () => true },
  { id: "attention", label: "Needs attention", test: (r) => r.status === "done" && r.open_issues > 0 },
  { id: "ready", label: "Ready to approve", test: (r) => r.status === "done" && r.open_issues === 0 && !r.approved_at },
  { id: "approved", label: "Approved", test: (r) => !!r.approved_at },
  { id: "failed", label: "Failed", test: (r) => r.status === "failed" },
];

function cellClass(c: BatchCell) {
  if (c.reviewed) return "bg-accent/15 shadow-[inset_3px_0_0_rgb(var(--accent))]";
  if (c.status === "FAIL") return "bg-fail/15 text-fail shadow-[inset_3px_0_0_rgb(var(--fail))]";
  if (c.status === "REVIEW") return "bg-review/20 shadow-[inset_3px_0_0_rgb(var(--review))]";
  return "";
}

function cellTitle(c: BatchCell) {
  const state = c.reviewed ? `Resolved by reviewer (${c.source})` : QC_META[c.status].label;
  return `${state}${c.value ? `\n${c.value}` : ""}`;
}

function RowState({ r }: { r: BatchRow }) {
  if (r.status === "queued" || r.status === "running") {
    return (
      <div className="w-[150px] space-y-1">
        <div className="truncate text-xs text-ink-2">{r.status === "queued" ? "Waiting" : r.stage}</div>
        <ProgressBar value={r.progress} />
      </div>
    );
  }
  if (r.status === "failed") {
    return (
      <span className="inline-flex max-w-[180px] items-center gap-1.5 text-xs text-fail" title={r.error ?? undefined}>
        <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate">{r.error || "Failed"}</span>
      </span>
    );
  }
  if (r.approved_at) return <span className="text-xs font-medium text-pass">Approved</span>;
  if (r.open_issues > 0) {
    return (
      <span className="text-xs text-ink-2">
        <span className="font-medium text-fail">{r.open_issues}</span> to review
      </span>
    );
  }
  return <span className="text-xs text-ink-2">Ready to approve</span>;
}

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={clsx("text-md font-semibold tabular-nums", tone ?? "text-ink")}>{value}</span>
      <span className="text-xs text-ink-3">{label}</span>
    </div>
  );
}

export default function BatchDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");

  const query = useQuery({
    queryKey: ["batch", id],
    queryFn: () => api.batch(id),
    refetchInterval: (q) => (q.state.data && q.state.data.active > 0 ? 2000 : false),
  });
  const batch = query.data;

  const refresh = (b: Batch) => {
    qc.setQueryData(["batch", id], b);
    qc.invalidateQueries({ queryKey: ["batches"] });
    qc.invalidateQueries({ queryKey: ["runs"] });
  };
  const approveClean = useMutation({
    mutationFn: () => api.approveClean(id),
    onSuccess: (res) => {
      refresh(res.batch);
      toast(res.approved ? `Approved ${res.approved} document${res.approved > 1 ? "s" : ""} with no open issues` : "No documents were ready to approve");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const retry = useMutation({
    mutationFn: () => api.retryFailed(id),
    onSuccess: (res) => {
      refresh(res.batch);
      toast(`Retrying ${res.retried} document${res.retried > 1 ? "s" : ""}`);
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteBatch(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["batches"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      toast("Batch deleted");
      navigate("/batches");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.id, batch?.rows.filter(f.test).length ?? 0])) as Record<Filter, number>,
    [batch],
  );
  const rows = useMemo(() => batch?.rows.filter(FILTERS.find((f) => f.id === filter)!.test) ?? [], [batch, filter]);

  if (query.isError) {
    return (
      <div className="p-10 text-center">
        <p className="text-sm text-fail">{(query.error as Error).message}</p>
        <Link to="/batches" className="mt-3 inline-block text-sm text-accent hover:underline">
          Back to batches
        </Link>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="border-b border-line px-8 pb-5 pt-5 max-sm:px-4">
        <Link to="/batches" className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Batches
        </Link>
        <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            {batch ? (
              <>
                <h1 className="truncate text-xl font-semibold tracking-[-0.01em]">{batch.name}</h1>
                <p className="mt-1 text-sm text-ink-2">
                  {batch.template_name} · {batch.total} documents · {batch.fields.length} fields · started {relativeTime(batch.created_at)}
                </p>
              </>
            ) : (
              <Skeleton className="h-7 w-72" />
            )}
          </div>
          {batch && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                className="rounded p-2 text-ink-3 hover:bg-fail-weak hover:text-fail"
                aria-label="Delete batch"
                title="Delete batch"
                onClick={() => confirm(`Delete "${batch.name}" and its ${batch.total} runs? The documents stay available.`) && remove.mutate()}
              >
                <Trash2 className="h-4 w-4" />
              </button>
              {batch.failed > 0 && (
                <Button icon={<RotateCcw className="h-4 w-4" />} loading={retry.isPending} onClick={() => retry.mutate()}>
                  Retry {batch.failed} failed
                </Button>
              )}
              {counts.ready > 0 && (
                <Button icon={<CheckCheck className="h-4 w-4" />} loading={approveClean.isPending} onClick={() => approveClean.mutate()}>
                  Approve {counts.ready} with no issues
                </Button>
              )}
              <ExportMenu target={{ batch: batch.id }} variant="primary" disabled={batch.done === 0} />
            </div>
          )}
        </div>

        {batch && (
          <div className="mt-5 flex flex-wrap items-center gap-x-7 gap-y-3">
            {batch.active > 0 && (
              <div className="w-full max-w-[360px] space-y-1.5">
                <div className="text-xs text-ink-2">
                  Processing · {batch.done + batch.failed} of {batch.total} finished
                </div>
                <ProgressBar value={batch.progress} />
              </div>
            )}
            <Stat label="complete" value={`${batch.done}/${batch.total}`} />
            <Stat label="fields verified" value={batch.pass} tone="text-pass" />
            <Stat label={batch.fail === 1 ? "mismatch" : "mismatches"} value={batch.fail} tone={batch.fail ? "text-fail" : undefined} />
            <Stat label="to review" value={batch.review} tone={batch.review ? "text-review" : undefined} />
            <Stat label="approved" value={`${batch.approved}/${batch.total}`} />
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 px-8 pt-4 max-sm:px-4">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter documents">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              role="tab"
              aria-selected={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={clsx(
                "h-7 rounded px-2.5 text-xs font-medium transition-colors duration-150",
                filter === f.id ? "bg-ink text-paper" : "text-ink-2 hover:bg-ink/5 hover:text-ink",
              )}
            >
              {f.label} <span className={clsx("tabular-nums", filter === f.id ? "text-paper/70" : "text-ink-3")}>{counts[f.id]}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs font-medium text-ink-2" aria-label="Cell colours">
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm bg-pass" />Verified</span>
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm bg-fail" />Mismatch</span>
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm bg-review" />Needs review</span>
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm bg-accent" />Resolved</span>
        </div>
      </div>

      <div className="min-h-0 flex-1 px-8 pb-8 pt-3 max-sm:px-4">
        {!batch ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <div className="max-h-[calc(100vh-260px)] min-h-[200px] overflow-auto rounded-lg border border-line bg-surface">
            <table className="w-max min-w-full border-separate border-spacing-0 text-left text-sm">
              <thead>
                <tr className="text-xs text-ink-3">
                  <th className="sticky left-0 top-0 z-20 h-9 min-w-[240px] border-b border-r border-line bg-panel px-3 font-medium">Document</th>
                  <th className="sticky top-0 z-10 h-9 border-b border-line bg-panel px-3 font-medium">Status</th>
                  {batch.fields.map((f) => (
                    <th key={f.name} className="sticky top-0 z-10 h-9 whitespace-nowrap border-b border-line bg-panel px-3 font-medium" title={f.description}>
                      {fieldLabel(f)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.run_id} onClick={() => navigate(`/runs/${r.run_id}`)} className="group cursor-pointer">
                    <td className="sticky left-0 z-[5] h-11 max-w-[280px] border-b border-r border-line bg-surface px-3 group-hover:bg-panel">
                      <div className="truncate font-medium text-ink" title={r.filename}>{r.filename}</div>
                      {r.pages && <div className="text-xs text-ink-3">{r.pages} pages</div>}
                    </td>
                    <td className="whitespace-nowrap border-b border-line px-3 group-hover:bg-panel/60">
                      <RowState r={r} />
                    </td>
                    {batch.fields.map((f) => {
                      const c = r.cells[f.name];
                      return (
                        <td
                          key={f.name}
                          className={clsx("border-b border-line px-3 group-hover:brightness-[0.97]", c && cellClass(c))}
                          title={c ? cellTitle(c) : undefined}
                        >
                          <div className={clsx("max-w-[240px] truncate", f.type === "number" && "tabular-nums", !c?.value && "text-ink-3")}>
                            {r.status !== "done" ? "" : c?.value ?? "—"}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={batch.fields.length + 2} className="px-3 py-8 text-center text-sm text-ink-3">
                      No documents in this view.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

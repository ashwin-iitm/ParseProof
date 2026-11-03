import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertCircle, ArrowRight, FileText, Plus, Trash2 } from "lucide-react";
import { api, type RunListItem } from "@/api";
import { Button, PageHeader, ProgressBar, Skeleton } from "@/components/ui";
import ExportMenu from "@/components/ExportMenu";
import { useToast } from "@/components/toast";
import { duration, relativeTime } from "@/lib/format";

function Outcome({ run }: { run: RunListItem }) {
  if (run.status === "queued" || run.status === "running") {
    return (
      <div className="w-[220px] space-y-1.5">
        <div className="truncate text-xs text-ink-2">{run.stage || "Queued"}</div>
        <ProgressBar value={run.progress} />
      </div>
    );
  }
  if (run.status === "failed") {
    return (
      <span className="inline-flex max-w-[320px] items-center gap-1.5 text-sm text-fail" title={run.error ?? undefined}>
        <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate">{run.error || "Failed"}</span>
      </span>
    );
  }
  const s = run.summary;
  if (!s) return <span className="text-ink-3">—</span>;
  const attention = s.FAIL + s.REVIEW;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-ink-2">
        <span className="font-medium text-pass">{s.PASS}</span> verified
      </span>
      {s.FAIL > 0 && (
        <span className="text-ink-2">
          <span className="font-medium text-fail">{s.FAIL}</span> mismatch{s.FAIL > 1 ? "es" : ""}
        </span>
      )}
      {s.REVIEW > 0 && (
        <span className="text-ink-2">
          <span className="font-medium text-review">{s.REVIEW}</span> to review
        </span>
      )}
      {attention === 0 && <span className="text-xs text-ink-3">{duration(run.seconds)}</span>}
      {run.tokens != null && <span className="text-xs tabular-nums text-ink-3">{run.tokens.toLocaleString()} tokens</span>}
    </div>
  );
}

function ReviewState({ run }: { run: RunListItem }) {
  if (run.status !== "done") return <span className="text-ink-3">—</span>;
  if (run.approved_at) {
    return <span className="text-sm font-medium text-pass">Approved</span>;
  }
  const open = (run.summary?.FAIL ?? 0) + (run.summary?.REVIEW ?? 0) - Object.keys(run.review || {}).length;
  return <span className="text-sm text-ink-2">{open > 0 ? "Awaiting review" : "Ready to approve"}</span>;
}

export default function Runs() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 1500 : false),
  });
  const remove = useMutation({
    mutationFn: api.deleteRun,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      toast("Run deleted");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const list = runs.data ?? [];
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const finished = list.filter((r) => r.status === "done");
  const picked = finished.filter((r) => selected.has(r.id)).map((r) => r.id);
  const allPicked = finished.length > 0 && picked.length === finished.length;
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div>
      <PageHeader
        title="Runs"
        description="Each run extracts a template's fields from one document, then checks every value against its source page."
        actions={
          <>
            {picked.length > 0 && (
              <>
                <button className="text-xs font-medium text-ink-2 hover:text-ink hover:underline" onClick={() => setSelected(new Set())}>
                  Clear selection
                </button>
                <ExportMenu target={{ runs: picked }} label={`Export ${picked.length} selected`} />
              </>
            )}
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/new")}>
              New run
            </Button>
          </>
        }
      />

      {settings.data && !settings.data.openai_key_set && (
        <div className="mx-8 mt-6 flex items-center justify-between gap-4 rounded-lg border border-review/30 bg-review-weak px-4 py-3 text-sm max-sm:mx-4">
          <span className="text-ink">Add your OpenAI API key before starting a run.</span>
          <Link to="/settings" className="font-medium text-accent hover:underline">
            Open settings
          </Link>
        </div>
      )}

      <div className="px-8 py-6 max-sm:px-4">
        {runs.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : runs.isError ? (
          <p className="text-sm text-fail">{(runs.error as Error).message}</p>
        ) : list.length === 0 ? (
          <div className="mx-auto max-w-[520px] py-16 text-center">
            <FileText className="mx-auto h-8 w-8 text-ink-3" strokeWidth={1.5} aria-hidden />
            <h2 className="mt-4 text-md font-semibold">No runs yet</h2>
            <p className="mt-2 text-sm text-ink-2">
              Upload an invoice, agreement or purchase order and pick a template. ParseProof pulls out every field, then a
              second model confirms each value on the page it came from, so you only review what doesn't match.
            </p>
            <Button className="mt-5" variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/new")}>
              Start your first run
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-panel text-xs text-ink-3">
                  <th className="h-9 w-10 pl-4">
                    <input
                      type="checkbox"
                      aria-label="Select all completed runs"
                      title="Select all completed runs for export"
                      checked={allPicked}
                      disabled={finished.length === 0}
                      onChange={() => setSelected(allPicked ? new Set() : new Set(finished.map((r) => r.id)))}
                      className="h-4 w-4 cursor-pointer accent-[rgb(var(--accent))] align-middle"
                    />
                  </th>
                  <th className="h-9 px-4 font-medium">Document</th>
                  <th className="h-9 px-4 font-medium">Template</th>
                  <th className="h-9 px-4 font-medium">QC result</th>
                  <th className="h-9 px-4 font-medium">Review</th>
                  <th className="h-9 px-4 font-medium">Started</th>
                  <th className="h-9 w-[84px] px-4" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => navigate(`/runs/${run.id}`)}
                    className="group h-14 cursor-pointer border-b border-line transition-colors duration-150 last:border-0 hover:bg-paper/70"
                  >
                    <td className="w-10 pl-4" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${run.filename} for export`}
                        checked={selected.has(run.id)}
                        disabled={run.status !== "done"}
                        onChange={() => toggle(run.id)}
                        className="h-4 w-4 cursor-pointer accent-[rgb(var(--accent))] align-middle disabled:cursor-not-allowed disabled:opacity-30"
                      />
                    </td>
                    <td className="px-4">
                      <div className="flex items-center gap-2.5">
                        <FileText className="h-4 w-4 shrink-0 text-ink-3" strokeWidth={1.75} aria-hidden />
                        <div className="min-w-0">
                          <div className="max-w-[300px] truncate font-medium text-ink">{run.filename}</div>
                          {run.pages && <div className="text-xs text-ink-3">{run.pages} pages</div>}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 text-ink-2">
                      <div>{run.template_name}</div>
                      {run.batch_id && (
                        <Link
                          to={`/batches/${run.batch_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="block max-w-[220px] truncate text-xs text-ink-3 hover:text-accent hover:underline"
                        >
                          {run.batch_name}
                        </Link>
                      )}
                    </td>
                    <td className="px-4">
                      <Outcome run={run} />
                    </td>
                    <td className="px-4">
                      <ReviewState run={run} />
                    </td>
                    <td className="whitespace-nowrap px-4 text-ink-2">{relativeTime(run.created_at)}</td>
                    <td className="px-4">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          className={clsx(
                            "rounded p-1.5 text-ink-3 opacity-0 transition hover:bg-fail-weak hover:text-fail focus-visible:opacity-100 group-hover:opacity-100",
                          )}
                          aria-label={`Delete run for ${run.filename}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (confirm(`Delete this run of ${run.filename}? The document stays available.`)) remove.mutate(run.id);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                        <ArrowRight className="h-4 w-4 text-ink-3 transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-ink" aria-hidden />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

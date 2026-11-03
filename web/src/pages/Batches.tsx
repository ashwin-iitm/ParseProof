import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Layers, Plus, Trash2 } from "lucide-react";
import { api, type BatchListItem } from "@/api";
import { Button, PageHeader, ProgressBar, Skeleton } from "@/components/ui";
import { useToast } from "@/components/toast";
import { relativeTime } from "@/lib/format";

function Progress({ b }: { b: BatchListItem }) {
  if (b.active > 0) {
    return (
      <div className="w-[200px] space-y-1.5">
        <div className="text-xs text-ink-2">
          {b.done + b.failed} of {b.total} processed
        </div>
        <ProgressBar value={b.progress} />
      </div>
    );
  }
  return (
    <span className="text-sm text-ink-2">
      <span className="font-medium text-ink">{b.done}</span> of {b.total} complete
      {b.failed > 0 && <span className="text-fail"> · {b.failed} failed</span>}
    </span>
  );
}

export default function Batches() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const batches = useQuery({
    queryKey: ["batches"],
    queryFn: api.batches,
    refetchInterval: (q) => (q.state.data?.some((b) => b.active > 0) ? 2000 : false),
  });
  const remove = useMutation({
    mutationFn: api.deleteBatch,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["batches"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      toast("Batch deleted");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const list = batches.data ?? [];

  return (
    <div>
      <PageHeader
        title="Batches"
        description="Many documents run with one template. Review them as one table and export the results to Excel or CSV."
        actions={
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/new")}>
            New batch
          </Button>
        }
      />
      <div className="px-8 py-6 max-sm:px-4">
        {batches.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : batches.isError ? (
          <p className="text-sm text-fail">{(batches.error as Error).message}</p>
        ) : list.length === 0 ? (
          <div className="mx-auto max-w-[520px] py-16 text-center">
            <Layers className="mx-auto h-8 w-8 text-ink-3" strokeWidth={1.5} aria-hidden />
            <h2 className="mt-4 text-md font-semibold">No batches yet</h2>
            <p className="mt-2 text-sm text-ink-2">
              Select several files on the New run page. They run together with one template, and you get one table with a
              row per document and a column per field, ready to export.
            </p>
            <Button className="mt-5" variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/new")}>
              Start a batch
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-panel text-xs text-ink-3">
                  <th className="h-9 px-4 font-medium">Batch</th>
                  <th className="h-9 px-4 font-medium">Documents</th>
                  <th className="h-9 px-4 font-medium">QC result (fields)</th>
                  <th className="h-9 px-4 font-medium">Approved</th>
                  <th className="h-9 px-4 font-medium">Created</th>
                  <th className="h-9 w-[84px] px-4" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((b) => (
                  <tr
                    key={b.id}
                    onClick={() => navigate(`/batches/${b.id}`)}
                    className="group h-14 cursor-pointer border-b border-line transition-colors duration-150 last:border-0 hover:bg-paper/70"
                  >
                    <td className="px-4">
                      <div className="max-w-[320px] truncate font-medium text-ink">{b.name}</div>
                      <div className="text-xs text-ink-3">{b.template_name}</div>
                    </td>
                    <td className="px-4">
                      <Progress b={b} />
                    </td>
                    <td className="px-4 text-sm text-ink-2">
                      {b.done > 0 ? (
                        <span className="flex flex-wrap gap-x-3">
                          <span>
                            <span className="font-medium text-pass">{b.pass}</span> verified
                          </span>
                          {b.fail > 0 && (
                            <span>
                              <span className="font-medium text-fail">{b.fail}</span> mismatch{b.fail > 1 ? "es" : ""}
                            </span>
                          )}
                          {b.review > 0 && (
                            <span>
                              <span className="font-medium text-review">{b.review}</span> to review
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-ink-3">—</span>
                      )}
                    </td>
                    <td className="px-4 text-sm text-ink-2">
                      {b.approved} of {b.total}
                    </td>
                    <td className="whitespace-nowrap px-4 text-ink-2">{relativeTime(b.created_at)}</td>
                    <td className="px-4">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          className="rounded p-1.5 text-ink-3 opacity-0 transition hover:bg-fail-weak hover:text-fail focus-visible:opacity-100 group-hover:opacity-100"
                          aria-label={`Delete batch ${b.name}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (confirm(`Delete the batch "${b.name}" and its ${b.total} runs? The documents stay available.`)) remove.mutate(b.id);
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

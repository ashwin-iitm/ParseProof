import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus } from "lucide-react";
import { api } from "@/api";
import AIComposer from "@/components/AIComposer";
import { Button, PageHeader, Skeleton } from "@/components/ui";
import { fieldLabel, relativeTime } from "@/lib/format";

export default function Templates() {
  const navigate = useNavigate();
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const [composing, setComposing] = useState(false);

  return (
    <div>
      <PageHeader
        title="Templates"
        description="A template lists the fields to extract. Clear descriptions help both models find the right value."
        actions={
          <>
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/templates/new")}>
              Blank template
            </Button>
            <Button variant="primary" onClick={() => setComposing(true)} disabled={composing}>
              Create with AI
            </Button>
          </>
        }
      />
      <div className="px-8 py-6 max-sm:px-4">
        {composing && (
          <div className="mb-6 max-w-[760px]">
            <AIComposer
              onCancel={() => setComposing(false)}
              onDraft={(draft) => navigate("/templates/new", { state: { draft } })}
            />
          </div>
        )}
        {templates.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-panel text-xs text-ink-3">
                  <th className="h-9 px-4 font-medium">Name</th>
                  <th className="h-9 px-4 font-medium">Fields</th>
                  <th className="h-9 px-4 font-medium">Checks</th>
                  <th className="h-9 px-4 font-medium">Runs</th>
                  <th className="h-9 px-4 font-medium">Updated</th>
                  <th className="h-9 w-10 px-4" aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {(templates.data ?? []).map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => navigate(`/templates/${t.id}`)}
                    className="group cursor-pointer border-b border-line transition-colors duration-150 last:border-0 hover:bg-paper/70"
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium">{t.name}</div>
                      {t.description && <div className="mt-0.5 max-w-[420px] truncate text-xs text-ink-3">{t.description}</div>}
                    </td>
                    <td className="px-4 py-3 text-ink-2">
                      <span className="text-ink">{t.fields.length}</span>
                      <span className="ml-2 hidden max-w-[260px] truncate align-bottom text-xs text-ink-3 xl:inline-block">
                        {t.fields.slice(0, 4).map(fieldLabel).join(", ")}
                        {t.fields.length > 4 && "…"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink-2">{t.rules.length ? `${t.rules.length} sum rule${t.rules.length > 1 ? "s" : ""}` : "—"}</td>
                    <td className="px-4 py-3 text-ink-2">{t.run_count ?? 0}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-ink-2">{relativeTime(t.updated_at)}</td>
                    <td className="px-4 py-3">
                      <ArrowRight className="h-4 w-4 text-ink-3 transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-ink" aria-hidden />
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

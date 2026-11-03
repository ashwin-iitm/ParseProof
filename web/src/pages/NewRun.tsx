import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import AIComposer from "@/components/AIComposer";
import clsx from "clsx";
import { FileText, Search, Upload, X } from "lucide-react";
import { api, type DocumentRow } from "@/api";
import { Button, Input, Label, PageHeader, Skeleton } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fileSize, relativeTime } from "@/lib/format";

const ACCEPT = ".pdf,.docx,.xlsx,.xls,.csv,.txt";
const UPLOAD_PARALLEL = 3;

/** A document chosen for the run: a local file not yet uploaded, or one already on the server. */
type Chosen = { key: string; file: File; doc?: undefined } | { key: string; doc: DocumentRow; file?: undefined };

const fileKey = (f: File) => `file:${f.name}:${f.size}:${f.lastModified}`;

export default function NewRun() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [params] = useSearchParams();
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [templateId, setTemplateId] = useState<string>(params.get("template") ?? "");
  const [batchName, setBatchName] = useState("");
  const [filter, setFilter] = useState("");
  const [dragging, setDragging] = useState(false);
  const [starting, setStarting] = useState(false);
  const [progress, setProgress] = useState("");
  const [composing, setComposing] = useState(false);

  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const documents = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  // Coming back from the template editor: restore the documents that were chosen
  const docsParam = params.get("docs") ?? params.get("doc");
  useEffect(() => {
    if (!docsParam || chosen.length || !documents.data) return;
    const ids = docsParam.split(",");
    const docs = ids.map((id) => documents.data.find((d) => d.id === id)).filter((d): d is DocumentRow => !!d);
    setChosen(docs.map((doc) => ({ key: doc.id, doc })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docsParam, documents.data]);

  const selectedTemplate = templateId || templates.data?.[0]?.id || "";
  const templateName = templates.data?.find((t) => t.id === selectedTemplate)?.name ?? "";
  const chosenIds = useMemo(() => new Set(chosen.map((c) => c.key)), [chosen]);
  const count = chosen.length;

  const addFiles = (list: FileList | null | undefined) => {
    if (!list?.length) return;
    const files = Array.from(list);
    setChosen((prev) => {
      const have = new Set(prev.map((c) => c.key));
      return [...prev, ...files.filter((f) => !have.has(fileKey(f))).map((file) => ({ key: fileKey(file), file }))];
    });
  };

  const toggleDoc = (doc: DocumentRow) =>
    setChosen((prev) => (prev.some((c) => c.key === doc.id) ? prev.filter((c) => c.key !== doc.id) : [...prev, { key: doc.id, doc }]));

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  /** Upload every chosen file that isn't on the server yet. Returns the document ids in order. */
  const uploadPending = async (): Promise<{ ids: string[]; failed: string[] }> => {
    const pending = chosen.filter((c) => c.file);
    const uploaded = new Map<string, DocumentRow>();
    const failed: string[] = [];
    let next = 0;
    let finished = 0;
    const worker = async () => {
      while (next < pending.length) {
        const item = pending[next++];
        try {
          uploaded.set(item.key, await api.upload(item.file!));
        } catch (e) {
          failed.push(`${item.file!.name}: ${(e as Error).message}`);
        }
        finished += 1;
        if (pending.length > 1) setProgress(`Uploading ${finished} of ${pending.length}…`);
      }
    };
    if (pending.length) {
      setProgress(pending.length > 1 ? `Uploading 0 of ${pending.length}…` : "Uploading…");
      await Promise.all(Array.from({ length: Math.min(UPLOAD_PARALLEL, pending.length) }, worker));
      qc.invalidateQueries({ queryKey: ["documents"] });
    }
    const next_: Chosen[] = [];
    for (const c of chosen) {
      if (c.doc) next_.push(c);
      else if (uploaded.has(c.key)) next_.push({ key: uploaded.get(c.key)!.id, doc: uploaded.get(c.key)! });
    }
    setChosen(next_);
    return { ids: next_.map((c) => c.doc!.id), failed };
  };

  /** Upload once, so the choice survives a trip to the template editor. */
  const returnPath = async () => {
    const { ids } = await uploadPending().catch(() => ({ ids: [] as string[] }));
    setProgress("");
    return ids.length ? `/new?docs=${ids.join(",")}` : "/new";
  };

  const start = async () => {
    setStarting(true);
    try {
      const { ids, failed } = await uploadPending();
      if (failed.length) {
        toast(failed.length === 1 ? failed[0] : `${failed.length} files could not be uploaded. First: ${failed[0]}`, "error");
      }
      if (!ids.length) {
        setStarting(false);
        setProgress("");
        return;
      }
      setProgress("Starting…");
      if (ids.length === 1) {
        const run = await api.createRun(ids[0], selectedTemplate);
        navigate(`/runs/${run.id}`);
      } else {
        const batch = await api.createBatch(selectedTemplate, ids, batchName);
        qc.invalidateQueries({ queryKey: ["batches"] });
        navigate(`/batches/${batch.id}`);
      }
    } catch (e) {
      toast((e as Error).message, "error");
      setStarting(false);
      setProgress("");
    }
  };

  const library = (documents.data ?? []).filter((d) => !filter || d.filename.toLowerCase().includes(filter.toLowerCase()));
  const allShownChosen = library.length > 0 && library.every((d) => chosenIds.has(d.id));

  return (
    <div>
      <PageHeader
        title="New run"
        description="Choose one or more documents and the template that describes what to extract. Several documents run as a batch you can review and export as one table."
      />

      <div className="grid max-w-[1180px] gap-8 px-8 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] max-sm:px-4">
        <section aria-labelledby="doc-heading" className="min-w-0">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="doc-heading" className="text-sm font-semibold">
              Documents {count > 0 && <span className="font-normal text-ink-3">· {count} selected</span>}
            </h2>
            {count > 0 && (
              <button className="text-xs font-medium text-ink-2 hover:text-ink hover:underline" onClick={() => setChosen([])}>
                Clear all
              </button>
            )}
          </div>

          <div
            role="button"
            tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={clsx(
              "flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed px-6 text-center transition-colors duration-150",
              count ? "py-5" : "py-10",
              dragging ? "border-accent bg-accent-weak" : "border-line-strong bg-surface hover:border-ink-3 hover:bg-panel",
            )}
          >
            <Upload className="h-5 w-5 text-ink-3" strokeWidth={1.75} aria-hidden />
            <p className="mt-2.5 text-sm font-medium">{count ? "Add more files" : "Drop files here or browse"}</p>
            <p className="mt-1 text-xs text-ink-3">Select many at once · PDF (including scans), Word, Excel, CSV or text · up to 100 MB each</p>
          </div>
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />

          {count > 0 && (
            <ul className="mt-3 max-h-[300px] divide-y divide-line overflow-auto rounded-lg border border-line bg-surface">
              {chosen.map((c) => (
                <li key={c.key} className="flex items-center gap-3 px-3.5 py-2">
                  <FileText className="h-4 w-4 shrink-0 text-ink-3" strokeWidth={1.75} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{c.file?.name ?? c.doc?.filename}</div>
                    <div className="text-xs text-ink-3">
                      {c.file ? `${fileSize(c.file.size)} · ready to upload` : `${c.doc!.pages ? `${c.doc!.pages} pages · ` : ""}uploaded ${relativeTime(c.doc!.created_at)}`}
                    </div>
                  </div>
                  <button
                    className="rounded p-1 text-ink-3 hover:bg-ink/5 hover:text-ink disabled:opacity-40"
                    onClick={() => setChosen((prev) => prev.filter((p) => p.key !== c.key))}
                    aria-label={`Remove ${c.file?.name ?? c.doc?.filename}`}
                    disabled={starting}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {(documents.data?.length ?? 0) > 0 && (
            <div className="mt-6">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-xs font-medium text-ink-3">Or pick documents already uploaded</h3>
                {library.length > 1 && (
                  <button
                    className="text-xs font-medium text-accent hover:underline"
                    onClick={() =>
                      setChosen((prev) =>
                        allShownChosen
                          ? prev.filter((c) => !library.some((d) => d.id === c.key))
                          : [...prev, ...library.filter((d) => !chosenIds.has(d.id)).map((doc) => ({ key: doc.id, doc }))],
                      )
                    }
                  >
                    {allShownChosen ? "Deselect these" : `Select ${filter ? "these" : "all"} (${library.length})`}
                  </button>
                )}
              </div>
              {(documents.data?.length ?? 0) > 6 && (
                <div className="relative mb-2">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-ink-3" aria-hidden />
                  <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by file name" className="pl-8" aria-label="Filter documents" />
                </div>
              )}
              <ul className="max-h-[280px] divide-y divide-line overflow-auto rounded-lg border border-line bg-surface">
                {library.map((d) => (
                  <li key={d.id}>
                    <label className="flex cursor-pointer items-center gap-3 px-3.5 py-2 text-sm transition-colors duration-150 hover:bg-panel">
                      <input
                        type="checkbox"
                        checked={chosenIds.has(d.id)}
                        onChange={() => toggleDoc(d)}
                        className="h-4 w-4 shrink-0 cursor-pointer accent-[rgb(var(--accent))]"
                      />
                      <span className="min-w-0 flex-1 truncate">{d.filename}</span>
                      <span className="shrink-0 text-xs text-ink-3">
                        {d.pages ? `${d.pages} pp · ` : ""}
                        {relativeTime(d.created_at)}
                      </span>
                    </label>
                  </li>
                ))}
                {library.length === 0 && <li className="px-3.5 py-3 text-sm text-ink-3">No documents match “{filter}”.</li>}
              </ul>
            </div>
          )}
        </section>

        <section aria-labelledby="tpl-heading" className="min-w-0">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="tpl-heading" className="text-sm font-semibold">Template</h2>
            {!composing && (
              <button className="text-xs font-medium text-accent hover:underline" onClick={() => setComposing(true)}>
                Create with AI
              </button>
            )}
          </div>
          {composing && (
            <div className="mb-4">
              <AIComposer
                sampleName={chosen[0] ? (chosen[0].file?.name ?? chosen[0].doc?.filename) : null}
                resolveSample={async () => (await uploadPending()).ids[0] ?? null}
                onCancel={() => setComposing(false)}
                onDraft={async (draft) => {
                  navigate("/templates/new", { state: { draft, returnTo: await returnPath() } });
                }}
              />
            </div>
          )}
          {templates.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <div role="radiogroup" className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
              {(templates.data ?? []).map((t) => {
                const active = t.id === selectedTemplate;
                return (
                  <label
                    key={t.id}
                    className={clsx(
                      "flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors duration-150",
                      active ? "bg-accent-weak/60" : "hover:bg-panel",
                    )}
                  >
                    <input
                      type="radio"
                      name="template"
                      checked={active}
                      onChange={() => setTemplateId(t.id)}
                      className="mt-1 h-4 w-4 accent-[rgb(var(--accent))]"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline justify-between gap-3">
                        <span className="font-medium">{t.name}</span>
                        <span className="shrink-0 text-xs text-ink-3">{t.fields.length} fields</span>
                      </span>
                      {t.description && <span className="mt-0.5 block text-xs text-ink-2">{t.description}</span>}
                      {active && (
                        <button
                          type="button"
                          className="mt-1.5 text-xs font-medium text-accent hover:underline"
                          onClick={async (e) => {
                            e.preventDefault();
                            navigate(`/templates/${t.id}`, { state: { returnTo: await returnPath() } });
                          }}
                        >
                          Edit fields
                        </button>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          )}

          {count > 1 && (
            <div className="mt-5">
              <Label htmlFor="batch-name" hint="Shown on the Batches page and used as the export file name.">
                Batch name
              </Label>
              <Input
                id="batch-name"
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
                placeholder={`${templateName || "Batch"} · ${new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`}
              />
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
            {settings.data && !settings.data.openai_key_set && (
              <Link to="/settings" className="mr-auto text-xs text-fail hover:underline">
                Add an OpenAI API key first
              </Link>
            )}
            {progress && <span className="mr-auto text-xs text-ink-2" aria-live="polite">{progress}</span>}
            <Button variant="ghost" onClick={() => navigate("/")} disabled={starting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={starting}
              disabled={!count || !selectedTemplate || !settings.data?.openai_key_set}
              onClick={start}
            >
              {count > 1 ? `Extract and verify ${count} documents` : "Extract and verify"}
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowLeft, ArrowUp, Plus, Trash2, X } from "lucide-react";
import { api, type Field, type SumRule, type TemplateDraft } from "@/api";
import { Button, Checkbox, Input, Label, Select, Skeleton, Textarea } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fieldLabel, humanize, toKey } from "@/lib/format";

const blankField = (): Field => ({ name: "", label: "", description: "", type: "string", required: false });

export default function TemplateEditor() {
  const { id = "new" } = useParams();
  const isNew = id === "new";
  const navigate = useNavigate();
  const location = useLocation();
  const { draft, returnTo } = (location.state ?? {}) as { draft?: TemplateDraft; returnTo?: string };
  const [fromAI, setFromAI] = useState(!!draft);
  const qc = useQueryClient();
  const toast = useToast();
  const existing = useQuery({ queryKey: ["template", id], queryFn: () => api.template(id), enabled: !isNew });

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [fields, setFields] = useState<Field[]>([blankField()]);
  const [rules, setRules] = useState<SumRule[]>([]);
  const [keyTouched, setKeyTouched] = useState<Record<number, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!draft || !isNew) return;
    setName(draft.name);
    setDescription(draft.description);
    setFields(draft.fields.map((f) => ({ ...f, label: f.label || humanize(f.name) })));
    setRules(draft.rules);
    setKeyTouched(Object.fromEntries(draft.fields.map((_, i) => [i, true])));
  }, [draft, isNew]);

  useEffect(() => {
    if (!existing.data) return;
    setName(existing.data.name);
    setDescription(existing.data.description);
    setFields(existing.data.fields.map((f) => ({ ...f, label: f.label || humanize(f.name) })));
    setRules(existing.data.rules);
    setKeyTouched(Object.fromEntries(existing.data.fields.map((_, i) => [i, true])));
  }, [existing.data]);

  const update = (i: number, patch: Partial<Field>) => setFields((fs) => fs.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const move = (i: number, d: -1 | 1) =>
    setFields((fs) => {
      const j = i + d;
      if (j < 0 || j >= fs.length) return fs;
      const next = [...fs];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  const numberFields = fields.filter((f) => f.type === "number" && f.name);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const body = { name, description, fields: fields.map((f) => ({ ...f, name: f.name || toKey(f.label) })), rules };
      const saved = isNew ? await api.createTemplate(body) : await api.updateTemplate(id, body);
      qc.invalidateQueries({ queryKey: ["templates"] });
      qc.setQueryData(["template", saved.id], saved);
      toast(isNew ? "Template created" : "Template saved");
      setFromAI(false);
      if (returnTo) navigate(`${returnTo}${returnTo.includes("?") ? "&" : "?"}template=${saved.id}`);
      else if (isNew) navigate(`/templates/${saved.id}`, { replace: true });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete the template "${name}"? Past runs keep their results.`)) return;
    try {
      await api.deleteTemplate(id);
      qc.invalidateQueries({ queryKey: ["templates"] });
      toast("Template deleted");
      navigate("/templates");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  if (!isNew && existing.isLoading) {
    return (
      <div className="space-y-3 p-8">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="pb-24">
      <div className="border-b border-line px-8 pb-5 pt-6 max-sm:px-4">
        <Link to={returnTo ?? "/templates"} className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
          <ArrowLeft className="h-4 w-4" aria-hidden />
          {returnTo ? "Back to new run" : "Templates"}
        </Link>
        <h1 className="mt-3 text-xl font-semibold tracking-[-0.01em]">{isNew ? (fromAI ? "Review drafted template" : "New template") : name || "Untitled template"}</h1>
      </div>

      {fromAI && (
        <div className="mx-8 mt-6 max-w-[1080px] rounded-lg border border-accent/25 bg-accent-weak/60 px-4 py-3 text-sm max-sm:mx-4">
          <p className="text-ink">
            AI drafted {fields.length} field{fields.length === 1 ? "" : "s"}
            {rules.length > 0 && ` and ${rules.length} sum check${rules.length === 1 ? "" : "s"}`}. Rename, remove or add fields, then{" "}
            {isNew ? "create the template" : "save"}.
          </p>
          <p className="mt-0.5 text-xs text-ink-2">The descriptions are what the extraction and verification models read, so make them specific to your documents.</p>
          {(draft?.warnings ?? []).map((w, i) => (
            <p key={i} className="mt-1.5 text-xs text-review">{w}</p>
          ))}
        </div>
      )}

      <div className="max-w-[1080px] space-y-8 px-8 py-6 max-sm:px-4">
        <section className="grid gap-4 md:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          <div>
            <Label htmlFor="tpl-name">Name</Label>
            <Input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Supplier invoice" />
          </div>
          <div>
            <Label htmlFor="tpl-desc">Description</Label>
            <Input id="tpl-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Which documents this template is for" />
          </div>
        </section>

        <section aria-labelledby="fields-heading">
          <div className="mb-3 flex items-end justify-between">
            <div>
              <h2 id="fields-heading" className="text-sm font-semibold">Fields</h2>
              <p className="mt-0.5 text-xs text-ink-3">The description is what the models read. Say where the value usually appears and what it looks like.</p>
            </div>
            <span className="text-xs text-ink-3">{fields.length} field{fields.length === 1 ? "" : "s"}</span>
          </div>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[880px] text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-panel text-xs text-ink-3">
                  <th className="h-9 w-[210px] px-3 font-medium">Label</th>
                  <th className="h-9 w-[170px] px-3 font-medium">Key</th>
                  <th className="h-9 px-3 font-medium">Description</th>
                  <th className="h-9 w-[132px] px-3 font-medium">Type</th>
                  <th className="h-9 w-[84px] px-3 font-medium">Required</th>
                  <th className="h-9 w-[92px] px-3" aria-label="Row actions" />
                </tr>
              </thead>
              <tbody>
                {fields.map((f, i) => (
                  <tr key={i} className="border-b border-line align-top last:border-0">
                    <td className="px-3 py-2">
                      <Input
                        value={f.label}
                        placeholder="Invoice number"
                        aria-label={`Label for field ${i + 1}`}
                        onChange={(e) => update(i, { label: e.target.value, ...(keyTouched[i] ? {} : { name: toKey(e.target.value) }) })}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Input
                        value={f.name}
                        placeholder="invoice_number"
                        aria-label={`Key for field ${i + 1}`}
                        className="font-mono text-[13px]"
                        onChange={(e) => {
                          setKeyTouched((t) => ({ ...t, [i]: true }));
                          update(i, { name: e.target.value });
                        }}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Textarea
                        rows={1}
                        value={f.description}
                        placeholder="Invoice number or reference, top right of the first page"
                        aria-label={`Description for field ${i + 1}`}
                        className="min-h-8 resize-y"
                        onChange={(e) => update(i, { description: e.target.value })}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Select value={f.type} onChange={(e) => update(i, { type: e.target.value as Field["type"] })} aria-label={`Type for field ${i + 1}`}>
                        <option value="string">Text</option>
                        <option value="number">Number</option>
                        <option value="date">Date</option>
                      </Select>
                    </td>
                    <td className="px-3 py-2 pt-3.5">
                      <Checkbox checked={f.required} onChange={(v) => update(i, { required: v })} label="" id={`req-${i}`} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-0.5 pt-0.5">
                        <button className="rounded p-1 text-ink-3 hover:bg-ink/5 hover:text-ink disabled:opacity-30" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">
                          <ArrowUp className="h-4 w-4" />
                        </button>
                        <button className="rounded p-1 text-ink-3 hover:bg-ink/5 hover:text-ink disabled:opacity-30" disabled={i === fields.length - 1} onClick={() => move(i, 1)} aria-label="Move down">
                          <ArrowDown className="h-4 w-4" />
                        </button>
                        <button
                          className="rounded p-1 text-ink-3 hover:bg-fail-weak hover:text-fail disabled:opacity-30"
                          disabled={fields.length === 1}
                          onClick={() => setFields((fs) => fs.filter((_, idx) => idx !== i))}
                          aria-label="Remove field"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Button className="mt-3" icon={<Plus className="h-4 w-4" />} onClick={() => setFields((fs) => [...fs, blankField()])}>
            Add field
          </Button>
        </section>

        <section aria-labelledby="rules-heading">
          <h2 id="rules-heading" className="text-sm font-semibold">Sum checks</h2>
          <p className="mt-0.5 text-xs text-ink-3">
            Flag a run when amounts don't add up, for example subtotal + tax = total. Uses number fields.
          </p>
          <div className="mt-3 space-y-2">
            {rules.map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2.5">
                <div className="flex flex-wrap gap-1.5">
                  {numberFields.map((f) => {
                    const on = r.fields.includes(f.name);
                    return (
                      <button
                        key={f.name}
                        onClick={() =>
                          setRules((rs) => rs.map((x, idx) => (idx === i ? { ...x, fields: on ? x.fields.filter((n) => n !== f.name) : [...x.fields, f.name] } : x)))
                        }
                        className={clsx(
                          "rounded-full border px-2.5 py-0.5 text-xs transition-colors duration-150",
                          on ? "border-accent bg-accent-weak text-accent" : "border-line-strong text-ink-2 hover:border-ink-3",
                        )}
                        aria-pressed={on}
                      >
                        {fieldLabel(f)}
                      </button>
                    );
                  })}
                </div>
                <span className="text-sm text-ink-3">must equal</span>
                <Select
                  className="w-auto min-w-[160px]"
                  value={r.equals}
                  onChange={(e) => setRules((rs) => rs.map((x, idx) => (idx === i ? { ...x, equals: e.target.value } : x)))}
                  aria-label="Total field"
                >
                  <option value="">Choose field</option>
                  {numberFields.map((f) => (
                    <option key={f.name} value={f.name}>
                      {fieldLabel(f)}
                    </option>
                  ))}
                </Select>
                <button className="ml-auto rounded p-1 text-ink-3 hover:bg-fail-weak hover:text-fail" onClick={() => setRules((rs) => rs.filter((_, idx) => idx !== i))} aria-label="Remove check">
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
          <Button
            className="mt-3"
            icon={<Plus className="h-4 w-4" />}
            disabled={numberFields.length < 2}
            title={numberFields.length < 2 ? "Needs at least two number fields with keys" : undefined}
            onClick={() => setRules((rs) => [...rs, { type: "sum", fields: [], equals: "", tolerance: 0.01 }])}
          >
            Add sum check
          </Button>
        </section>
      </div>

      <div className="fixed bottom-0 left-[216px] right-0 border-t border-line bg-panel/95 px-8 py-3 backdrop-blur max-md:left-0 max-sm:px-4">
        <div className="flex max-w-[1080px] items-center gap-3">
          {error && <p className="min-w-0 flex-1 truncate text-sm text-fail" title={error}>{error}</p>}
          {!isNew && (
            <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={remove} className={error ? "" : "mr-auto"}>
              Delete
            </Button>
          )}
          <div className={clsx("flex gap-2", isNew && !error && "ml-auto")}>
            <Button variant="ghost" onClick={() => navigate(returnTo ?? "/templates")}>
              Cancel
            </Button>
            <Button variant="primary" loading={saving} onClick={save}>
              {isNew ? (returnTo ? "Create and use template" : "Create template") : returnTo ? "Save and use template" : "Save changes"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

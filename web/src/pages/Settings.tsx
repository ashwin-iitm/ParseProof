import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, AlertCircle, Plus, Trash2 } from "lucide-react";
import { api, type PriceRow } from "@/api";
import { Button, Input, Label, PageHeader, Panel, Select, Skeleton } from "@/components/ui";
import { useToast } from "@/components/toast";

const MODEL_FIELDS = [
  { key: "extract", label: "Extraction model", hint: "Reads each document (text and page images) and extracts the fields. Also does the self-check and drafts templates." },
  { key: "qc", label: "Verification model", hint: "Checks each value on its source page." },
  { key: "ocr", label: "OCR model", hint: "Transcribes scanned pages so the verifier can search them." },
] as const;

const KIND_NOTE: Record<string, string> = {
  embedding: "Embedding model, used for every document's search index",
  local: "Runs on this computer, always free",
};

type Draft = { model: string; input: string; output: string; kind?: PriceRow["kind"] };
const toDraft = (rows: PriceRow[]): Draft[] => rows.map((r) => ({ model: r.model, input: String(r.input), output: String(r.output), kind: r.kind }));

export default function Settings() {
  const qc = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [key, setKey] = useState("");
  const [models, setModels] = useState({ extract: "", qc: "", ocr: "" });
  const [prices, setPrices] = useState<Draft[]>([]);
  const [savingKey, setSavingKey] = useState(false);
  const [savingModels, setSavingModels] = useState(false);
  const [savingPrices, setSavingPrices] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    if (settings.data) {
      setModels(settings.data.models);
      setPrices(toDraft(settings.data.prices));
    }
  }, [settings.data]);

  const saveKey = async () => {
    setSavingKey(true);
    setTest(null);
    try {
      qc.setQueryData(["settings"], await api.saveSettings({ openai_api_key: key }));
      setKey("");
      toast("API key saved");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSavingKey(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    try {
      const r = await api.testSettings();
      setTest(
        r.ok
          ? { ok: true, message: r.model_available === false ? `Connected, but "${models.extract}" is not available to this key.` : "Connected. The key works." }
          : { ok: false, message: r.error || "Connection failed." },
      );
    } catch (e) {
      setTest({ ok: false, message: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  const saveModels = async () => {
    setSavingModels(true);
    try {
      qc.setQueryData(["settings"], await api.saveSettings({ extract_model: models.extract, qc_model: models.qc, ocr_model: models.ocr }));
      toast("Models saved");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSavingModels(false);
    }
  };

  // Rows that can't be sent: an empty or repeated name, or a price that isn't a number of 0 or more
  const problem = useMemo(() => {
    const seen = new Set<string>();
    for (const p of prices) {
      const name = p.model.trim();
      if (!name) return "Every row needs a model name.";
      if (seen.has(name)) return `${name} is listed twice.`;
      seen.add(name);
      for (const v of [p.input, p.output]) if (v.trim() === "" || !(Number(v) >= 0)) return `Prices for ${name} must be numbers of 0 or more.`;
    }
    return null;
  }, [prices]);

  const savePrices = async () => {
    setSavingPrices(true);
    try {
      const body = prices.filter((p) => p.kind !== "local").map((p) => ({ model: p.model.trim(), input: Number(p.input), output: Number(p.output) }));
      qc.setQueryData(["settings"], await api.saveSettings({ prices: body }));
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run"] });
      toast("Prices saved. Costs everywhere now use them.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSavingPrices(false);
    }
  };

  const resetPrices = async () => {
    if (!confirm("Replace the price list with OpenAI's standard prices? Models you added will be removed from it.")) return;
    setSavingPrices(true);
    try {
      qc.setQueryData(["settings"], await api.saveSettings({ reset_prices: true }));
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run"] });
      toast("Prices reset");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSavingPrices(false);
    }
  };

  const s = settings.data;
  // The models you can pick are the chat models in the price list (as edited, so a new row shows at once)
  const choices = prices.filter((p) => (p.kind ?? "chat") === "chat" && p.model.trim()).map((p) => p.model.trim());
  const pricesChanged = !!s && JSON.stringify(toDraft(s.prices)) !== JSON.stringify(prices);

  return (
    <div>
      <PageHeader title="Settings" description="ParseProof runs on this machine. The only outside service it calls is OpenAI." />
      <div className="max-w-[820px] space-y-6 px-8 py-6 max-sm:px-4">
        {!s ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            <Panel>
              <div className="border-b border-line px-5 py-4">
                <h2 className="text-sm font-semibold">OpenAI API key</h2>
                <p className="mt-0.5 text-xs text-ink-3">Stored in the .env file next to the server. Used for extraction, verification, OCR and search.</p>
              </div>
              <div className="space-y-4 px-5 py-4">
                <div className="flex items-center gap-2 text-sm">
                  {s.openai_key_set ? (
                    <>
                      <CheckCircle2 className="h-4 w-4 text-pass" aria-hidden />
                      <span>
                        Key set <span className="font-mono text-[13px] text-ink-2">{s.openai_key_hint}</span>
                      </span>
                    </>
                  ) : (
                    <>
                      <AlertCircle className="h-4 w-4 text-fail" aria-hidden />
                      <span>No key set. Runs can't start until you add one.</span>
                    </>
                  )}
                </div>
                <form
                  className="flex gap-2 max-sm:flex-col"
                  onSubmit={(e) => {
                    e.preventDefault();
                    saveKey();
                  }}
                >
                  <Input
                    type="password"
                    autoComplete="off"
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder={s.openai_key_set ? "Paste a new key to replace it" : "sk-..."}
                    aria-label="OpenAI API key"
                    className="font-mono text-[13px]"
                  />
                  <Button type="submit" variant="primary" disabled={!key.trim()} loading={savingKey}>
                    Save key
                  </Button>
                  <Button type="button" onClick={runTest} loading={testing} disabled={!s.openai_key_set}>
                    Test connection
                  </Button>
                </form>
                {test && (
                  <p className={test.ok ? "text-sm text-pass" : "text-sm text-fail"} role="status">
                    {test.message}
                  </p>
                )}
              </div>
            </Panel>

            <Panel>
              <div className="border-b border-line px-5 py-4">
                <h2 className="text-sm font-semibold">Models</h2>
                <p className="mt-0.5 text-xs text-ink-3">Pick from the models in the price list below. To use another model, add it to the list first. Changes apply to new runs.</p>
              </div>
              <div className="space-y-4 px-5 py-4">
                {MODEL_FIELDS.map((m) => {
                  const current = models[m.key];
                  const options = choices.includes(current) || !current ? choices : [current, ...choices];
                  return (
                    <div key={m.key} className="grid gap-1 md:grid-cols-[220px_minmax(0,1fr)] md:gap-4">
                      <Label htmlFor={`model-${m.key}`} hint={m.hint}>
                        {m.label}
                      </Label>
                      <div>
                        <Select
                          id={`model-${m.key}`}
                          value={current}
                          onChange={(e) => setModels((x) => ({ ...x, [m.key]: e.target.value }))}
                          className="w-full font-mono text-[13px]"
                        >
                          {options.map((o) => (
                            <option key={o} value={o}>
                              {o}
                              {choices.includes(o) ? "" : " (not in the price list)"}
                            </option>
                          ))}
                        </Select>
                        {current !== s.defaults[m.key] && (
                          <button className="mt-1 text-xs text-accent hover:underline" onClick={() => setModels((x) => ({ ...x, [m.key]: s.defaults[m.key] }))}>
                            Reset to {s.defaults[m.key]}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
                <div className="flex justify-end">
                  <Button variant="primary" onClick={saveModels} loading={savingModels}>
                    Save models
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel>
              <div className="border-b border-line px-5 py-4">
                <h2 className="text-sm font-semibold">Model prices</h2>
                <p className="mt-0.5 text-xs text-ink-3">
                  US dollars per 1 million tokens. Used for the cost of every run, the Runs list, the Run report and the Excel export, including older runs. Now using{" "}
                  {s.prices_source}.{" "}
                  <a className="text-accent hover:underline" href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noreferrer">
                    OpenAI's price page
                  </a>
                </p>
              </div>
              <div className="px-5 py-4">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead>
                      <tr className="text-left text-xs text-ink-3">
                        <th className="pb-2 font-medium">Model name</th>
                        <th className="w-[130px] pb-2 font-medium">Input $ / 1M</th>
                        <th className="w-[130px] pb-2 font-medium">Output $ / 1M</th>
                        <th className="w-10 pb-2" aria-label="Remove" />
                      </tr>
                    </thead>
                    <tbody>
                      {prices.map((p, i) => {
                        const fixed = p.kind === "embedding" || p.kind === "local";
                        const set = (patch: Partial<Draft>) => setPrices((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
                        return (
                          <tr key={i} className="border-t border-line align-top">
                            <td className="py-2 pr-2">
                              {fixed ? (
                                <div className="pt-1.5">
                                  <span className="font-mono text-[13px]">{p.model}</span>
                                  <span className="block text-xs text-ink-3">{KIND_NOTE[p.kind!]}</span>
                                </div>
                              ) : (
                                <Input value={p.model} onChange={(e) => set({ model: e.target.value })} placeholder="e.g. gpt-4.1-nano" aria-label="Model name" className="font-mono text-[13px]" />
                              )}
                            </td>
                            <td className="py-2 pr-2">
                              <Input inputMode="decimal" value={p.input} disabled={p.kind === "local"} onChange={(e) => set({ input: e.target.value })} aria-label={`Input price for ${p.model || "new model"}`} className="tabular-nums" />
                            </td>
                            <td className="py-2 pr-2">
                              <Input inputMode="decimal" value={p.output} disabled={fixed} onChange={(e) => set({ output: e.target.value })} aria-label={`Output price for ${p.model || "new model"}`} className="tabular-nums" />
                            </td>
                            <td className="py-2">
                              {!fixed && (
                                <button
                                  className="mt-1 rounded p-1.5 text-ink-3 hover:bg-fail-weak hover:text-fail"
                                  aria-label={`Remove ${p.model || "row"}`}
                                  onClick={() => setPrices((rows) => rows.filter((_, j) => j !== i))}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap gap-2">
                    <Button
                      icon={<Plus className="h-4 w-4" />}
                      onClick={() => setPrices((rows) => [...rows.filter((r) => (r.kind ?? "chat") === "chat"), { model: "", input: "", output: "", kind: "chat" }, ...rows.filter((r) => r.kind && r.kind !== "chat")])}
                    >
                      Add model
                    </Button>
                    <Button variant="ghost" onClick={resetPrices} disabled={savingPrices}>
                      Reset to OpenAI's prices
                    </Button>
                  </div>
                  <div className="flex items-center gap-3">
                    {problem && pricesChanged && <span className="text-xs text-fail">{problem}</span>}
                    <Button variant="primary" onClick={savePrices} loading={savingPrices} disabled={!pricesChanged || !!problem}>
                      Save prices
                    </Button>
                  </div>
                </div>
              </div>
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}

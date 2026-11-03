import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/api";
import { Button, Input, Label, PageHeader, Panel, Skeleton } from "@/components/ui";
import { useToast } from "@/components/toast";

const MODEL_FIELDS = [
  { key: "extract", label: "Extraction model", hint: "Reads each document (text and page images) and extracts the fields." },
  { key: "qc", label: "Verification model", hint: "Checks each value on its source page. Use a different model from extraction." },
  { key: "ocr", label: "OCR model", hint: "Transcribes scanned pages so the verifier can search them." },
] as const;

export default function Settings() {
  const qc = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [key, setKey] = useState("");
  const [models, setModels] = useState({ extract: "", qc: "", ocr: "" });
  const [savingKey, setSavingKey] = useState(false);
  const [savingModels, setSavingModels] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    if (settings.data) setModels(settings.data.models);
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

  const s = settings.data;

  return (
    <div>
      <PageHeader title="Settings" description="AdoVerse runs on this machine. The only outside service it calls is OpenAI." />
      <div className="max-w-[760px] space-y-6 px-8 py-6 max-sm:px-4">
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
                <p className="mt-0.5 text-xs text-ink-3">Any OpenAI model name your key can use. Changes apply to new runs.</p>
              </div>
              <div className="space-y-4 px-5 py-4">
                {MODEL_FIELDS.map((m) => (
                  <div key={m.key} className="grid gap-1 md:grid-cols-[220px_minmax(0,1fr)] md:gap-4">
                    <Label htmlFor={`model-${m.key}`} hint={m.hint}>
                      {m.label}
                    </Label>
                    <div>
                      <Input
                        id={`model-${m.key}`}
                        value={models[m.key]}
                        onChange={(e) => setModels((x) => ({ ...x, [m.key]: e.target.value }))}
                        className="font-mono text-[13px]"
                      />
                      {models[m.key] !== s.defaults[m.key] && (
                        <button className="mt-1 text-xs text-accent hover:underline" onClick={() => setModels((x) => ({ ...x, [m.key]: s.defaults[m.key] }))}>
                          Reset to {s.defaults[m.key]}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
                <div className="flex justify-end">
                  <Button variant="primary" onClick={saveModels} loading={savingModels}>
                    Save models
                  </Button>
                </div>
              </div>
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}

export type QCStatus = "PASS" | "FAIL" | "REVIEW" | "ABSENT" | "NOT_CHECKED";
export type RunStatus = "queued" | "running" | "done" | "failed";
export type FieldType = "string" | "number" | "date";

export interface DocumentRow {
  id: string;
  filename: string;
  size: number;
  pages: number | null;
  content_type: string;
  created_at: number;
  run_count?: number;
}

export interface Field {
  name: string;
  label: string;
  description: string;
  type: FieldType;
  required: boolean;
}

export interface SumRule {
  type: "sum";
  fields: string[];
  equals: string;
  tolerance: number;
}

export interface Template {
  id: string;
  name: string;
  description: string;
  fields: Field[];
  rules: SumRule[];
  created_at: number;
  updated_at: number;
  run_count?: number;
}

export type TemplateDraft = Pick<Template, "name" | "description" | "fields" | "rules"> & { warnings?: string[] };

export interface Summary {
  PASS: number;
  FAIL: number;
  REVIEW: number;
  ABSENT?: number;
  NOT_CHECKED: number;
}

export interface RunListItem {
  id: string;
  document_id: string;
  template_id: string;
  template_name: string;
  status: RunStatus;
  stage: string;
  progress: number;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  approved_at: number | null;
  review: Record<string, ReviewDecision>;
  summary: Summary | null;
  seconds: number | null;
  tokens: number | null;
  cost_usd: number | null;
  filename: string;
  pages: number | null;
  batch_id: string | null;
  batch_name: string | null;
}

export interface BatchListItem {
  id: string;
  name: string;
  template_id: string;
  template_name: string;
  created_at: number;
  total: number;
  done: number;
  failed: number;
  active: number;
  approved: number;
  pass: number;
  fail: number;
  review: number;
  progress: number;
}

export interface BatchCell {
  value: string | null;
  status: QCStatus;
  reviewed: boolean;
  source: string;
}

export interface BatchRow {
  run_id: string;
  document_id: string;
  filename: string;
  pages: number | null;
  status: RunStatus;
  stage: string;
  progress: number;
  error: string | null;
  approved_at: number | null;
  summary: Summary | null;
  open_issues: number;
  cells: Record<string, BatchCell>;
}

export interface Batch extends BatchListItem {
  fields: Field[];
  rows: BatchRow[];
}

export type ExportFormat = "xlsx" | "csv" | "json";
export type ExportLayout = "summary" | "summary_qc" | "detail";

export interface ExportOptions {
  format: ExportFormat;
  layout?: ExportLayout;
  headers?: "labels" | "keys";
  approvedOnly?: boolean;
}

export interface FieldResult {
  field: string;
  label: string;
  type: FieldType;
  status: QCStatus;
  verdict: string | null;
  extracted_value: string | null;
  extracted_page: number | null;
  extracted_quote: string | null;
  confidence: number | null;
  correct_value: string | null;
  final_value: string | null;
  evidence_quote: string | null;
  evidence_page: number | null;
  pages_checked: number[];
  located_by: string;
  citation_ok?: boolean | null;
  reasoning: string | null;
  notes: string[];
  qc_call_count?: number;
  extracted_quote_pages?: number[];
  evidence_pages?: number[];
}

/** One request to the QC model, as sent, plus its reply. */
export interface QcCall {
  model: string;
  messages: { role: string; content: unknown }[];
  response: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Report {
  num_pages: number;
  ocr_pages: number[];
  models: Record<string, string>;
  summary: Summary;
  llm_calls: number;
  pages_sent_to_qc: number;
  review_pages: number[];
  seconds: number;
  results: FieldResult[];
  page_texts: Record<string, string>;
  usage?: Usage;
  timings?: { phases: { phase: string; seconds: number }[]; index_reused: boolean };
}

/** One model call of a run, in the order they started. */
export interface ModelCall {
  n: number;
  step: string;
  model: string;
  detail: string | null;
  input: number;
  output: number;
  seconds: number;
  at: number;
  cost_usd?: number | null;
  local?: boolean;
}

/** Tokens used by every OpenAI call in a run, in total and per model. */
export interface Usage {
  input: number;
  output: number;
  total: number;
  models: Record<string, { calls: number; input: number; output: number; total: number; seconds?: number; cost_usd?: number | null; local?: boolean }>;
  calls?: ModelCall[];
  cost_usd?: number;
  priced_all?: boolean;
  prices_checked?: string;
}

export interface ReviewDecision {
  value: string | null;
  source: "extracted" | "verified" | "manual";
  at: number;
}

export interface Run extends Omit<RunListItem, "summary" | "seconds" | "tokens" | "cost_usd" | "batch_name"> {
  template: { fields: Field[]; rules: SumRule[] };
  report: Report | null;
  content_type: string;
  resolved: { field: string; value: string | null; reviewed: boolean; source: string }[];
}

export interface PriceRow {
  model: string;
  input: number;
  output: number;
  kind?: "chat" | "embedding" | "local";
}

export interface Settings {
  openai_key_set: boolean;
  openai_key_hint: string;
  prices: PriceRow[];
  default_prices: PriceRow[];
  prices_source: string;
  models: { extract: string; qc: string; ocr: string };
  defaults: { extract: string; qc: string; ocr: string };
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("Can't reach the ParseProof server. Make sure it is running.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail[0]?.msg : null;
    throw new ApiError(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  runs: () => request<RunListItem[]>("/api/runs"),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  qcCalls: (id: string, field: string) => request<QcCall[]>(`/api/runs/${id}/qc-calls/${encodeURIComponent(field)}`),
  createRun: (document_id: string, template_id: string) =>
    request<RunListItem>("/api/runs", json("POST", { document_id, template_id })),
  rerun: (id: string) => request<RunListItem>(`/api/runs/${id}/rerun`, { method: "POST" }),
  deleteRun: (id: string) => request(`/api/runs/${id}`, { method: "DELETE" }),
  review: (id: string, body: { field: string; value?: string | null; source?: string; reset?: boolean }) =>
    request<Run>(`/api/runs/${id}/review`, json("PUT", body)),
  approve: (id: string) => request<Run>(`/api/runs/${id}/approve`, { method: "POST" }),
  reopen: (id: string) => request<Run>(`/api/runs/${id}/reopen`, { method: "POST" }),
  exportUrl: (target: { batch?: string; runs?: string[] }, o: ExportOptions) => {
    const q = new URLSearchParams({ format: o.format, layout: o.layout ?? "summary", headers: o.headers ?? "labels" });
    if (target.batch) q.set("batch", target.batch);
    if (target.runs) q.set("runs", target.runs.join(","));
    if (o.approvedOnly) q.set("approved_only", "true");
    return `/api/export?${q}`;
  },

  batches: () => request<BatchListItem[]>("/api/batches"),
  batch: (id: string) => request<Batch>(`/api/batches/${id}`),
  createBatch: (template_id: string, document_ids: string[], name: string) =>
    request<Batch>("/api/batches", json("POST", { template_id, document_ids, name })),
  deleteBatch: (id: string) => request(`/api/batches/${id}`, { method: "DELETE" }),
  approveClean: (id: string) => request<{ approved: number; batch: Batch }>(`/api/batches/${id}/approve-clean`, { method: "POST" }),
  retryFailed: (id: string) => request<{ retried: number; batch: Batch }>(`/api/batches/${id}/retry-failed`, { method: "POST" }),

  documents: () => request<DocumentRow[]>("/api/documents"),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<DocumentRow>("/api/documents", { method: "POST", body: fd });
  },
  documentUrl: (id: string) => `/api/documents/${id}/file`,

  templates: () => request<Template[]>("/api/templates"),
  template: (id: string) => request<Template>(`/api/templates/${id}`),
  createTemplate: (t: Partial<Template>) => request<Template>("/api/templates", json("POST", t)),
  updateTemplate: (id: string, t: Partial<Template>) => request<Template>(`/api/templates/${id}`, json("PUT", t)),
  deleteTemplate: (id: string) => request(`/api/templates/${id}`, { method: "DELETE" }),
  draftTemplate: (prompt: string, document_id?: string | null) =>
    request<TemplateDraft>("/api/templates/draft", json("POST", { prompt, document_id: document_id || null })),

  settings: () => request<Settings>("/api/settings"),
  saveSettings: (s: Record<string, unknown>) => request<Settings>("/api/settings", json("PUT", s)),
  testSettings: () => request<{ ok: boolean; error?: string; model_available?: boolean | null }>("/api/settings/test", { method: "POST" }),
};

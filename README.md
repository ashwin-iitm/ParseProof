# AdoVerse

Document extraction you can sign off. AdoVerse:
1. **Extracts** fields from a document using OpenAI's native document input. The model reads text and
   page images, so scans and tables work.
2. **Verifies** every value with a second, independent model. That model only reads the page the value
   came from, found through the hybrid RAG index: FAISS vectors + BM25 keywords, fused with RRF and
   reranked by a cross-encoder.
3. **Shows** the result: what was verified, what was corrected, what needs a human. Each comes with the
   source page and the evidence highlighted. You approve the run and export the data.

The only thing it needs is an OpenAI API key.

## How to run

### What you need first

| Tool | Version | Check it with | Get it |
|---|---|---|---|
| Python | 3.11 or newer (tested on 3.12) | `python --version` | https://www.python.org/downloads/ (on Windows, tick **Add python.exe to PATH**) |
| Node.js | 18 or newer (tested on 22) | `node --version` | https://nodejs.org/ (the LTS version) |
| Git | any | `git --version` | https://git-scm.com/downloads |
| An OpenAI API key | | | https://platform.openai.com/api-keys |

You also need about 3 GB of free disk space for the Python packages (PyTorch is the big one) and an
internet connection the first time.

### 1. Download the code

```bash
git clone https://github.com/ashwin-iitm/ParseProof.git
cd ParseProof
```

### 2. Start it

**Windows:** double-click **`start.bat`** in the `ParseProof` folder, or run it from a terminal:

```bash
start.bat
```

**macOS or Linux:**

```bash
chmod +x start.sh
./start.sh
```

The first start sets everything up by itself and takes 5 to 10 minutes:
1. Creates a Python environment in `venv/` and installs `requirements.txt`.
2. Installs the web packages and builds the screens into `web/dist/`.
3. Copies `.env.example` to `.env`.
4. Downloads the small reranker model (about 90 MB) from Hugging Face and loads it.

Later starts skip all of this and take about 30 seconds. The app is ready when the terminal shows
`Uvicorn running on http://127.0.0.1:8010`. Then open **http://127.0.0.1:8010** in your browser. On
Windows it opens by itself. Keep the terminal window open while you use the app; closing it stops the
app.

### 3. Add your OpenAI key

Open **Settings** in the app, paste your key and save. Or put it in the `.env` file before starting:

```
OPENAI_API_KEY=sk-...
```

The key stays on your machine, in `.env`. The only outside service AdoVerse calls is OpenAI.

### 4. Try it

1. Click **New run**.
2. Drop a PDF, for example `samples/sample_invoice.pdf`.
3. Pick the **Invoice** template and click **Extract and verify**.
4. In about 20 seconds you see every field with its status, and the PDF page with the proof highlighted.

`samples/sample_invoice_scanned.pdf` is a scan with one planted mistake (the supplier GSTIN). QC should
flag it as a **Mismatch**.

### Run it by hand (instead of the start scripts)

```bash
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
cd web
npm install
npm run build
cd ..
venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8010
```

On macOS or Linux use `python3` and `venv/bin/python` instead of `venv\Scripts\python.exe`.

**Changing the screens:** run the server as above, then in a second terminal run `npm run dev` in
`web/`. Open http://localhost:5180. It reloads as you edit and sends `/api` calls to the server on port
8010. Run `npm run build` again when you are done, because the server on port 8010 serves `web/dist/`.

### If something goes wrong

| What you see | What to do |
|---|---|
| `python` is not recognized | Install Python and tick **Add python.exe to PATH**, then open a new terminal. |
| `Node.js 18 or newer is needed` | Install Node.js LTS, then open a new terminal. |
| `address already in use` / port 8010 busy | AdoVerse is already running in another window. Close it, or open http://127.0.0.1:8010. |
| The page is blank or looks old | Refresh the browser once. If you changed `web/src`, run `npm run build` in `web/`. |
| "Add your OpenAI API key" banner | Add the key under **Settings**. |
| "This PDF is password-protected" | Bank statements are often locked. Open the PDF, print it to a new PDF (Print → Save as PDF) and upload that copy. |
| The first start stops while installing packages | Check your internet connection and run the start script again. It picks up where it stopped. |
| You want a clean start | Stop the app and delete the `data/` folder. Your documents, runs and templates are stored there. |

## Templates

A template is the list of fields to extract. You can start from a template in three ways:
- **A starter:** Invoice, Loss run summary, Insurance policy, General document (works on any business
  document), Service agreement or Purchase order.
- **Create with AI:** describe what you need in plain words, e.g. "workers comp loss run: insured,
  carrier, valuation date, paid, reserves, incurred". You can also attach a sample document. The AI
  drafts the fields, the descriptions and any sum checks, and the draft opens in the editor. Change
  anything there, then save. On **New run**, the document you picked can be used as the sample. After
  you save, you go back to the run with the new template selected.
- **Blank template:** start from an empty editor and add every field yourself.

Every template stays editable. You can also open **Edit fields** on the selected template during a
new run.

## How a run works

```
upload ─> ingest ──> extract (OpenAI, PDF page ranges in parallel) ──> verify each field (parallel)
          │ text layer per page                                          │ locate: is the quote on the cited page? (code, no LLM)
          │ OCR for scanned pages                                        │ search: hybrid RAG over pages, if the citation is missing or wrong
          └ page index (saved, reused)                                   │ verify: second model reads only those 1–3 pages
                                                                         └ check the checker: evidence must exist on the page
                                                    ──> rule checks (required, number/date, sums) ──> review
```

Before QC, the extractor checks its own work. If a field's quote isn't found anywhere in the
document text, the extractor re-reads that page's text once. The new answer is used only if its
quote is on the page, and the field's notes say so. After QC, a "correction" that has the same words
as the extracted value (an address whose city and PIN are printed twice) counts as verified.

Every run counts the tokens of each OpenAI call: extraction, OCR, embeddings, the self-check and QC. The run header shows the total (click it to see the split per model), the Runs list shows it per run, and the Excel export has token columns on the `Runs` sheet. In the review panel, each field shows who produced each value: the extractor (AI), the QC checker (AI), the Python checks with every page the quote is on, and the final value.

Each field ends up in one of three states:
- **Verified**
- **Mismatch**: the verifier found a different value on the page, with evidence.
- **Needs review**

## Batches and exports

Select several files (or tick documents already uploaded) on **New run**. They run as a **batch**
with one template, 3 documents at a time. The batch page shows one table: a row per document, a column
per field, with mismatches in red, reviews in amber and reviewer fixes in blue. **Approve N with no
issues** approves every document whose fields all verified; **Retry failed** re-runs failed documents.

**Export** (on a batch, on a single run, or for runs ticked on the Runs page):

| Option | What you get |
|---|---|
| Excel workbook | `Data` (row per document, numbers stored as numbers, hover a red cell for the evidence), `QC status`, `QC detail` (row per field: extracted value, QC value, pages, quotes, notes), `Runs` (time, model calls, errors), `Key` |
| CSV · data table | One row per document, one column per field |
| CSV · data table with QC | The same, plus a QC status column after every field |
| CSV · QC detail | One row per field per document |
| JSON | All documents with values and evidence |

Two switches apply to every option: **Approved documents only**, and **field keys** (`total_amount`)
instead of labels (`Total amount`) as column headers. The same exports are available from
`GET /api/export?batch=…|runs=a,b&format=xlsx|csv|json&layout=summary|summary_qc|detail`.

## Files

| Path | What |
|---|---|
| `server.py` | API + serves the web app |
| `agents.py` | LangGraph pipeline: extraction agent, per-field QC agent, rules |
| `openai_extract.py` | OpenAI document extraction and OCR |
| `doc_index.py` | Page-level hybrid RAG index used by QC |
| `db.py` | SQLite (`data/adoverse.db`): documents, templates, runs, batches, settings |
| `exports.py` | Excel, CSV and JSON exports (data table and QC detail) |
| `templates_seed.py` | Starter templates: Invoice, Loss run summary, Insurance policy, General document, Service agreement, Purchase order |
| `vector_store.py` | Embeddings, FAISS and the cross-encoder reranker |
| `text_processing.py` | Reads Word, Excel, CSV and text files |
| `config.py` | Settings from `.env`, the OpenAI client and the token meter |
| `web/` | React app (`npm run build` → `web/dist`) |
| `data/` | Created on first start: stored documents, saved indexes, database. Not in git. |
| `samples/` | Test documents, including a scanned invoice |
| `docs/` | Explainer pages for the team |
| `start.bat`, `start.sh` | Set up on first run, then start the app |
| `run_agents.py` | Command-line version: `venv\Scripts\python.exe run_agents.py <file> --schema samples/schema.json` |

## Settings

Change models in the app under **Settings**, or in `.env`. Other limits are in `.env` only.

| Setting | Default | What it does |
|---|---|---|
| `EXTRACT_MODEL` | `gpt-4.1` | Extraction model. It read page numbers correctly in testing, where `gpt-4o` did not. |
| `QC_MODEL` | `gpt-4o` | Verification model. Deliberately different from the extraction model. |
| `OCR_MODEL` | `gpt-4.1-mini` | Reads scanned pages. |
| `EXTRACT_PAGES_PER_CALL` | `40` | PDF pages sent per extraction call. Larger documents are split and run in parallel. |
| `AGENT_MAX_CONCURRENCY` | `8` | How many model calls run in parallel within one document. |
| `RUN_CONCURRENCY` | `3` | How many documents of a batch are processed at the same time. Raise it if your OpenAI rate limits allow. |

## Limits

- **Local and single-user:** no login. Run it on your own machine or a trusted network.
- **Single values only:** fields are single values. Repeating line-item tables aren't modelled yet.
- **No on-page highlight for scans:** scanned pages have no text layer, so the evidence shows as a
  quote in the field panel instead.

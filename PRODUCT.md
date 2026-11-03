# Product

<!-- impeccable:product-schema 1 -->

> Inferred from the owner's brief ("working product", "only thing I will provide is the OpenAI API",
> "don't ask anything more"). No interview was run; items marked *(inferred)* are assumptions.

## Platform

web

## Stack

Delegated: FastAPI (Python) backend serving a React + Vite + TypeScript + Tailwind single-page app,
SQLite for storage. Runs locally on one machine; the only external service is the OpenAI API.

## Users

*(inferred)* Operations, finance and legal analysts who extract fields from business documents
(invoices, agreements, purchase orders) and must be able to stand behind every value. They work at a
desk on a laptop or external monitor, processing documents one after another.

## Product Purpose

AdoVerse extracts structured fields from documents and proves each value. OpenAI reads the whole
document; a QC agent then re-checks every field against only the page it came from, using a hybrid
RAG index (vector + keyword + reranker). The reviewer sees which fields passed, which were corrected
and which need a human, with the source page and evidence highlighted, so they never re-read the
whole document. Success: a reviewer approves a document by looking at a handful of pages, not all of them.

## Positioning

Every value comes with evidence that was verified in code (the quote must actually exist on the
cited page), by a second, independent model. Extraction tools give values; AdoVerse gives values a
reviewer can sign off.

## Operating Context

- Upload a document (PDF, Word, Excel, CSV, text), choose a template, run.
- Review: fields grouped by QC status; accept the verified correction, keep the extracted value,
  or type a value; approve; export JSON or CSV.
- Templates define fields (key, label, description, type, required) and sum rules.
- Settings hold the OpenAI API key and model choices.

## Capabilities and Constraints

- Single-user, local tool: no accounts or authentication *(inferred)*.
- Scanned PDFs are OCR'd with OpenAI so QC can search them.
- Fields are single values; repeating tables (line items) are not supported yet.

## Evidence on Hand

Sample documents in `samples/`. No customers, testimonials or benchmarks exist; do not invent any.

## Product Principles

1. Evidence over confidence: show the source, not a score.
2. Only surface what needs a human; passed fields stay quiet.
3. The document is the authority: the viewer is first-class, not a preview.
4. Nothing leaves the machine except calls to OpenAI.

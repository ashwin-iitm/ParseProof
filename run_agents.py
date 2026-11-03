#!/usr/bin/env python3
"""
run_agents.py — run the extraction + QC agents from the command line.

Usage:
  python run_agents.py doc.pdf --schema schema.json                          # extract + QC
  python run_agents.py doc.pdf --schema schema.json --extraction out.json    # QC an existing extraction
  python run_agents.py doc.pdf --schema schema.json --fields total,gst       # audit only some fields
  python run_agents.py doc.pdf --schema schema.json --no-qc                  # extraction only
"""

import argparse
import json
from pathlib import Path

from agents import run_pipeline
from report_html import render_report


def main():
    ap = argparse.ArgumentParser(description="Extraction + QC agents")
    ap.add_argument("file")
    ap.add_argument("--schema", required=True)
    ap.add_argument("--extraction", help="JSON output of an existing extractor (skips the extraction agent)")
    ap.add_argument("--fields", help="comma-separated field names to audit")
    ap.add_argument("--no-qc", action="store_true", help="run extraction only")
    ap.add_argument("--out", default="reports/report", help="output path without extension")
    args = ap.parse_args()

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    extraction = json.loads(Path(args.extraction).read_text(encoding="utf-8")) if args.extraction else None
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None

    report = run_pipeline(args.file, schema, extraction, fields, run_qc=not args.no_qc)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    render_report(report, out.with_suffix(".html"))

    s = report["summary"]
    print(f"\n{report['file']}: {report['num_pages']} pages, {report['llm_calls']} LLM calls, "
          f"{report['pages_sent_to_qc']} pages sent to QC, {report['seconds']}s")
    print(f"PASS {s['PASS']}  FAIL {s['FAIL']}  REVIEW {s['REVIEW']}  NOT_CHECKED {s['NOT_CHECKED']}\n")
    for r in report["results"]:
        line = f"  [{r['status']:<11}] {r['field']:<22} {str(r.get('extracted_value'))!s:<28}"
        if r.get("correct_value"):
            line += f" -> {r['correct_value']}"
        if r.get("pages_checked"):
            line += f"   (pages {r['pages_checked']}, via {r.get('located_by')})"
        print(line)
        for n in r.get("notes") or []:
            print(f"      - {n}")
    if report["review_pages"]:
        print(f"\nPages a human should open: {report['review_pages']}")
    print(f"\nReport: {out.with_suffix('.html')}")


if __name__ == "__main__":
    main()

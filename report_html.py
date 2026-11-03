"""
report_html.py — renders a QC report as a standalone HTML page for human reviewers.

Only FAIL / REVIEW fields matter to a reviewer, so their source pages are embedded
with the evidence highlighted: the reviewer reads one page, not the whole document.
"""

import html
import re
from pathlib import Path

STATUS_ORDER = {"FAIL": 0, "REVIEW": 1, "NOT_CHECKED": 2, "PASS": 3}


def _esc(value) -> str:
    return "—" if value is None or value == "" else html.escape(str(value))


def _highlight(page_text: str, quotes) -> str:
    out = html.escape(page_text)
    for q in quotes:
        if not q:
            continue
        words = [re.escape(html.escape(w)) for w in str(q).split()]
        if not words:
            continue
        out = re.sub(r"\s+".join(words), lambda m: f"<mark>{m.group(0)}</mark>", out, flags=re.IGNORECASE)
    return out


def render_report(report: dict, out_path: Path) -> Path:
    s = report["summary"]
    results = sorted(report["results"], key=lambda r: STATUS_ORDER.get(r["status"], 9))

    rows = []
    for r in results:
        pages = ", ".join(str(p) for p in r.get("pages_checked") or []) or "—"
        notes = "<br>".join(_esc(n) for n in r.get("notes") or [])
        rows.append(f"""
<tr class="{r['status'].lower()}">
  <td><span class="badge {r['status'].lower()}">{r['status']}</span></td>
  <td class="mono">{_esc(r['field'])}</td>
  <td>{_esc(r.get('extracted_value'))}<div class="sub">cited p.{_esc(r.get('extracted_page'))}</div></td>
  <td>{_esc(r.get('correct_value'))}</td>
  <td>{_esc(r.get('evidence_quote'))}<div class="sub">p.{_esc(r.get('evidence_page'))}</div></td>
  <td>{pages}<div class="sub">{_esc(r.get('located_by'))}</div></td>
  <td class="notes">{_esc(r.get('reasoning'))}{'<br>' + notes if notes else ''}</td>
</tr>""")

    page_sections = []
    for p in report.get("review_pages", []):
        text = report["page_texts"].get(p) or report["page_texts"].get(str(p), "")
        fields = [r for r in results
                  if (r["status"] == "FAIL" and p in (r.get("evidence_page"), r.get("extracted_page")))
                  or (r["status"] == "REVIEW" and p in (r.get("pages_checked") or []))]
        quotes = [r.get("evidence_quote") for r in fields] + [r.get("extracted_quote") for r in fields]
        names = ", ".join(r["field"] for r in fields)
        page_sections.append(f"""
<details>
  <summary>Page {p} <span class="sub">— {html.escape(names)}</span></summary>
  <pre>{_highlight(text, quotes)}</pre>
</details>""")

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QC Report</title>
<style>
  :root {{ --bg:#f7f7f5; --card:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#e3e2dc;
          --pass:#1f7a4d; --fail:#b42318; --review:#b26a00; --nc:#6b6b66; --mark:#ffe58a; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#161615; --card:#1f1f1d; --ink:#ecebe6; --muted:#9a9993; --line:#33332f;
            --pass:#4cc38a; --fail:#ff6b5b; --review:#f0a73a; --nc:#9a9993; --mark:#6b5a12; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--ink);
         font:14px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }}
  main {{ max-width:1200px; margin:0 auto; }}
  h1 {{ font-size:20px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:28px 0 10px; }}
  .sub {{ color:var(--muted); font-size:12px; }}
  .mono {{ font-family: ui-monospace, Consolas, monospace; font-size:13px; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:10px; margin:16px 0; }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 14px; min-width:110px; }}
  .stat b {{ display:block; font-size:22px; }}
  .wrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:8px; }}
  table {{ border-collapse:collapse; width:100%; min-width:900px; }}
  th, td {{ text-align:left; vertical-align:top; padding:10px 12px; border-bottom:1px solid var(--line); }}
  th {{ font-size:12px; color:var(--muted); font-weight:600; }}
  .notes {{ max-width:320px; font-size:13px; }}
  .badge {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:99px; color:#fff; }}
  .badge.pass {{ background:var(--pass); }} .badge.fail {{ background:var(--fail); }}
  .badge.review {{ background:var(--review); }} .badge.not_checked {{ background:var(--nc); }}
  details {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin-bottom:8px; }}
  summary {{ cursor:pointer; padding:10px 14px; font-weight:600; }}
  pre {{ white-space:pre-wrap; margin:0; padding:0 14px 14px; font:13px/1.55 ui-monospace, Consolas, monospace; }}
  mark {{ background:var(--mark); color:inherit; border-radius:2px; }}
</style></head>
<body><main>
  <h1>QC Report — {html.escape(report['file'])}</h1>
  <div class="sub">{report['num_pages']} pages · extraction: {_esc(report.get('extraction_source'))}
    · models: {_esc(report['models']['extract'])} / {_esc(report['models']['qc'])} · {report['seconds']}s</div>
  <div class="stats">
    <div class="stat"><b style="color:var(--pass)">{s['PASS']}</b>Pass</div>
    <div class="stat"><b style="color:var(--fail)">{s['FAIL']}</b>Fail</div>
    <div class="stat"><b style="color:var(--review)">{s['REVIEW']}</b>Needs review</div>
    <div class="stat"><b>{report['pages_sent_to_qc']}</b>Pages sent to QC</div>
    <div class="stat"><b>{len(report.get('review_pages', []))}</b>Pages for a human</div>
    <div class="stat"><b>{report['llm_calls']}</b>LLM calls</div>
  </div>
  <div class="wrap"><table>
    <thead><tr><th>Status</th><th>Field</th><th>Extracted</th><th>Correct value</th>
      <th>Evidence</th><th>Pages checked</th><th>Reasoning / notes</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
  <h2>Pages to review</h2>
  {''.join(page_sections) or '<div class="sub">Nothing needs a human.</div>'}
</main></body></html>"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path

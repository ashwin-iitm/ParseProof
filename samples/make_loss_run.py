#!/usr/bin/env python3
"""
make_loss_run.py — builds samples/sample_loss_run.pdf, a 3-page workers compensation loss run
(header, claim listing, totals) for testing loss-run templates.
"""

from pathlib import Path
import fitz  # PyMuPDF

HERE = Path(__file__).parent

PAGE_1 = """GRANITE MUTUAL INSURANCE COMPANY
Loss Run Report - Workers Compensation

Named Insured:     Coastal Freight & Warehousing LLC
Policy Number:     WC-7714-202509
Line of Business:  Workers Compensation and Employers Liability
Policy Period:     09/01/2025 to 09/01/2026
Valued As Of:      10/15/2026
Agency:            Harbor Point Insurance Brokers

This report lists all claims reported under the policy above as of the valuation date.
Amounts are in USD. Paid includes indemnity, medical and expense payments.
Reserves are outstanding amounts as of the valuation date."""

CLAIMS = [
    ("WC25-0193", "10/02/2025", "Strain - lifting pallet", "Closed", 8420.00, 0.00),
    ("WC25-0241", "11/19/2025", "Laceration - box cutter", "Closed", 2135.50, 0.00),
    ("WC25-0310", "01/07/2026", "Fall from loading dock", "Open", 41250.00, 63800.00),
    ("WC26-0017", "02/23/2026", "Forklift collision - foot", "Open", 18900.00, 22400.00),
    ("WC26-0088", "04/11/2026", "Repetitive motion - wrist", "Closed", 6740.25, 0.00),
    ("WC26-0132", "06/30/2026", "Heat exhaustion", "Closed", 1980.00, 0.00),
    ("WC26-0175", "08/14/2026", "Back injury - unloading", "Open", 9310.00, 15500.00),
]


def page_2() -> str:
    lines = ["CLAIM DETAIL  -  Policy WC-7714-202509", "",
             f"{'Claim No':<11}{'Loss Date':<12}{'Description':<30}{'Status':<8}{'Paid':>12}{'Reserve':>12}{'Incurred':>12}"]
    for no, date, desc, status, paid, res in CLAIMS:
        lines.append(f"{no:<11}{date:<12}{desc:<30}{status:<8}{paid:>12,.2f}{res:>12,.2f}{paid + res:>12,.2f}")
    return "\n".join(lines)


def page_3() -> str:
    paid = sum(c[4] for c in CLAIMS)
    res = sum(c[5] for c in CLAIMS)
    open_ = sum(1 for c in CLAIMS if c[3] == "Open")
    largest = max(CLAIMS, key=lambda c: c[4] + c[5])
    return f"""POLICY TOTALS  -  WC-7714-202509   (valued as of 10/15/2026)

Total Claims Reported:   {len(CLAIMS)}
Open Claims:             {open_}
Closed Claims:           {len(CLAIMS) - open_}

Total Paid:              {paid:,.2f}
Total Outstanding Reserves: {res:,.2f}
Total Incurred:          {paid + res:,.2f}

Largest Claim:           {largest[0]}  ({largest[2]})  Incurred {largest[4] + largest[5]:,.2f}

Report generated 10/15/2026 by Granite Mutual Claims Services. Loss runs are provided for
underwriting purposes and do not alter coverage."""


def main():
    doc = fitz.open()
    for body, size in ((PAGE_1, 10.5), (page_2(), 7.5), (page_3(), 10.5)):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 50, 575, 800), body, fontsize=size, fontname="cour")
    out = HERE / "sample_loss_run.pdf"
    doc.save(out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

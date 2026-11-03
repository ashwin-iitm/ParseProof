#!/usr/bin/env python3
"""
make_sample.py — builds samples/sample_msa.pdf, a 30-page contract for testing the agents.

Facts live on specific pages, and filler pages carry look-alike numbers
("30 days", other amounts) so retrieval has to work for it.
"""

from pathlib import Path
import fitz  # PyMuPDF

FILLER = (
    "The Parties shall perform their obligations in good faith and in accordance with applicable law. "
    "Each Party shall maintain adequate records relating to the Services and make them available for "
    "inspection upon reasonable notice. Nothing in this clause limits any other right or remedy. "
)

FACT_PAGES = {
    1: """MASTER SERVICES AGREEMENT
Agreement No.: MSA-2026-0417

This Master Services Agreement is made on 15 March 2026 (the "Effective Date")
BETWEEN Northwind Logistics Private Limited, a company incorporated in India ("Client")
AND Bluepeak Software Solutions LLP ("Service Provider").""",
    4: """4. TERM
4.1 This Agreement commences on the Effective Date and continues for an initial term of
thirty-six (36) months, unless terminated earlier in accordance with Clause 19.
4.2 The Parties may renew this Agreement by mutual written agreement.""",
    9: """9. FEES AND PAYMENT
9.1 The Client shall pay the Fees set out in Schedule B.
9.2 All undisputed invoices are payable within forty-five (45) days of receipt (Net 45).
9.3 Invoices shall be raised monthly in arrears.""",
    10: """10. LATE PAYMENT
10.1 If any undisputed amount remains unpaid after 30 days beyond its due date, interest shall
accrue at 1.5% per month until paid.
10.2 The Service Provider may suspend Services on 15 days' written notice of non-payment.""",
    12: """12. INSURANCE
12.1 The Service Provider shall maintain professional indemnity insurance of not less than
INR 10,000,000 for the duration of this Agreement.""",
    14: """14. LIMITATION OF LIABILITY
14.1 Each Party's aggregate liability under this Agreement shall not exceed INR 25,000,000
(Rupees Twenty-Five Million only).
14.2 Neither Party is liable for indirect or consequential losses.""",
    18: """18. GOVERNING LAW AND JURISDICTION
18.1 This Agreement is governed by the laws of India.
18.2 The courts at Bengaluru, Karnataka shall have exclusive jurisdiction.""",
    19: """19. TERMINATION
19.1 Either Party may terminate this Agreement for convenience by giving not less than
ninety (90) days' prior written notice to the other Party.
19.2 Either Party may terminate immediately for material breach not cured within 30 days.""",
    27: """SCHEDULE B — FEES (FIRST INVOICE)
Description: Platform implementation, Phase 1
Subtotal: INR 1,840,000.00
GST @ 18%: INR 331,200.00
Total Amount Payable: INR 2,171,200.00""",
    30: """IN WITNESS WHEREOF the Parties have executed this Agreement.

For Northwind Logistics Private Limited
Name: Priya Raman
Designation: Director

For Bluepeak Software Solutions LLP
Name: Arjun Mehta
Designation: Designated Partner""",
}


def main():
    out = Path(__file__).parent / "sample_msa.pdf"
    doc = fitz.open()
    for n in range(1, 31):
        page = doc.new_page()
        body = FACT_PAGES.get(n, f"{n}. GENERAL PROVISIONS (PART {n})\n" + FILLER * 3)
        page.insert_textbox(fitz.Rect(60, 60, 540, 780), body, fontsize=11)
        page.insert_text((290, 810), f"Page {n} of 30", fontsize=8)
    doc.save(out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

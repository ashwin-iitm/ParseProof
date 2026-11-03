#!/usr/bin/env python3
"""
make_invoice.py — builds two test invoices in samples/:
  sample_invoice.pdf          2-page digital invoice (totals on page 2)
  sample_invoice_scanned.pdf  the same invoice as page images only (no text layer), to test OCR
"""

from pathlib import Path
import fitz  # PyMuPDF

HERE = Path(__file__).parent

PAGE_1 = """TAX INVOICE

Meridian Components Pvt. Ltd.
Plot 14, Electronic City Phase II, Bengaluru 560100
GSTIN: 29AAKCM4471Q1Z6

Invoice No: INV-24-00918
Invoice Date: 04 September 2026
Due Date: 04 October 2026

Bill To:
Halcyon Retail Systems Ltd.
22 Marine Drive, Mumbai 400002
Customer PO: PO-HRS-55120

Currency: INR

#   Description                              Qty    Unit price      Amount
1   Edge controller board EC-200              40      9,850.00    394,000.00
2   Sensor harness, 2 m                      120        640.00     76,800.00
3   Enclosure, IP65 aluminium                 40      2,310.00     92,400.00
4   Firmware licence, per device              40      1,150.00     46,000.00

(continued on next page)"""

PAGE_2 = """INVOICE INV-24-00918 (continued)

#   Description                              Qty    Unit price      Amount
5   On-site commissioning, per day             6     18,500.00    111,000.00

Subtotal:                                                          720,200.00
IGST @ 18%:                                                        129,636.00
Total Amount Due (INR):                                            849,836.00

Amount in words: Rupees Eight Lakh Forty-Nine Thousand Eight Hundred Thirty-Six only.

Payment terms: Net 30 from invoice date. Late payments attract interest at 1% per month.
Bank: State Bank of India, Koramangala branch, A/c 3920 1188 4410, IFSC SBIN0004321

For Meridian Components Pvt. Ltd.
Authorised Signatory"""


def build(out: Path) -> fitz.Document:
    doc = fitz.open()
    for body in (PAGE_1, PAGE_2):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 560, 800), body, fontsize=10, fontname="cour")
    doc.save(out)
    return doc


def main():
    digital = build(HERE / "sample_invoice.pdf")
    scanned = fitz.open()
    for page in digital:
        pix = page.get_pixmap(dpi=150)
        img_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
        img_page.insert_image(img_page.rect, stream=pix.tobytes("png"))
    scanned.save(HERE / "sample_invoice_scanned.pdf")
    print("Wrote sample_invoice.pdf and sample_invoice_scanned.pdf")


if __name__ == "__main__":
    main()

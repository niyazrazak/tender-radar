"""QAFCO (Qatar Fertiliser Company) tenders. Public WordPress page plus one PDF per RFQ.

The suppliers page lists each RFQ as a box with its number, title and a link to
an "Invitation to Tender" PDF. Only the PDF has the fee, bond and dates. Old RFQs
stay on the page for months, so only PDFs uploaded in the last `max_age_days`
(the upload month is in the PDF's URL) are opened. QAFCO is not on Monaqasat.
Bids go through its SAP Ariba portal; the list and PDFs are public.
"""

import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

LIST_URL = "https://www.qafco.qa/en/suppliers/"
RFQ = re.compile(r"RFQ\s*(\d+)\s*(.*)", re.S)
UPLOAD_MONTH = re.compile(r"/uploads/(\d{4})/(\d{2})/")
DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")  # "13.12.2026" or "31/08/2026"
FEE = re.compile(r"(\d[\d,]*)\s*/-")  # "500/- (Non-refundable)"
AMOUNT = re.compile(r"\d[\d,]*")


class QafcoSource:
    name = "qafco"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_age_days = settings.get("max_age_days", 120)

    def collect(self, known_keys: dict) -> list[Lead]:
        cutoff = date.today() - timedelta(days=self.max_age_days)
        leads = [lead for lead in self._list() if _uploaded(lead.url) >= cutoff.replace(day=1)]
        for lead in leads:
            self._add_pdf(lead)
        print(f"  qafco/open: {len(leads)} tenders")
        return leads

    def _list(self) -> list[Lead]:
        soup = BeautifulSoup(self.client.get_text(LIST_URL), "html.parser")
        leads = {}
        for box in soup.select(".elementor-widget-icon-box"):
            link = box.select_one("a[href$='.pdf']")
            match = RFQ.match(_clean(box.get_text(" ")))
            if link and match and match.group(1) not in leads:  # the page repeats some RFQs
                leads[match.group(1)] = self._lead(match.group(1), match.group(2), link["href"])
        return list(leads.values())

    def _lead(self, number: str, title: str, pdf_url: str) -> Lead:
        return Lead(
            source=self.name,
            source_id=number,
            country="Qatar",
            title=_clean(title) or f"RFQ {number}",
            url=pdf_url,
            ref_no=f"RFQ {number}",
            buyer="QAFCO (Qatar Fertiliser Company)",
            tender_type="RFQ",
            currency="QAR",
        )

    def _add_pdf(self, lead: Lead):
        try:
            text = self.client.get_pdf_text(lead.url)
        except Exception as error:  # one bad PDF must not lose the list
            print(f"  ! qafco PDF failed {lead.url}: {error}")
            return
        table = text.split("GENERAL INSTRUCTIONS")[0]  # the English table; the rest is terms and Arabic
        dates = sorted(date(int(y), int(m), int(d)) for d, m, y in DATE.findall(table))
        if dates:
            # The fee-receipt dates come first; the latest date is the closing date.
            lead.published, lead.closing = dates[0].isoformat(), dates[-1].isoformat()
        fee = FEE.search(table)
        if fee:
            lead.doc_fee = fee.group(1)
            first_date = DATE.search(table, fee.end())
            lead.bond = _bond(table[fee.end():first_date.start() if first_date else None])


def _uploaded(url: str) -> date:
    match = UPLOAD_MONTH.search(url)
    return date(int(match.group(1)), int(match.group(2)), 1) if match else date.min


def _bond(cell: str) -> str:
    """The bond cell sits between the fee and the dates: "QAR 52,000 (...)", "32,000 (...)" or "Not applicable"."""
    if "not applicable" in cell.lower():
        return "0"
    match = AMOUNT.search(cell)
    return match.group(0) if match else ""


def _clean(text) -> str:
    return " ".join(str(text or "").split())

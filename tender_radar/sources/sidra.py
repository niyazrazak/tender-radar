"""Sidra Medicine (Qatar) RFQs, RFIs and tenders. Public Oracle Fusion list, read as HTML.

sidra.org/procurement-and-contracts links to its Oracle Fusion "Negotiation
Abstracts" page, which anyone can read without login. Oracle ADF answers the
first GET with a "loopback" script; the second GET, with the `_afrLoop` id from
that script and the session cookies, returns the table. Detail pages are
JavaScript actions, not URLs, so a lead links to the list.

The list is newest first and shows about 25 rows. Sidra posts a few a day, so
a check every few hours sees every new one. Most items are medical supplies;
the keyword scorer keeps the IT ones.
"""

import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

LIST_URL = (
    "https://fa-epxn-saasfaprod1.fa.ocs.oraclecloud.com/fscmUI/faces/NegotiationAbstracts"
    "?prcBuId=300000003054324"
)
LOOPBACK_ID = re.compile(r'"_afrLoop",\s*"(\d+)"')
# Cell order in each row: number, title, type, status, posting, open, close, details.
NUMBER, TITLE, TYPE, STATUS, POSTED, OPENS, CLOSES = range(7)
STATUSES = {"Active": "open", "Preview": "future"}  # "Closed" rows are dropped
DATE_FORMAT = "%m/%d/%y %I:%M %p"
QATAR_OFFSET = timedelta(hours=3)  # the page shows times in UTC


class SidraSource:
    name = "sidra"

    def __init__(self, client, settings: dict):
        self.client = client

    def collect(self, known_keys: dict) -> list[Lead]:
        loopback = self.client.get_text(LIST_URL)
        match = LOOPBACK_ID.search(loopback)
        if not match:
            raise RuntimeError("Oracle loopback id not found; the page layout changed")
        html = self.client.get_text(f"{LIST_URL}&_afrLoop={match.group(1)}&_afrWindowMode=0&_afrWindowId=null")
        leads = self._parse(html)
        print(f"  sidra/open: {len(leads)} tenders")
        return leads

    def _parse(self, html: str) -> list[Lead]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("tr[_afrrk]")  # ADF marks data rows with a row key
        return [lead for row in rows if (lead := self._lead(row))]

    def _lead(self, row) -> Lead | None:
        cells = [_clean(cell.get_text(" ")) for cell in row.find_all("td", recursive=False)]
        if len(cells) <= CLOSES or cells[STATUS] not in STATUSES or not cells[NUMBER]:
            return None
        category = cells[TITLE].rpartition(" | ")[0]  # "Laboratory Consumables | Freezer Boxes"
        return Lead(
            source=self.name,
            source_id=cells[NUMBER],  # Oracle negotiation number; amendments add ",1" or "-2"
            country="Qatar",
            title=cells[TITLE],
            url=LIST_URL,
            status=STATUSES[cells[STATUS]],
            ref_no=cells[NUMBER],
            buyer="Sidra Medicine",
            category=category,
            tender_type=cells[TYPE],
            published=_qatar_date(cells[POSTED]),
            closing=_qatar_date(cells[CLOSES]),
            currency="QAR",
            extra={"opens": _qatar_date(cells[OPENS])},
        )


def _qatar_date(text: str) -> str:
    """'12/3/26 8:11 AM' (UTC) -> '2026-12-03' (Qatar date)."""
    try:
        return (datetime.strptime(text, DATE_FORMAT) + QATAR_OFFSET).date().isoformat()
    except ValueError:
        return ""


def _clean(text) -> str:
    return " ".join(str(text or "").split())

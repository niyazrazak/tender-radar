"""Bahrain Tender Board (tenderboard.gov.bh). Public JSON page methods that return HTML rows.

The public page `/Tenders/PublicTenders/` loads its list with two ASP.NET page
methods on `/Templates/TenderBoardWebService.aspx`: one returns the page
count, the other one page of rows as an HTML fragment in `{"d": "..."}`.
No login. `/robots.txt` does not exist (the site serves its HTML 404 page).
The id is the Tender Board tender number, e.g. `581/2026/BTB (MTT/PMA/02/2026)`.
"""

import re
from datetime import datetime
from urllib.parse import unquote_plus

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

BASE = "https://www.tenderboard.gov.bh"
SERVICE = BASE + "/Templates/TenderBoardWebService.aspx/"
LIST_PAGE = BASE + "/Tenders/PublicTenders/"
# The filters as the public page sends them with nothing selected.
LIST_FILTERS = {
    "tenderNumber": "", "ministry": "0", "category": "0", "tendertype": "0",
    "closingDate_filter": "", "publicTenderOnly": "true", "prequalificationOnly": "false",
    "auctionOnly": "true", "sortingType": "0", "listPage": "mainList",
    "smeTendersOnly": "false", "sectionName": "",
}
# List cell data-label -> Lead attribute.
LIST_DATES = {"Publish Date": "published", "Closing Date": "closing"}
# "23, Nov,2026", "08 Dec,2026", "Wednesday,  09 December 2026"
DATE = re.compile(r"(\d{1,2})\W+([A-Za-z]{3})[A-Za-z]*\W+(\d{4})")
AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Detail page <dt> label -> lead.extra key.
DETAIL_EXTRA = {
    "Invitation Method": "invitation_method",
    "Contract Duration": "contract_duration",
    "Opening Date": "opening_date",
    "Bid Validity / Initial Bond Validity Period (Days)": "bid_validity",
}


class BahrainTenderBoardSource:
    name = "bahrain_tender_board"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_pages = settings.get("max_pages", 60)
        self.fetch_details = settings.get("fetch_details", True)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads = self._collect_list()
        if self.fetch_details:
            for lead in leads:
                if lead.key not in known_keys:
                    self._add_details(lead)
        return leads

    def _collect_list(self) -> list[Lead]:
        page_count = min(self._post("GetCurrentPublicTenderPageCount", Page="-1"), self.max_pages)
        leads, seen = [], set()
        for page in range(1, page_count + 1):
            try:
                html = self._post("GetCurrentPublicTenderByPage", Page=str(page))
            except Exception as error:  # past the last page the service returns an HTML error page
                print(f"  ! {self.name} page {page} failed: {error}")
                break
            page_leads = [lead for lead in _parse_list(html, self.name) if lead.key not in seen]
            if not page_leads:
                break
            seen.update(lead.key for lead in page_leads)
            leads += page_leads
        print(f"  {self.name}/open: {len(leads)} tenders")
        return leads

    def _post(self, method: str, **params):
        body = {**LIST_FILTERS, **params}
        return self.client.post_json(SERVICE + method, body, headers={"Referer": LIST_PAGE})["d"]

    def _add_details(self, lead: Lead):
        try:
            soup = BeautifulSoup(self.client.get_text(lead.url), "html.parser")
        except Exception as error:  # one bad page must not stop the run
            print(f"  ! detail failed {lead.url}: {error}")
            return
        info = soup.select_one(".case-detail-info")
        if not info:
            return
        description = info.find("h4", string=re.compile("Tender Description"))
        lead.brief = _text(description.find_next_sibling("p")) if description else ""
        fields = {_text(dt): _text(dt.find_next_sibling("dd")) for dt in info.select("dl dt")}
        lead.bond = _first_amount(fields.get("Initial Bond", ""))
        lead.doc_fee = _first_amount(fields.get("Tender Fees", ""))
        lead.closing = _iso_date(fields.get("Closing Date", "")) or lead.closing
        for label, key in DETAIL_EXTRA.items():
            if fields.get(label):
                lead.extra[key] = _iso_date(fields[label]) if key == "opening_date" else fields[label]


def _parse_list(html: str, source: str) -> list[Lead]:
    soup = BeautifulSoup(html, "html.parser")
    return [lead for row in soup.select("div.rows") if (lead := _parse_row(row, source))]


def _parse_row(row, source: str) -> Lead | None:
    link = row.select_one("a[href*='TenderDetails']")
    if not link or "id=" not in link["href"]:
        return None
    ref = link.find("span")
    ref_no = _text(ref)
    if ref:
        ref.extract()
    cells = {cell.get("data-label"): _text(cell) for cell in row.select("div.column")}
    lead = Lead(
        source=source,
        source_id=unquote_plus(link["href"].split("id=", 1)[1]),
        country="Bahrain",
        title=_text(link),
        url=BASE + link["href"],
        ref_no=ref_no,
        buyer=cells.get("Purchasing Authority", ""),
        tender_type=cells.get("Tender Type", "") or row.get("data-type", ""),
        currency="BHD",
    )
    for label, attr in LIST_DATES.items():
        setattr(lead, attr, _iso_date(cells.get(label, "")))
    purchase_before = _iso_date(cells.get("Purchase Before", ""))
    if purchase_before:
        lead.extra["purchase_before"] = purchase_before
    return lead


def _iso_date(text: str) -> str:
    match = DATE.search(text or "")
    if not match:
        return ""
    try:
        return datetime.strptime(" ".join(match.groups()), "%d %b %Y").date().isoformat()
    except ValueError:
        return ""


def _first_amount(text: str) -> str:
    match = AMOUNT.search(text)
    return match.group(0) if match else ""


def _text(element) -> str:
    return " ".join(element.get_text(" ").split()) if element else ""

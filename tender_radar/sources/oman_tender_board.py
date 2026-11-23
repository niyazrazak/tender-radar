"""Oman Tender Board e-tendering portal (Esnad). Public HTML lists, no robots.txt.

Two lists are read: "new tenders" (open for bids) and "in process" (bids
opened, no award yet). The awarded list needs a form signed by the portal's
JavaScript and is not collected; see the skill's portals.md.

Detail pages need a URL signed by the portal's JavaScript, so this source reads
only the list. The list already has the full title, a description, buyer,
category, closing date, fee and bond.
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

BASE = "https://etendering.tenderboard.gov.om/product"
LIST_URL = BASE + "/publicDash?viewFlag={view}&pageNo={page}"
VIEWS = {"open": "NewTenders", "opened": "InProcessTenders"}
TENDER_ID = re.compile(r"getNit\('(\d+)'\)")
TIP_TEXT = re.compile(r"Tip\('(.*)'\)", re.S)
PAGE_COUNT = re.compile(r"name=['\"]hidMax['\"]\s+value=['\"](\d+)")
DATE_AFTER = "{label}:\\s*(\\d{{2}}-\\d{{2}}-\\d{{4}})"
OPENED_AT = re.compile(r"(\d{2}-\d{2}-\d{4}) (\d{2}:\d{2})")

# Cell order in each row of the tender table.
REF, TITLE, BUYER, CATEGORY, TYPE, DATES, FEE, BOND = range(1, 9)


class OmanTenderBoardSource:
    name = "oman_tender_board"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_pages = settings.get("max_pages", 45)
        self.in_process_pages = settings.get("in_process_pages", 10)

    def collect(self, known_keys: dict) -> list[Lead]:
        seen = set()
        leads = self._collect_list("open", self.max_pages, seen)
        leads += self._collect_list("opened", self.in_process_pages, seen)
        return leads

    def _collect_list(self, status: str, max_pages: int, seen: set) -> list[Lead]:
        """`seen` is shared, so a tender that moves list during the run is kept once."""
        leads, page, last_page = [], 1, max_pages
        while page <= last_page:
            html = self.client.get_text(LIST_URL.format(view=VIEWS[status], page=page))
            # Past the last page the portal serves old tenders, not an error.
            last_page = min(last_page, _page_count(html) or last_page)
            page_leads = [lead for lead in self._parse_rows(html, status) if lead.key not in seen]
            if not page_leads:
                break
            seen.update(lead.key for lead in page_leads)
            leads += page_leads
            page += 1
        print(f"  oman_tender_board/{status}: {len(leads)} tenders")
        return leads

    def _parse_rows(self, html: str, status: str) -> list[Lead]:
        soup = BeautifulSoup(html, "html.parser")
        return [lead for row in soup.select("table.display tr") if (lead := self._parse_row(row, status))]

    def _parse_row(self, row, status: str) -> Lead | None:
        match = TENDER_ID.search(str(row))
        cells = row.find_all("td")
        if not match or len(cells) <= BOND:
            return None
        description = row.select_one("input[id^=tendDesc]")
        dates = _text(cells[DATES])
        lead = Lead(
            source=self.name,
            source_id=match.group(1),
            country="Oman",
            title=_tip_or_text(cells[TITLE]),
            url=LIST_URL.format(view=VIEWS[status], page=1),
            status=status,
            ref_no=_text(cells[REF]),
            buyer=_text(cells[BUYER]),
            category=_tip_or_text(cells[CATEGORY]),
            tender_type=_text(cells[TYPE]),
            closing=_date_after(dates, "Bid Closing Date"),
            doc_fee=_amount(cells[FEE]),
            bond=_amount(cells[BOND]),
            currency="OMR",
            brief=_clean(description["value"]) if description else "",
        )
        if status == "opened":
            lead.extra = {"opened_at": _opened_at(dates)}
        else:
            lead.extra = {"sales_end": _date_after(dates, "Sales EndDate")}
        return lead


def _page_count(html: str) -> int:
    match = PAGE_COUNT.search(html)
    return int(match.group(1)) if match else 0


def _tip_or_text(cell) -> str:
    """Long values are cut to "....." in the cell; the full text is in the tooltip."""
    match = TIP_TEXT.search(cell.get("onmouseover", ""))
    return _clean(match.group(1).replace("\\'", "'")) if match else _text(cell)


def _amount(cell) -> str:
    text = _text(cell)
    return "" if text == "N/A" else text


def _date_after(text: str, label: str) -> str:
    match = re.search(DATE_AFTER.format(label=label), text)
    if not match:
        return ""
    return datetime.strptime(match.group(1), "%d-%m-%Y").date().isoformat()


def _opened_at(text: str) -> str:
    """In-process rows show the actual bid opening time instead of the closing date."""
    match = OPENED_AT.search(text)
    if not match:
        return ""
    opened = datetime.strptime(" ".join(match.groups()), "%d-%m-%Y %H:%M")
    return opened.isoformat(sep=" ", timespec="minutes")


def _text(cell) -> str:
    return _clean(cell.get_text(" "))


def _clean(text: str) -> str:
    return " ".join((text or "").split())

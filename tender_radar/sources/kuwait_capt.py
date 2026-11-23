"""Kuwait Central Agency for Public Tenders (capt.gov.kw). Public server-rendered HTML list.

robots.txt is empty (allows all). The "open tenders" list (المناقصات المطروحة)
holds every field in a hidden panel after each row, so no detail page is
fetched. There is no numeric id: the tender number is unique only within one
buyer, so the id is `ministry_code:tender_no`. The list can be filtered by
these two values, which gives a link that shows only this tender.
"""

import re
from datetime import date
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

BASE = "https://capt.gov.kw"
LIST_PATH = "/ar/tenders/opening-tenders/"
PAGE_SIZE = 10
AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?")
ARABIC_DATE = re.compile(r"(\S+)\s+(\d{1,2}),\s*(\d{4})")
MINISTRY_IN_POPUP = re.compile(r"--(\d+)$")
PRACTICE = "ممارسة"  # A "practice" is a limited, simpler procurement than a tender.

# Arabic month names as the portal writes them, with common hamza variants.
MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "إبريل": 4, "مايو": 5, "يونيو": 6,
    "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}


class KuwaitCaptSource:
    name = "kuwait_capt"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_pages = settings.get("max_pages", 10)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads, seen = [], set()
        for page in range(1, self.max_pages + 1):
            html = self.client.get_text(f"{BASE}{LIST_PATH}?page={page}")
            panels = BeautifulSoup(html, "html.parser").select(".tenderslist .tender-info")
            # Past the last page the portal serves page 1 again, so stop on no unseen key.
            page_leads = [lead for lead in self._parse_panels(panels) if lead.key not in seen]
            if not page_leads:
                break
            seen.update(lead.key for lead in page_leads)
            leads += page_leads
            if len(panels) < PAGE_SIZE:
                break
        print(f"  kuwait_capt/open: {len(leads)} tenders")
        return leads

    def _parse_panels(self, panels) -> list[Lead]:
        leads = []
        for panel in panels:
            try:
                lead = self._parse_panel(panel)
            except Exception as error:  # one odd row must not lose the page
                print(f"  ! kuwait_capt row skipped: {error}")
                continue
            if lead:
                leads.append(lead)
        return leads

    def _parse_panel(self, panel) -> Lead | None:
        fields = _fields(panel)
        tender_no = fields.get("الرقم", "")
        title = fields.get("الموضوع", "")
        ministry = _ministry_code(panel)
        if not tender_no or not title:
            return None
        buyer = fields.get("الجهة", "")
        return Lead(
            source=self.name,
            source_id=f"{ministry or buyer}:{tender_no}",
            country="Kuwait",
            title=title,
            url=_tender_url(ministry, tender_no),
            ref_no=tender_no,
            buyer=buyer,
            tender_type=PRACTICE if tender_no.startswith(PRACTICE) else fields.get("النوع", ""),
            published=_iso_date(fields.get("تاريخ الطلب", "")),
            closing=_iso_date(fields.get("اخر موعد للعطاء", "")),
            doc_fee=_amount(fields.get("السعر", "")),
            bond=_amount(fields.get("التأمين", "")),
            currency="KWD",
            # Notes sometimes only repeat the tender number.
            brief="" if fields.get("ملاحظات", "") == tender_no else fields.get("ملاحظات", ""),
            extra={
                "alternative_offers": fields.get("العروض البديلة", ""),
                "divisible": fields.get("التجزئة", ""),
                "ministry_code": ministry,
            },
        )


def _fields(panel) -> dict:
    """Each field is a <ul> of two <li>: Arabic label, then value."""
    fields = {}
    for row in panel.select(".detail-list ul"):
        cells = row.find_all("li", recursive=False)
        if len(cells) >= 2:
            fields[_text(cells[0])] = _text(cells[1])
    return fields


def _ministry_code(panel) -> str:
    buy_button = panel.select_one("[data-ministry-code]")
    if buy_button and buy_button["data-ministry-code"]:
        return buy_button["data-ministry-code"]
    popup = panel.select_one("[data-popup-url]")
    match = MINISTRY_IN_POPUP.search(popup["data-popup-url"]) if popup else None
    return match.group(1) if match else ""


def _tender_url(ministry: str, tender_no: str) -> str:
    if not ministry:
        return BASE + LIST_PATH
    return f"{BASE}{LIST_PATH}?{urlencode({'ministry_code': ministry, 'tender_no': tender_no})}"


def _iso_date(text: str) -> str:
    """`نوفمبر 22, 2026` -> `2026-11-22`."""
    match = ARABIC_DATE.search(text)
    if not match or match.group(1) not in MONTHS:
        return ""
    try:
        return date(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2))).isoformat()
    except ValueError:
        return ""


def _amount(text: str) -> str:
    """`15,000.000 د.ك` -> `15,000`. KWD has 3 decimals (fils); keep them only when not zero."""
    match = AMOUNT.search(text)
    if not match:
        return ""
    value = float(match.group(0).replace(",", ""))
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _text(element) -> str:
    return " ".join(element.get_text(" ").split()) if element else ""

"""Qatar Football Association tenders (qfa.qa). Public server-rendered HTML list.

robots.txt allows all generic agents (it blocks only AI crawlers) and sets
`use=reference`: we keep a link back to the list. QFA does not publish on
Monaqasat. There is no detail page and no numeric id, so the tender number
(`T/10/2026`) is the id.
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

LIST_URL = "https://www.qfa.qa/en/tenders?page={page}"
TENDER_NO = re.compile(r"T\s*[\\/]\s*(\d+)\s*/\s*(\d{4})")
AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?")
CONTACT_NOISE = re.compile(r"For (?:bank details and )?more info.*|\[email\s*protected\]", re.I | re.S)
# Bond wording varies: "bond in the amount of 25,000 QR", "15,000 QR Tender Bond", or only "30,000 QR".
BOND_AFTER = re.compile(r"bond\D{0,40}?(\d[\d,]*)", re.I)
BOND_BEFORE = re.compile(r"(\d[\d,]*)\s*(?:QR|QAR)?\s*tender bond", re.I)
BOND_ONLY = re.compile(r"(?:QR\s*)?(\d[\d,]*)\s*(?:QR|QAR)?\.?")


class QfaSource:
    name = "qfa"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_pages = settings.get("max_pages", 5)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads, seen = [], set()
        for page in range(1, self.max_pages + 1):
            soup = BeautifulSoup(self.client.get_text(LIST_URL.format(page=page)), "html.parser")
            # Past the last page the list is empty.
            page_leads = [lead for box in soup.select(".tender-box") if (lead := self._parse_box(box))]
            page_leads = [lead for lead in page_leads if lead.key not in seen]
            if not page_leads:
                break
            seen.update(lead.key for lead in page_leads)
            leads += page_leads
        print(f"  qfa/open: {len(leads)} tenders")
        return leads

    def _parse_box(self, box) -> Lead | None:
        heading = box.select_one(".tender-heading p")
        # Auctions are QFA selling assets, not buying.
        if not heading or _text(heading).lower().startswith("auction"):
            return None
        dates = _dates(box)
        number = TENDER_NO.search(box.get_text(" "))
        ref_no = f"T/{int(number.group(1)):02d}/{number.group(2)}" if number else ""
        title = CONTACT_NOISE.sub("", TENDER_NO.sub("", _text(heading))).strip(" -")
        tags = [_text(tag) for tag in box.select(".tag")]
        description = _description(box)
        return Lead(
            source=self.name,
            # Older tenders have no number; issue date + title is the most stable fallback.
            source_id=ref_no or f"{dates.get('Issue Date', '')}:{title}",
            country="Qatar",
            title=title,
            url=LIST_URL.format(page=1),
            ref_no=ref_no,
            buyer="Qatar Football Association",
            tender_type=tags[0] if tags else "",
            category=tags[1] if len(tags) > 1 else "",
            published=dates.get("Issue Date", ""),
            closing=dates.get("Closing Date", ""),
            doc_fee=_first_amount(box.select_one("h6")),
            bond=_bond(description),
            currency="QAR",
            brief=description,
        )


def _dates(box) -> dict:
    """Label <p> followed by a DD-MM-YYYY <h4>."""
    dates = {}
    for label in box.select("p.text-primary"):
        value = label.find_next_sibling("h4")
        if value:
            dates[_text(label)] = _iso_date(_text(value))
    return dates


def _description(box) -> str:
    desc = box.select_one(".tender-desc")
    return CONTACT_NOISE.sub("", _text(desc)).strip() if desc else ""


def _bond(description: str) -> str:
    match = BOND_AFTER.search(description) or BOND_BEFORE.search(description) or BOND_ONLY.fullmatch(description)
    return match.group(1) if match else ""


def _first_amount(cell) -> str:
    match = AMOUNT.search(_text(cell)) if cell else None
    return match.group(0) if match else ""


def _iso_date(text: str) -> str:
    try:
        return datetime.strptime(text, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return ""


def _text(element) -> str:
    return " ".join(element.get_text(" ").split()) if element else ""

"""Qatar Ministry of Finance e-tendering portal (Monaqasat). Public pages, robots.txt allows all.

Awarded tenders have a public award report with the winners, the approved
value and every bid, read for new awarded tenders only.
"""

from datetime import datetime

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

BASE = "https://monaqasat.mof.gov.qa"
LIST_PATHS = {
    "open": "/TendersOnlineServices/AvailableMinistriesTenders/{page}",
    "future": "/TendersOnlineServices/FutureTenders/{page}",
    "awarded": "/TendersOnlineServices/AwardedTenders/{page}",
}
AWARD_REPORT = "/TendersOnlineServices/TenderCompaniesDetails/{id}"

# Card labels on the list page -> Lead attribute.
CARD_FIELDS = {
    "تاريخ الطرح": "published",
    "تاريخ الترسية": "published",
    "نوع القطاع المطلوب": "category",
    "التأمين المؤقت (رق)": "bond",
    "قيمة الوثائق (رق)": "doc_fee",
    "الجهة": "buyer",
    "النوع": "tender_type",
}


class MonaqasatSource:
    name = "monaqasat"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_pages = settings.get("max_pages", 30)
        self.awarded_pages = settings.get("awarded_pages", 3)
        self.fetch_details = settings.get("fetch_details", True)
        self.award_reports = settings.get("award_reports", True)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads = self._collect_list("open", self.max_pages)
        leads += self._collect_list("future", self.max_pages)
        leads += self._collect_list("awarded", self.awarded_pages)
        for lead in leads:
            # Awarded tenders get details too: their activities make the score useful.
            if self.fetch_details and lead.key not in known_keys:
                self._add_details(lead)
            # An open tender keeps its id when awarded, so check the stored status, not only the key.
            if self.award_reports and lead.status == "awarded" and known_keys.get(lead.key) != "awarded":
                self.add_award(lead)
        return leads

    def _collect_list(self, status: str, max_pages: int) -> list[Lead]:
        leads, seen = [], set()
        for page in range(1, max_pages + 1):
            html = self.client.get_text(BASE + LIST_PATHS[status].format(page=page))
            page_leads = [lead for lead in self._parse_cards(html, status) if lead.key not in seen]
            if not page_leads:
                break
            seen.update(lead.key for lead in page_leads)
            leads += page_leads
        print(f"  monaqasat/{status}: {len(leads)} tenders")
        return leads

    def _parse_cards(self, html: str, status: str) -> list[Lead]:
        soup = BeautifulSoup(html, "html.parser")
        return [lead for card in soup.select("div.custom-cards") if (lead := self._parse_card(card, status))]

    def _parse_card(self, card, status: str) -> Lead | None:
        link = card.select_one(".card-title a[href]")
        if not link:
            return None
        source_id = link["href"].rstrip("/").split("/")[-1]
        lead = Lead(
            source=self.name,
            source_id=source_id,
            country="Qatar",
            title=_clean(link.get_text()),
            url=BASE + link["href"],
            status=status,
            currency="QAR",
        )
        header = card.select_one(".col-header .card-label")
        lead.ref_no = _clean(header.get_text()) if header else ""
        self._apply_card_fields(card, lead)
        lead.closing = self._closing_date(card)
        return lead

    def _apply_card_fields(self, card, lead: Lead):
        for row in card.select(".cards-row, .col-header"):
            label = row.select_one(".card-label")
            value = row.select_one(".card-title")
            attr = CARD_FIELDS.get(_clean(label.get_text())) if label else None
            if attr and value:
                text = _clean(value.get_text())
                setattr(lead, attr, _iso_date(text) if attr == "published" else text)

    def _closing_date(self, card) -> str:
        for label in card.select(".circle-container .card-label"):
            if "الإغلاق" in label.get_text():
                parts = [_clean(span.get_text()) for span in label.find_all("span")]
                return _iso_date(parts[-1]) if parts else ""
        return ""

    def _add_details(self, lead: Lead):
        try:
            soup = BeautifulSoup(self.client.get_text(lead.url), "html.parser")
        except Exception as error:  # one bad page must not stop the run
            print(f"  ! detail failed {lead.url}: {error}")
            return
        fields, activities = _parse_detail_tables(soup)
        lead.brief = fields.get("نبذة مختصرة", "")
        lead.activities = "; ".join(activities)
        lead.closing = _iso_date(fields.get("تاريخ الاقفال", "")) or lead.closing
        lead.extra |= {
            "buyer_ref": fields.get("رقم المناقصة لدى الجهة", ""),
            "bidder_types": fields.get("أنواع مقدمي العطاءات المستهدفين", ""),
            "delivery_place": fields.get("مكان التنفيذ أو التسليم", ""),
            "contract_months": fields.get("مدة العقد (عدد الأشهر)", ""),
            "envelopes": fields.get("نظام المظاريف", ""),
        }

    def add_award(self, lead: Lead):
        """Adds winners, award value and bids from the public award report. Also used to backfill old tenders."""
        url = BASE + AWARD_REPORT.format(id=lead.source_id)
        try:
            soup = BeautifulSoup(self.client.get_text(url), "html.parser")
        except Exception as error:  # one bad page must not stop the run
            print(f"  ! award report failed {url}: {error}")
            return
        lead.extra |= _parse_award_tables(soup) | {"award_report": url}


def _parse_award_tables(soup) -> dict:
    """Report tables, told apart by header: winners, bidders (technical opening), bids (financial opening)."""
    award = {}
    for table in soup.find_all("table"):
        rows = [[_clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        head, body = (rows[0], [r for r in rows[1:] if r and r[0]]) if rows else ([], [])
        if "القيمة الموافق عليها" in head:
            # The commercial registration (CR) number identifies the company, e.g. to find its contacts.
            award["winners"] = [{"company": r[0], "cr": r[1], "value": _amount(r[2])} for r in body if len(r) > 2]
            award["award_value"] = _total(w["value"] for w in award["winners"])
        elif head == ["اسم الشركة", "رقم السجل التجاري"]:
            award["bidders"] = len(body)
        elif "قيمة العطاء" in head:
            award["bids"] = [_bid(r) for r in body if len(r) > 5]
    # Single-envelope tenders have no technical-opening table; every bid is a bidder.
    if "bids" in award:
        award.setdefault("bidders", len(award["bids"]))
    return award


def _bid(row: list[str]) -> dict:
    # Columns: company, CR no, bid value, local value %, financial result, notes ("مستبعد" = excluded).
    return {"company": row[0], "value": _amount(row[2]), "result": row[4], "note": row[5]}


def _amount(text: str) -> str:
    """'284,050.00 رق' -> '284,050.00'."""
    return text.replace("رق", "").strip()


def _total(values) -> str:
    try:
        return f"{sum(float(v.replace(',', '')) for v in values if v):,.2f}"
    except ValueError:
        return ""


def _parse_detail_tables(soup) -> tuple[dict, list[str]]:
    """Detail page has header-row tables, name/value tables and an activity table."""
    fields, activities = {}, []
    for table in soup.find_all("table"):
        rows = [[_clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        rows = [r for r in rows if r]
        if not rows:
            continue
        head = rows[0]
        if head[:2] == ["كود النشاط", "اسم النشاط"]:
            activities += [f"{r[0]} {r[1]}" for r in rows[1:] if len(r) >= 2]
        elif head[:2] == ["الاسم", "القيمة"]:
            fields.update({r[0]: r[1] for r in rows[1:] if len(r) >= 2})
        elif len(rows) >= 2:
            fields.update(dict(zip(head, rows[1])))
    return fields, activities


def _clean(text: str) -> str:
    return " ".join(text.split())


def _iso_date(text: str) -> str:
    try:
        return datetime.strptime(text.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""

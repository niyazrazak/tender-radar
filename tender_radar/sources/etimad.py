"""Saudi Arabia government procurement portal (Etimad). Uses the JSON feed behind the visitor page."""

from urllib.parse import quote

from tender_radar.lead import Lead

BASE = "https://tenders.etimad.sa"
FEED = "/Tender/AllSupplierTendersForVisitorAsync"
PAGE_SIZE = 24
# Etimad's own "published since" filter values.
PUBLISH_WINDOWS = {"2days": 2, "week": 3, "month": 4, "3months": 5}
ACTIVE_TENDERS = 2


class EtimadSource:
    name = "etimad"

    def __init__(self, client, settings: dict):
        self.client = client
        self.window = PUBLISH_WINDOWS[settings.get("publish_window", "week")]
        self.max_pages = settings.get("max_pages", 40)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads = []
        for page in range(1, self.max_pages + 1):
            data = self.client.get_json(BASE + FEED, params=self._params(page))
            rows = data.get("data") or []
            leads += [self._to_lead(row) for row in rows]
            if len(rows) < PAGE_SIZE or len(leads) >= data.get("totalCount", 0):
                break
        print(f"  etimad/open: {len(leads)} tenders")
        return leads

    def _params(self, page: int) -> dict:
        return {
            "PageSize": PAGE_SIZE,
            "PageNumber": page,
            "PublishDateId": self.window,
            "TenderCategory": ACTIVE_TENDERS,
            "IsSearch": "true",
            "sort": "SubmitionDate",
            "sortDirection": "DESC",
        }

    def _to_lead(self, row: dict) -> Lead:
        buyer = row.get("agencyName") or ""
        branch = row.get("branchName") or ""
        return Lead(
            source=self.name,
            source_id=str(row["tenderId"]),
            country="Saudi Arabia",
            title=_clean(row.get("tenderName")),
            url=self._detail_url(row),
            ref_no=row.get("referenceNumber") or "",
            buyer=f"{buyer} — {branch}" if branch and branch != buyer else buyer,
            category=_clean(row.get("tenderActivityName")),
            tender_type=row.get("tenderTypeName") or "",
            published=(row.get("submitionDate") or "")[:10],
            closing=(row.get("lastOfferPresentationDate") or "")[:10],
            doc_fee=str(row.get("condetionalBookletPrice") or ""),
            currency="SAR",
            extra={
                "tender_number": row.get("tenderNumber") or "",
                "last_enquiry": (row.get("lastEnqueriesDate") or "")[:10],
                "offers_opening": (row.get("offersOpeningDate") or "")[:10],
            },
        )

    def _detail_url(self, row: dict) -> str:
        if row.get("isUGRP") and row.get("ugrpRfxUrl"):
            return row["ugrpRfxUrl"]
        page = "DetailsTenderAnnouncement" if row.get("tenderTypeId") == 15 else "DetailsForVisitor"
        return f"{BASE}/Tender/{page}?STenderId={quote(row.get('tenderIdString') or '')}"


def _clean(text) -> str:
    return " ".join((text or "").split())

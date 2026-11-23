"""Mwani Qatar (Qatar Ports Management) tenders. Public SharePoint list read as JSON.

The tenders page fills itself from the site's anonymous `_api` endpoint
(robots.txt blocks only `_layouts`, `_vti_bin`, `_catalogs`). Mwani does not
publish on Monaqasat. There is no detail page, so `url` is the list page.
"""

from datetime import datetime, timedelta

from tender_radar.lead import Lead

PAGE_URL = "https://www.mwani.com.qa/English/Procurement/Pages/TendersAuctions.aspx"
# SharePoint list items do not support $skip; newest first is enough at 2-3 tenders a month.
API_URL = (
    "https://www.mwani.com.qa/_api/web/lists/GetByTitle('Tenders%20and%20Auctions')/items"
    "?$top={top}&$orderby=Created%20desc"
)
ODATA = {"Accept": "application/json;odata=verbose"}
QATAR_OFFSET = timedelta(hours=3)  # dates are stored as Qatar midnight in UTC


class MwaniSource:
    name = "mwani"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_items = settings.get("max_items", 50)

    def collect(self, known_keys: dict) -> list[Lead]:
        data = self.client.get_json(API_URL.format(top=self.max_items), headers=ODATA)
        # Auctions are Mwani selling assets, not buying.
        leads = [self._lead(item) for item in data["d"]["results"] if item.get("Category", "").startswith("Tender")]
        print(f"  mwani/open: {len(leads)} tenders")
        return leads

    def _lead(self, item: dict) -> Lead:
        title = _clean(item.get("Title"))
        arabic = _clean(item.get("Arabic_x0020_Title"))
        return Lead(
            source=self.name,
            source_id=str(item["Id"]),
            country="Qatar",
            title=title,
            url=PAGE_URL,
            ref_no=_clean(item.get("Tender_x0020_Number")),
            buyer="Mwani Qatar",
            tender_type=_clean(item.get("Submission_x0020_Method")).split(";")[0],
            published=_qatar_date(item.get("Start_x0020_Date")),
            closing=_qatar_date(item.get("Closing_x0020_Date")),
            doc_fee=_amount(item.get("Tender_x0020_Fee")),
            bond=_amount(item.get("Tender_x0020_Bond_x0020_Value")),
            currency="QAR",
            brief=arabic if arabic != title else "",
            extra={"contact": _clean(item.get("English_x0020_Content"))},
        )


def _qatar_date(value: str | None) -> str:
    """'2026-11-11T21:00:00Z' -> '2026-11-12' (Qatar local date)."""
    try:
        return (datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") + QATAR_OFFSET).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _amount(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.0f}" if value else ""
    return _clean(value)


def _clean(text) -> str:
    return " ".join(str(text or "").split())

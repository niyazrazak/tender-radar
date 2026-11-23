"""WOQOD (Qatar Fuel) tenders. Public JSON API behind the "Online Tenders" page.

The Angular page /website/en/tenders-and-supplier/all-tenders reads
`fo_api_website/api/Tenders/getAllTenderDetails` anonymously. The response body
is a JSON string that holds the JSON, so it is decoded twice. WOQOD does not
publish on Monaqasat. Its firewall rejects /robots.txt for every visitor, a
browser too, and its terms forbid only interfering with or loading the service,
so this source makes one request per check.
"""

import html
import json
import re

from tender_radar.lead import Lead

SITE = "https://www.woqod.com/website/en"
API_URL = (
    "https://www.woqod.com/fo_api_website/api/Tenders/getAllTenderDetails"
    "?PageSize={size}&PageIndex={page}&TenderStatus=0"  # 0 = open, 1 = closed
)
PAGE_SIZE = 50
TAGS = re.compile(r"<[^>]+>")


class WoqodSource:
    name = "woqod"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_pages = settings.get("max_pages", 2)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads = []
        for page in range(1, self.max_pages + 1):
            data = self._page(page)
            leads += [self._lead(item) for item in data["pageItems"] if not item.get("isCanceled")]
            if page * PAGE_SIZE >= data["totalCount"]:
                break
        print(f"  woqod/open: {len(leads)} tenders")
        return leads

    def _page(self, page: int) -> dict:
        body = self.client.get_json(API_URL.format(size=PAGE_SIZE, page=page))
        body = json.loads(body) if isinstance(body, str) else body
        if not body.get("status"):
            raise RuntimeError(f"WOQOD API refused: {body.get('messageEN') or body}")
        return body["data"]

    def _lead(self, item: dict) -> Lead:
        return Lead(
            source=self.name,
            source_id=item["tenderDetailsID"],
            country="Qatar",
            title=_clean(item.get("titleEN") or item.get("titleAR")),
            url=SITE + item["pageURL"] if item.get("pageURL") else SITE + "/tenders-and-supplier/all-tenders",
            ref_no=_clean(item.get("tenderNumber")),
            buyer="WOQOD",
            category=_clean(item.get("categoryNameEN")),
            published=(item.get("startingDate") or "")[:10],
            closing=(item.get("closingDate") or "")[:10],
            doc_fee=_fee(item),
            bond=_amount(item.get("tenderBond")),
            currency="QAR",
            brief=_text(item.get("scopeOfWorkEN"), item.get("descriptionEN")),
            # The details are the same bid instructions on every tender ("obtain the document on the
            # website / portal"); scoring them would give every tender points for "website" and "portal".
            extra={
                "instructions": _text(item.get("detailsEN")),
                "last_collection": (item.get("lastCollectionDate") or "")[:10],
            },
        )


def _fee(item: dict) -> str:
    """A 0 fee on an unpaid tender means the documents are free; keep it as "0"."""
    fee = item.get("fee") or 0
    if fee:
        return _amount(fee)
    return "" if item.get("isPaid") else "0"


def _amount(value) -> str:
    """A 0 bond means WOQOD did not state one, so it stays empty."""
    return f"{value:,.0f}" if isinstance(value, (int, float)) and value else ""


def _text(*parts) -> str:
    return _clean(html.unescape(" ".join(TAGS.sub(" ", part or "") for part in parts)))


def _clean(text) -> str:
    return " ".join(str(text or "").split())

"""ORYX GTL tenders (oryxgtl.qa). Public WordPress pages, read as HTML.

robots.txt blocks only /wp-admin/; the WordPress REST API answers 401, so the
lists are read as pages. Open, future and closed tenders each have a page with a
`ul.tender-list` of links, newest first. Each tender page has a `.tenders-info`
list: number, fee, bond, bid closing date and document collection closing date.

To bid, a company pays the fee and registers by email before the document
collection closing date; after that the tender moves to "Closed Tenders" while
bids are still open. So `closing` is the collection closing date, the last day a
new bidder can join, and the bid closing date is kept in `extra`.

The store overwrites a lead on every run, so every lead returned is read in full.
That is why only the newest `closed_items` closed tenders are returned (they
catch a tender that opened and closed between two checks): the closed page lists
over 300.
"""

from datetime import datetime

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

BASE = "https://www.oryxgtl.qa"
LISTS = {"open-tenders": "open", "future-tenders": "future", "closed-tenders": "open"}

# Label on the tender page -> what it fills.
INFO_FIELDS = {
    "Tender No.": "ref_no",
    "Tender Fee": "doc_fee",
    "Tender Bond": "bond",
    "Bid Closing Date": "bid_closing",
    "Tender Documents Collection Closing Date": "collection_closing",
}


class OryxGtlSource:
    name = "oryx_gtl"

    def __init__(self, client, settings: dict):
        self.client = client
        self.closed_items = settings.get("closed_items", 5)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads = []
        for path, status in LISTS.items():
            found = self._list(path, status)
            leads += found[: self.closed_items] if path == "closed-tenders" else found
        for lead in leads:
            self._add_details(lead)
        print(f"  oryx_gtl: {len(leads)} tenders")
        return leads

    def _list(self, path: str, status: str) -> list[Lead]:
        soup = BeautifulSoup(self.client.get_text(f"{BASE}/{path}/"), "html.parser")
        return [self._lead(link, status) for link in soup.select("ul.tender-list li a[href]")]

    def _lead(self, link, status: str) -> Lead:
        url = link["href"]
        return Lead(
            source=self.name,
            source_id=url.rstrip("/").rsplit("/", 1)[-1],  # the page slug, e.g. "soc-support-services-fy-27-29"
            country="Qatar",
            title=_clean(link.get_text()),
            url=url,
            status=status,
            buyer="ORYX GTL",
            currency="QAR",
        )

    def _add_details(self, lead: Lead):
        try:
            soup = BeautifulSoup(self.client.get_text(lead.url), "html.parser")
        except Exception as error:  # one bad page must not stop the run
            print(f"  ! detail failed {lead.url}: {error}")
            return
        info = {}
        for item in soup.select(".tenders-info li"):
            label = item.select_one(".title")
            if label and _clean(label.get_text()) in INFO_FIELDS:
                field = INFO_FIELDS[_clean(label.get_text())]
                label.extract()
                info[field] = _clean(item.get_text())
        lead.ref_no = info.get("ref_no", "")
        lead.category = _department(lead.ref_no)
        lead.doc_fee = _amount(info.get("doc_fee"))
        lead.bond = _amount(info.get("bond"))
        bid_closing = _iso_date(info.get("bid_closing"))
        lead.closing = _iso_date(info.get("collection_closing")) or bid_closing
        email = soup.select_one(".wysiwyg a[href^='mailto:']")
        lead.extra = {"bid_closing": bid_closing, "register_by_email": email["href"][7:] if email else ""}


def _department(ref_no: str) -> str:
    """"TC-CN-018-26-IT" -> "IT department". The last part of the number is the department."""
    parts = ref_no.split("-")
    return f"{parts[-1]} department" if len(parts) >= 5 and parts[-1].isalpha() else ""


def _amount(text: str | None) -> str:
    """"QAR 45,500.00" -> "45,500"."""
    number = (text or "").replace("QAR", "").strip()
    return number.removesuffix(".00")


def _iso_date(text: str | None) -> str:
    try:
        return datetime.strptime(text or "", "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def _clean(text) -> str:
    return " ".join(str(text or "").split())

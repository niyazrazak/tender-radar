"""Gulf Times newspaper tender adverts, read by Claude from the daily PDF.

Semi-government bodies and companies (e.g. Qatar Primary Materials Company) advertise tenders in the
paper that are on no portal. https://www.gulf-times.com/pdfs links each day's PDFs as
`/gulftimes/uploads/pdf/YYYY/MM/DD/<section>-YYYYMMDD-1-<ts>.pdf`. The advert pages are scanned
images with no text layer, so Claude reads the pages (vision) and returns the adverts as data.

robots.txt allows /pdfs and the uploads, with Crawl-delay: 2 (set `delay_seconds` 2 in config.json).
Each issue is read once and cached in data/gulf_times/, because there are four checks a day and one
issue. A day without adverts is normal, so this source never raises the "0 tenders" warning.
"""

import hashlib
import json
import re
from pathlib import Path

from tender_radar.lead import Lead

PDFS_URL = "https://www.gulf-times.com/pdfs"
PDF_LINK = re.compile(r'href="([^"]*/uploads/pdf/(\d{4})/(\d{2})/(\d{2})/([a-z]+)-\d{8}[^"]*\.pdf[^"]*)"')
DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "data" / "gulf_times"
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
AMOUNT = re.compile(r"\d[\d,]*(\.\d+)?%?")


class GulfTimesSource:
    name = "gulf_times"
    needs_ai = True  # cli passes the Claude analyst
    may_be_empty = True  # most days have no tender adverts

    def __init__(self, client, settings: dict, analyst=None):
        self.client = client
        self.analyst = analyst
        self.sections = settings.get("sections", ["main", "business"])
        self.days = settings.get("days", 2)
        cache = settings.get("cache_dir", str(DEFAULT_CACHE))
        self.cache = Path(cache) if cache else None

    def collect(self, known_keys: dict) -> list[Lead]:
        leads = {}
        for url, issue, section in self._issues():
            for advert in self._adverts(url):
                lead = self._lead(advert, url, issue, section)
                leads.setdefault(lead.source_id, lead)  # an advert printed on several days is one tender
        print(f"  gulf_times/adverts: {len(leads)} tenders")
        return list(leads.values())

    def _issues(self) -> list[tuple[str, str, str]]:
        """(PDF url, issue date, section) for the newest `days` issues of the chosen sections."""
        found = {}
        for href, year, month, day, section in PDF_LINK.findall(self.client.get_text(PDFS_URL)):
            if section in self.sections:
                url = href if href.startswith("http") else "https://www.gulf-times.com" + href
                found.setdefault((f"{year}-{month}-{day}", section), url)
        dates = sorted({date for date, _ in found}, reverse=True)[:self.days]
        return [(url, date, section) for (date, section), url in sorted(found.items()) if date in dates]

    def _adverts(self, url: str) -> list[dict]:
        """The adverts in one issue: from the cache, else read by Claude once and cached."""
        path = self.cache / (url.split("?")[0].rsplit("/", 1)[-1] + ".json") if self.cache else None
        if path and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        adverts = self.client.read_pdf(url, self._read)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(adverts, ensure_ascii=False, indent=1), encoding="utf-8")
        return adverts

    def _read(self, name: str, pdf: bytes) -> list[dict]:
        if not self.analyst:
            raise RuntimeError("Gulf Times adverts need Claude: log in to Claude Code or set ANTHROPIC_API_KEY")
        return self.analyst.read_adverts(name, pdf)

    def _lead(self, advert: dict, url: str, issue: str, section: str) -> Lead:
        number = _clean(advert.get("tender_no"))
        buyer, title = _clean(advert.get("buyer")), _clean(advert.get("title"))
        page = advert.get("page") or 1
        return Lead(
            source=self.name,
            source_id=re.sub(r"\s+", "", number.upper()) or _digest(buyer, title),
            country="Qatar",
            title=title or f"Tender {number}",
            url=f"{url.split('?')[0]}#page={page}",
            ref_no=number,
            buyer=buyer,
            tender_type=f"{_clean(advert.get('kind')) or 'Tender'} (newspaper advert)",
            published=issue,
            closing=_iso(advert.get("closing_date")),
            doc_fee=_amount(advert.get("doc_fee")),
            bond=_amount(advert.get("bond")),
            currency=_clean(advert.get("currency")).upper() or "QAR",
            brief=_clean(advert.get("summary")),
            extra={"newspaper": "Gulf Times", "section": section, "page": page},
        )


def _iso(text) -> str:
    text = _clean(text)
    return text if ISO.fullmatch(text) else ""


def _amount(text) -> str:
    """"500", "19,000", "2%" or "0"; anything else (words, ranges) is dropped rather than guessed."""
    text = _clean(text).replace(" ", "")
    return text if AMOUNT.fullmatch(text) else ""


def _digest(*parts) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _clean(text) -> str:
    return " ".join(str(text or "").split())

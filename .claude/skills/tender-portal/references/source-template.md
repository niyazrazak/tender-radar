# Source template

Start a new source from this shape. Delete what the portal does not need.
Both existing sources (`monaqasat.py` for HTML, `etimad.py` for JSON) are
real examples of it.

```python
"""<Country> <owner> e-tendering portal (<Portal name>). <How it is read: HTML pages / JSON feed>."""

from datetime import datetime

from bs4 import BeautifulSoup

from tender_radar.lead import Lead

BASE = "https://portal.example.gov"
LIST_PATH = "/tenders?page={page}"
PAGE_SIZE = 20

# Portal label -> Lead attribute. Keep the label exactly as the page shows it.
FIELDS = {
    "تاريخ الطرح": "published",
    "الجهة": "buyer",
}


class ExampleSource:
    name = "example"

    def __init__(self, client, settings: dict):
        self.client = client
        self.max_pages = settings.get("max_pages", 20)
        self.fetch_details = settings.get("fetch_details", True)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads = self._collect_list()
        if self.fetch_details:
            for lead in leads:
                if lead.key not in known_keys:
                    self._add_details(lead)
        return leads

    def _collect_list(self) -> list[Lead]:
        leads, seen = [], set()
        for page in range(1, self.max_pages + 1):
            html = self.client.get_text(BASE + LIST_PATH.format(page=page))
            page_leads = [lead for lead in self._parse_list(html) if lead.key not in seen]
            if not page_leads:
                break
            seen.update(lead.key for lead in page_leads)
            leads += page_leads
        print(f"  {self.name}/open: {len(leads)} tenders")
        return leads

    def _parse_list(self, html: str) -> list[Lead]:
        soup = BeautifulSoup(html, "html.parser")
        return [lead for row in soup.select("<row selector>") if (lead := self._parse_row(row))]

    def _parse_row(self, row) -> Lead | None:
        link = row.select_one("a[href]")
        if not link:
            return None
        return Lead(
            source=self.name,
            source_id=link["href"].rstrip("/").split("/")[-1],  # the portal's own id
            country="<Country>",
            title=_clean(link.get_text()),
            url=BASE + link["href"],
            currency="<ISO code>",
        )

    def _add_details(self, lead: Lead):
        try:
            soup = BeautifulSoup(self.client.get_text(lead.url), "html.parser")
        except Exception as error:  # one bad page must not stop the run
            print(f"  ! detail failed {lead.url}: {error}")
            return
        lead.brief = ...


def _clean(text) -> str:
    return " ".join((text or "").split())


def _iso_date(text: str, fmt: str = "%d/%m/%Y") -> str:
    try:
        return datetime.strptime(text.strip(), fmt).date().isoformat()
    except ValueError:
        return ""
```

`config.json` block:

```json
"example": {
  "enabled": true,
  "max_pages": 20,
  "fetch_details": true
}
```

Register it in `tender_radar/sources/__init__.py`:

```python
SOURCES = {source.name: source for source in (MonaqasatSource, EtimadSource, ExampleSource)}
```

Country names in use: `Qatar`, `Saudi Arabia`, `Oman`. Use the English short name
(`Kuwait`, `Bahrain`, `United Arab Emirates`), because the report's
country filter groups by this text.

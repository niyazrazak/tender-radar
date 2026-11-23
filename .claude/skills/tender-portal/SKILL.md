---
name: tender-portal
description: Add, fix or maintain a tender/RFQ portal scraper in the tender-radar project (Monaqasat, Mwani and QFA in Qatar, Etimad Saudi, Oman Tender Board, and new GCC portals such as Kuwait CAPT, Bahrain Tender Board, UAE, QatarEnergy LNG). Use this skill whenever the user wants to scrape a new procurement portal, says a portal "returns 0 tenders", "broke", "fails with SSL error", wants more fields (brief, closing date, fee, bond, buyer) from a portal, wants to change paging or filters, or asks how a source in tender_radar/sources works, even if they do not say "skill" or "scraper".
---

# Tender portal sources

tender-radar collects tenders from government procurement portals, normalizes
them to one `Lead`, scores them by keywords and writes HTML and Excel reports.
Each portal is one **source** module in `tender_radar/sources/`. This skill
tells you how to add a source, how to fix one that stopped working, and what
the rest of the pipeline expects from a source.

Read `references/portals.md` before you touch an existing source. It holds the
portal facts that are not obvious from the code (TLS quirks, Arabic labels,
filter values, paging behavior).

## How the pipeline uses a source

```
cli.TenderRadar.collect()
  → SOURCES[name](client, settings).collect(known_keys) -> list[Lead]
  → store.restore_details()   # copies brief/activities saved on earlier runs
  → KeywordScorer.score()     # title + brief + activities + category
  → store.save()              # upsert by key "source:source_id"
```

What this means for a source:

- **`source_id` must be stable.** The store key is `f"{source}:{source_id}"`.
  If the id changes between runs, every tender shows as NEW each day and the
  database fills with duplicates. Use the portal's own tender id, never a row
  number or a page position.
- **Fill text the scorer reads.** Scoring uses `title`, `brief`, `activities`
  and `category`. A source that fills only `title` scores poorly. Get the
  activity/category name from the list if the portal gives it, and the brief
  from the detail page. Keep a numeric activity code at the start of each
  activity (`620102 تصميم وبرمجة ...`): the scorer also scores code prefixes
  from `keywords.activity_codes` in `config.json`.
- **Fetch details only for new leads.** `known_keys` (`{key: stored status}`)
  is passed in so a source fetches detail pages only for
  `lead.key not in known_keys`. Use the status when a page depends on it:
  Monaqasat fetches the award report when a known open tender turns awarded. The store copies
  old details back. This keeps a daily run to a few requests per new tender.
- **Dates are ISO `YYYY-MM-DD` strings, or `""`.** The store filters closed
  tenders with `closing >= date('now')`, so a wrong format hides or shows the
  wrong leads. Return `""` when a date cannot be parsed. Do not guess.
- **One failure must not stop the run.** `cli` catches an exception from a
  whole source. Inside a source, catch errors per detail page (see
  `MonaqasatSource._add_details`), so one bad page does not lose the list.
- **`status`** is `open`, `future` or `awarded`. Awarded tenders are useful
  market intelligence (who buys what), but do not fetch their details.

## Adding a new portal

1. **Check that you may scrape it.** Read the portal's `robots.txt` and terms.
   Use only public pages that a visitor can see without login. If the portal
   needs a login, a supplier account or a CAPTCHA, stop and tell the user.
   Do not bypass it.
2. **Find the data source.** Open the public tender list in a browser. Use the
   Claude in Chrome tools (`anthropic-skills:chrome-browser` skill) if they are
   available, and look at the network requests while you change page or
   filter. Prefer, in this order:
   1. A JSON endpoint behind the page (as for Etimad). It is faster and more
      stable than HTML.
   2. Server-rendered HTML pages with page numbers in the URL (as for
      Monaqasat).
   3. A page that needs JavaScript to render. Tell the user first: this needs
      a headless browser, which the project does not use yet.
3. **Probe it with the project's HTTP client** before you write the parser:
   `.venv/bin/python .claude/skills/tender-portal/scripts/probe_url.py <url>`.
   This uses `PoliteClient`, so you see the same TLS and header behavior the
   real run gets. Save a sample page to the scratchpad and write the parser
   against it.
4. **Write `tender_radar/sources/<name>.py`.** Follow the shape in
   `references/source-template.md`. Copy the conventions of the two existing
   sources: a module docstring that names the portal and how it is read,
   constants at the top (`BASE`, paths, label maps), a class with a `name`
   attribute, `__init__(self, client, settings)` and
   `collect(self, known_keys) -> list[Lead]`.
5. **Register it** in `tender_radar/sources/__init__.py` (the `SOURCES` tuple)
   and add a block under `"sources"` in `config.json` with `"enabled": true`
   and its paging settings.
6. **Test it without touching the database:**
   `.venv/bin/python .claude/skills/tender-portal/scripts/try_source.py <name> --pages 1`.
   It runs only `collect()` and the scorer, and prints the leads. Check that
   ids are stable, dates are ISO, the URL opens the right tender, and Arabic
   text is clean.
7. **Add keywords if needed.** If the portal uses words the current keyword
   lists do not cover (another dialect, English-only titles), tell the user
   and suggest additions to `config.json`. The keywords are the user's
   business choice, so suggest them. Do not edit them without asking.
8. **Record test fixtures.** Add the source to `RECORD_SETTINGS` in
   `tests/recorder.py` with small settings (one page), then run
   `.venv/bin/python -m tests.recorder <name>` and
   `.venv/bin/python -m pytest tests`. `test_every_source_has_fixtures`
   fails until a registered source is recorded.
9. Then run the real collection once:
   `.venv/bin/python -m tender_radar collect --sources <name>`.

## Fixing a source that broke

After the fix, record the source again (`python -m tests.recorder <name>`) so
the offline tests run against the portal's new pages.


Typical symptoms and where to look:

| Symptom | Likely cause | What to check |
|---|---|---|
| `SSLError`, `ConnectionResetError`, `UNEXPECTED_EOF` | The portal changed its certificate or ciphers | `GovPortalTLSAdapter` in `http_client.py` and `tender_radar/certs/intermediates.pem`. See "TLS problems" below. |
| `monaqasat/open: 0 tenders`, no error | HTML changed: a CSS class or an Arabic label | Probe the list URL and compare it with the selectors and `CARD_FIELDS` |
| Fields empty but leads found | A label text changed (often a hamza or a space) | Print the labels the page has now and compare them with the label map |
| `etimad` JSON error or HTML instead of JSON | The endpoint moved, or it wants other headers or params | Open the visitor page in a browser and look for the new XHR request |
| HTTP 403/429 | Rate limit or bot block | Raise `http.delay_seconds` in `config.json`. Do not rotate user agents or proxies to get around a block. |
| Every lead is NEW each run | `source_id` is not stable | Check what the id is built from |

Fix the cause in the parser, then run `try_source.py` again. Keep the fix
small: the user reads these files.

### TLS problems

Many GCC government sites have weak TLS setups. The project handles this
without turning verification off:

- **Missing intermediate certificate:** add the intermediate PEM to
  `tender_radar/certs/intermediates.pem` (append, keep the existing one). Get
  it from the certificate's "CA Issuers" URL (AIA) and convert it with
  `openssl x509 -inform DER -in ca.crt -out ca.pem` if it is DER.
- **Old ciphers only:** `set_ciphers("DEFAULT")` is already set. If a portal
  needs even older settings, give it its own adapter mounted only on its host.
  Do not weaken TLS for all portals.

Never use `verify=False`. A tender list that a man-in-the-middle could change
is worse than no list.

## Rules for every source

- Use `self.client` (`PoliteClient`) for every request. It waits between
  calls, retries, and has the TLS fixes. A bare `requests.get` skips all that.
- Stop paging when a page returns no new leads or fewer rows than the page
  size. Portals often repeat the last page instead of returning an error.
- Respect `max_pages` from the settings, so the user controls the load.
- Clean text with `" ".join(text.split())`. Portals send `\r\n` and
  non-breaking spaces inside titles.
- Keep Arabic as it is. Do not translate or transliterate. The scorer folds
  Arabic spelling variants itself (`scorer.normalize`).
- Put portal-only fields in `lead.extra` (a dict). Add a new `Lead` field
  only if every portal can fill it and the reports should show it. A new
  field also needs a change in `store.COLUMNS` and an `ALTER TABLE`, because
  `CREATE TABLE IF NOT EXISTS` does not add columns to the existing
  `data/leads.db`.
- Follow the `code-style` skill for code shape.

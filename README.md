# Tender Radar

[![pre-commit](https://github.com/niyazrazak/tender-radar/actions/workflows/pre-commit.yml/badge.svg?branch=main)](https://github.com/niyazrazak/tender-radar/actions/workflows/pre-commit.yml)

Collects public tender / RFQ leads from GCC government procurement portals, keeps only the ones that match what you sell, and gives you a daily list with links.

## Sources

| Portal | Country | What we collect |
|---|---|---|
| Monaqasat (monaqasat.mof.gov.qa) | Qatar | Open, future and awarded tenders, with details (activities, brief, buyer reference) |
| Etimad (tenders.etimad.sa) | Saudi Arabia | Active tenders published in the last week |

Both are public pages. Each portal's robots.txt allows crawling. The tool waits 1 second between requests.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Dashboard (runs all the time)

```bash
.venv/bin/python -m tender_radar install-service   # once
```

Then open http://127.0.0.1:8765.

- The service starts when you log in and restarts if it stops (macOS launchd agent `com.tenderradar.dashboard`).
- It checks every portal every `schedule.interval_hours` (default 6) in `config.json`. If the Mac slept through a check, the check starts within a minute of waking. A failed check retries after 30 minutes.
- After a check, a macOS notification shows the number of relevant new leads and the top titles. It also tells you when a portal or the whole check fails. A check with nothing new shows no notification.
- **Check now** starts a check at once. The dot next to it shows the last result. Click the dot to see recent checks and which portal failed.
- Triage each lead: **Shortlisted**, **Bidding** or **Dismissed**. The tabs filter by this state. Collection never changes it.
- Keys: `j`/`k` move, `Enter` opens, `s` shortlist, `b` bidding, `d` dismiss, `u` back to inbox, `/` search.
- The settings button at the bottom right switches density, title language and light/dark theme.
- The dashboard listens on 127.0.0.1 only. Other computers cannot open it.

```bash
.venv/bin/python -m tender_radar service-status
.venv/bin/python -m tender_radar uninstall-service
.venv/bin/python -m tender_radar serve      # run in the foreground instead
```

Log: `logs/tender-radar.log`. Changes to keywords and sources apply at the next check. Changes to `schedule` need a restart: run `install-service` again.

## Use from the command line

```bash
.venv/bin/python -m tender_radar run              # collect + report
.venv/bin/python -m tender_radar report --days 1  # only leads first seen today
.venv/bin/python -m tender_radar run --sources monaqasat
```

Output:
- `reports/leads-YYYY-MM-DD.html`: open in a browser. Filter by word, country, or "new only".
- `reports/leads-YYYY-MM-DD.xlsx`: same list in Excel.
- `data/leads.db`: every tender ever seen (SQLite).

Titles, buyers, categories and briefs are shown in English, with the Arabic original below. Translations come from Google's free web translator and are cached in `data/leads.db` (table `translations`), so each text is translated once. If Google rate-limits a run, the rest is translated on the next run.

The first run takes about 10 minutes, because it opens every Monaqasat tender once. Later runs open only new tenders.

In Claude Code, ask "show me new tender leads" (skill: `.claude/skills/tender-leads`). Claude runs the tool and translates and summarizes the leads.

## Tune what counts as a lead

Edit `config.json`:
- `strong` keywords score 3, `weak` keywords score 1, and `exclude` keywords score −5.
- A lead shows up when its score is at least `min_score` (default 3).
- Arabic is matched without hamza or ta-marbuta differences, so write `منصه` or `منصة`; both work.

## Add a portal

Write a class in `tender_radar/sources/` with `name` and `collect(known_keys) -> list[Lead]`, and register it in `tender_radar/sources/__init__.py`.

## Notes

- `tender_radar/certs/intermediates.pem` holds DigiCert's public intermediate certificate. Monaqasat does not send it, so Python cannot verify the site without it.

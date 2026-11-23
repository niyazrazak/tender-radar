# Tender Radar

[![pre-commit](https://github.com/niyazrazak/tender-radar/actions/workflows/pre-commit.yml/badge.svg?branch=main)](https://github.com/niyazrazak/tender-radar/actions/workflows/pre-commit.yml)
[![tests](https://github.com/niyazrazak/tender-radar/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/niyazrazak/tender-radar/actions/workflows/tests.yml)

Collects public tender / RFQ leads from GCC government procurement portals, keeps only the ones that match what you sell, and gives you a daily list with links.

## Sources

| Portal | Country | What we collect |
|---|---|---|
| Monaqasat (monaqasat.mof.gov.qa) | Qatar | Open, future and awarded tenders, with details (activities, brief, buyer reference) and award reports (winners, value, every bid) |
| Mwani Qatar (mwani.com.qa) | Qatar | Port tenders, not on Monaqasat |
| Qatar Football Association (qfa.qa) | Qatar | Tenders, not on Monaqasat |
| Sidra Medicine | Qatar | RFQs, RFIs and tenders, not on Monaqasat |
| Etimad (tenders.etimad.sa) | Saudi Arabia | Active tenders published in the last week |
| Oman Tender Board (etendering.tenderboard.gov.om) | Oman | New tenders and tenders with bids opened |
| CAPT (capt.gov.kw) | Kuwait | Open tenders |
| Tender Board (tenderboard.gov.bh) | Bahrain | Current tenders, with details (brief, fee, bond) |

All are public pages that need no login. The tool reads only what each portal's robots.txt allows, and waits 1 second between requests.
Kahramaa, Ashghal, HMC and Qatar Foundation publish on Monaqasat. QatarEnergy, Ooredoo and Qatar Airways need a supplier login, so they are not collected.

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

## AI fit and bid analysis (optional)

Put an Anthropic API key in `.env` (copy `.env.example`), then run `install-service` again:

```bash
cp .env.example .env    # then set ANTHROPIC_API_KEY
```

- **AI fit.** After each check, Claude reads every open tender that hits at least one keyword (`ai.screen_min_score`) and rates the fit with your business from 0 to 10, with a one-line reason. The fit shows next to the keyword score. Sort by **AI fit** to see the best first. A tender with fit `ai.min_fit` (default 6) or more shows up even when its keyword score is low, so tenders written in other words are not missed. Each tender is rated once; at most `ai.max_per_run` (150) a check.
- **Bid / no-bid.** In a lead's panel, **Analyze tender** asks Claude for a recommendation, scope, requirements, key dates, risks and questions for the buyer. **Upload documents…** adds the tender documents (PDF or text) you bought from the portal, for a full analysis. Documents are kept in `data/documents/`.
- **Translation fallback.** When Google rate-limits translation, Claude translates the rest (`ai.translate_fallback`).
- Company profile: `company` in `config.json`. Claude rates against it, so describe what you sell.
- Model: `claude-opus-5-5` (`ai.model`). Without a key, everything else works and the AI parts stay off.

## Alerts by email and Telegram

Set up a channel in `config.json` -> `alerts`, and its secret in `.env`:

- **Email:** set `email.enabled`, `smtp_host`, `smtp_port`, `username`, `to` (a list). Put the password in `TENDER_RADAR_SMTP_PASSWORD`.
- **Telegram:** create a bot with @BotFather, put its token in `TENDER_RADAR_TELEGRAM_TOKEN`, and set `telegram.enabled` and `telegram.chat_id`.

```bash
.venv/bin/python -m tender_radar test-alerts   # sends a test message on each channel
```

What is sent:
- After a check: the new relevant leads. With AI on, leads rated below `alerts.digest_min_fit` are left out.
- Deadline reminders for **Shortlisted** and **Bidding** leads, `alerts.reminder_days` (7, 3, 1) days before the deadline. The deadline is **Our bid deadline** when the team set one, else the portal's closing date. Each reminder is sent once.
- A warning when a portal fails, or returns 0 tenders when it returned some last time (its page probably changed).

## Team work

- Each lead has **Owner**, **Our bid deadline** and **Notes** in its panel. Search finds them too.
- **Market** (key `m`) shows who wins tenders in your field, their win rate and won value, which buyers award them, and recent awards with the bid range. It reads Monaqasat award reports. For tenders stored before award reports were read: `.venv/bin/python -m tender_radar backfill-awards --limit 500`.
- **Shared server:** run it in Docker for the team. Away from localhost, the dashboard requires a password (`TENDER_RADAR_PASSWORD`); it refuses to start without one.

```bash
docker build -t tender-radar .
docker run -d --name tender-radar -p 8765:8765 --env-file .env \
  -v tender-radar-data:/app/data -v tender-radar-reports:/app/reports tender-radar
```

Put it behind HTTPS (a reverse proxy such as Caddy) before you use it over the internet: Basic login sends the password with every request.

## Use from the command line

```bash
.venv/bin/python -m tender_radar run              # collect + report
.venv/bin/python -m tender_radar report --days 1  # only leads first seen today
.venv/bin/python -m tender_radar run --sources monaqasat
.venv/bin/python -m tender_radar screen           # AI-rate leads not rated yet
.venv/bin/python -m tender_radar remind           # send due deadline reminders now
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

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

The tests run offline. Each portal parser runs against real responses recorded in `tests/fixtures/`, and the AI module against a local stand-in for the Claude API. When a portal changes its pages, fix the parser, then record it again: `.venv/bin/python -m tests.recorder <source>`. A new source needs an entry in `RECORD_SETTINGS` in `tests/recorder.py`.

## Notes

- `tender_radar/certs/intermediates.pem` holds DigiCert's public intermediate certificate. Monaqasat does not send it, so Python cannot verify the site without it.

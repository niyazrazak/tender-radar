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
| WOQOD (woqod.com) | Qatar | Open tenders with fee and bond, not on Monaqasat |
| QAFCO (qafco.qa) | Qatar | RFQs with fee, bond and dates from each RFQ's PDF, not on Monaqasat |
| Gulf Times newspaper (gulf-times.com/pdfs) | Qatar | Tender adverts printed in the daily paper (e.g. Qatar Foundation, QAPCO), read by Claude from the page images. Needs AI (Claude Code login or API key) |
| Etimad (tenders.etimad.sa) | Saudi Arabia | Active tenders published in the last week |
| Oman Tender Board (etendering.tenderboard.gov.om) | Oman | New tenders and tenders with bids opened |
| CAPT (capt.gov.kw) | Kuwait | Open tenders |
| Tender Board (tenderboard.gov.bh) | Bahrain | Current tenders, with details (brief, fee, bond) |

All are public pages that need no login. The tool reads only what each portal's robots.txt allows, and waits 1 second between requests.
Kahramaa, Ashghal, HMC and Qatar Foundation publish on Monaqasat. QatarEnergy, Ooredoo, Qatar Airways, Barwa and Msheireb Properties send tenders only to registered suppliers, so they are not collected: register on their supplier portals to receive them.

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

No API key is needed. When Claude Code is installed and logged in with your Claude subscription, the tool runs it in the background (`claude -p`, no tools) for the AI parts. Check with `claude` in a terminal once, then run `install-service` again.

To use the API instead, put a key in `.env` (copy `.env.example`). With a key set, the API is used first. `ai.backend` forces one: `auto` (default), `api` or `cli`.

- `ai.cli_model`: model for the CLI, for example `opus` or `sonnet`. Empty uses the CLI's default.
- `ai.claude_path`: where `claude` is, when it is not in `~/.local/bin`, `/opt/homebrew/bin` or `/usr/local/bin`.
- CLI calls count against your subscription's usage limits. A check screens at most `ai.max_per_run` leads, 10 per call.
- With the CLI, uploaded documents go in a temporary folder that Claude may read, and nothing else. Claude sees PDF pages as images, so scanned PDFs work too.

- **AI fit.** After each check, Claude reads every open tender that hits at least one keyword (`ai.screen_min_score`) and rates the fit with your business from 0 to 10, with a one-line reason. The fit shows next to the keyword score. Sort by **AI fit** to see the best first. A tender with fit `ai.min_fit` (default 6) or more shows up even when its keyword score is low, so tenders written in other words are not missed. Each tender is rated once; at most `ai.max_per_run` (150) a check.
- **Bid / no-bid.** In a lead's panel, **Analyze tender** asks Claude for a recommendation, scope, requirements, key dates, risks and questions for the buyer. **Upload documents…** adds the tender documents (PDF or text) you bought from the portal, for a full analysis. Documents are kept in `data/documents/`.
- **Translation fallback.** When Google rate-limits translation, Claude translates the rest (`ai.translate_fallback`).
- Company profile: `company` in `config.json`. Claude rates against it, so describe what you sell.
- API model: `claude-opus-5-5` (`ai.model`). Without a key or a logged-in CLI, everything else works and the AI parts stay off.

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

## Small company mode

For a company that cannot put up large bid bonds or pay many document fees. The **company size** filter shows:

- **Reserved for SMEs:** the tender type says so (Oman's "مؤسسات صغيرة و المتوسطة").
- **Small-value purchase:** Monaqasat "less than QAR 200,000 / 500,000", practices (ممارسة), direct purchases (Etimad شراء مباشر) and RFQs. These usually have a small bond or none.
- **Low up-front cost:** document fee + bid bond, in US dollars, up to `small_company.max_upfront_usd` (default 2000). When the bond is a percent of the bid, or a portal lists no fee or bond, the cost is unknown.
- **Fits a small company:** any of the above, for open tenders only.

Sort by **Lowest up-front cost** to see the cheapest to bid first. Each lead's panel shows its up-front cost and, for Qatar, the Qatar Development Bank SME exemptions to check.

Set `small_company.enabled` to `true` in `config.json` to start the dashboard on **Fits a small company**, and to send only those leads in alert digests.

The **Market** view lists **Partners to approach**: companies that win larger contracts in your field. A small company can offer to deliver the software part as their subcontractor, under their bond and registration.

## Freelancer mode

Most government tenders accept only registered companies. A freelancer gets work another way: from the companies that win.

- **Awarded in the last N days: pitch the winner** (company size filter). Awards in your field with a known winner, newest first. The date is the portal's award date. A company that just won often needs help to deliver.
- In an awarded lead's panel, **Pitch the winner** shows each winner, its commercial registration (CR) number (to look up a contact) and its awarded value. **Draft a pitch** asks Claude for a short first message that offers your services for that contract (needs the API key).
- **Open to freelancers:** open tenders for licensed freelancers (Oman's tender type "صاحب عمل حر").

Settings in `config.json` -> `freelancer`:
- `profile`: your skills and experience, used in pitches (falls back to `company`).
- `award_days`: how recent an award counts as new (default 30).
- `enabled`: start the dashboard on fresh awards, and send an alert after each check that lists awards new to the tool in your field.

Awards come from Monaqasat award reports. Winners stored before CR numbers were read show no CR.

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

---
name: tender-leads
description: Collect and review tender / RFQ leads from Qatar (Monaqasat) and Saudi (Etimad) government portals. Use when the user asks for new tenders, RFQs, leads, opportunities, or "what's new on Monaqasat/Etimad".
---

# Tender leads

The project collects public tenders, scores them against keywords in `config.json`, and keeps them in `data/leads.db`.

## Steps

1. Collect fresh leads (1–2 min after the first run):
   `.venv/bin/python -m tender_radar run --days 1 --json`
   - Use `report` instead of `run` to skip collecting and only read the database.
   - `--days N` limits to leads first seen in the last N days. `--min-score N` changes the cut-off.
   - `--sources monaqasat` collects only one portal.
2. Read the JSON. Most titles are Arabic. For each lead give the user:
   - English title (translate), buyer, country, closing date, days left, document fee.
   - One line on why it fits a software company, or "weak fit" if the keyword hit looks accidental.
   - The link.
3. Sort: closing soonest first among strong fits. Put weak fits and `awarded` items (subcontracting leads: contact the winner) in separate short lists.
4. If many irrelevant leads score high, suggest which words to add to `exclude` in `config.json`. If a clear fit was missed, suggest words for `strong`.

Do not draft quotations unless asked. Phase 1 is finding leads.

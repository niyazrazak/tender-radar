"""Run one source and the scorer without writing to data/leads.db.

Use it after you add or fix a source, to check its leads before a real run.

    .venv/bin/python .claude/skills/tender-portal/scripts/try_source.py NAME [--pages N] [--details] [--show N]
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT))

from tender_radar.http_client import PoliteClient  # noqa: E402
from tender_radar.scorer import KeywordScorer  # noqa: E402
from tender_radar.sources import SOURCES  # noqa: E402

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main():
    args = _parse_args()
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    settings = {
        **config["sources"].get(args.name, {}),
        "max_pages": args.pages, "awarded_pages": 1, "in_process_pages": 1,
    }
    settings["fetch_details"] = args.details
    http = config.get("http", {})
    client = PoliteClient(http.get("delay_seconds", 1.0), http.get("timeout_seconds", 30))
    source = SOURCES[args.name]
    if hasattr(source, "own_client"):  # Upwork needs its own browser-like client, as in cli
        client = source.own_client(client.delay)

    leads = source(client, settings).collect({})
    scorer = KeywordScorer(config["keywords"])
    for lead in leads:
        scorer.score(lead)

    for lead in sorted(leads, key=lambda lead: -lead.score)[: args.show]:
        print(json.dumps(lead.to_dict(), ensure_ascii=False, indent=1))
    _report_problems(leads)


def _report_problems(leads):
    keys = [lead.key for lead in leads]
    problems = []
    if not leads:
        problems.append("no leads at all")
    if len(keys) != len(set(keys)):
        problems.append(f"{len(keys) - len(set(keys))} duplicate keys")
    for field in ("published", "closing"):
        bad = [lead.key for lead in leads if getattr(lead, field) and not ISO_DATE.match(getattr(lead, field))]
        if bad:
            problems.append(f"{len(bad)} leads with non-ISO {field}, e.g. {bad[0]}")
    for field in ("source_id", "title", "url"):
        empty = sum(1 for lead in leads if not getattr(lead, field))
        if empty:
            problems.append(f"{empty} leads with empty {field}")
    for field in ("buyer", "closing", "category"):
        empty = sum(1 for lead in leads if not getattr(lead, field))
        if leads and empty == len(leads):
            problems.append(f"{field} is empty on every lead (label or selector wrong?)")

    scored = sum(1 for lead in leads if lead.score > 0)
    print(f"\n{len(leads)} leads, {scored} with score > 0.")
    print("Problems:\n- " + "\n- ".join(problems) if problems else "No problems found.")


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(SOURCES))
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--details", action="store_true", help="Also fetch detail pages (slower)")
    parser.add_argument("--show", type=int, default=3, help="How many leads to print")
    return parser.parse_args()


if __name__ == "__main__":
    main()

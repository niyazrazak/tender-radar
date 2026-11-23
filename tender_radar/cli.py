import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tender_radar.http_client import PoliteClient
from tender_radar.report import LeadReport
from tender_radar.scorer import KeywordScorer
from tender_radar.sources import SOURCES
from tender_radar.store import LeadStore
from tender_radar.translator import Translator

ROOT = Path(__file__).resolve().parent.parent
TRANSLATED_FIELDS = ("title", "buyer", "category", "activities", "brief")


class TenderRadar:
    """Collects leads from every enabled portal, scores them, stores them and reports."""

    def __init__(self, config_path: Path):
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        http = self.config.get("http", {})
        self.client = PoliteClient(http.get("delay_seconds", 1.0), http.get("timeout_seconds", 30))
        self.scorer = KeywordScorer(self.config["keywords"])
        self.store = LeadStore(ROOT / "data" / "leads.db")
        self.translator = Translator(self.store.db)

    def collect(self, only: list[str]) -> dict:
        """Returns {"new_keys", "total", "new", "sources": {name: {"ok", "count", "error"}}}."""
        known = self.store.known_keys()
        leads, sources = [], {}
        for name, settings in self.config["sources"].items():
            if not settings.get("enabled") or (only and name not in only):
                continue
            print(f"Collecting {name} …", flush=True)
            try:
                found = SOURCES[name](self.client, settings).collect(known)
                leads += found
                sources[name] = {"ok": True, "count": len(found), "error": ""}
            except Exception as error:  # a broken portal must not stop the others
                print(f"  ! {name} failed: {error}", flush=True)
                sources[name] = {"ok": False, "count": 0, "error": str(error)[:300]}
        self.store.restore_details(leads)
        for lead in leads:
            self.scorer.score(lead)
        new_count = self.store.save(leads)
        print(f"Saved {len(leads)} tenders, {new_count} new.", flush=True)
        new_keys = {lead.key for lead in leads if lead.key not in known}
        return {"new_keys": new_keys, "total": len(leads), "new": new_count, "sources": sources}

    def report(self, min_score: int, days: int, new_keys: set) -> list[dict]:
        since = ""
        if days:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        leads = self.store.query(min_score, since, countries=self.config.get("focus_countries", []))
        self._add_english(leads)
        html_path, xlsx_path = LeadReport(ROOT / "reports").write(leads, new_keys)
        print(f"{len(leads)} relevant leads (score >= {min_score}).")
        print(f"Report: {html_path}\nExcel:  {xlsx_path}")
        return leads

    def _add_english(self, leads: list[dict]):
        """Adds <field>_en for the Arabic fields people read. Cached, so only new text is translated."""
        # Field by field, so titles are done before long briefs use up the rate limit.
        for field in TRANSLATED_FIELDS:
            self.translator.translate_many(lead[field] for lead in leads)
            for lead in leads:
                lead[f"{field}_en"] = self.translator.cached(lead[field])

    def translate_all(self) -> int:
        """Every readable field of every stored tender, so 'all tenders' in the dashboard is English too."""
        added = 0
        for field in TRANSLATED_FIELDS:  # titles first: long briefs are most likely to hit the rate limit
            rows = self.store.db.execute(f"SELECT {field} FROM leads")
            added += self.translator.translate_many(row[0] for row in rows)
        print(f"Translated {added} new texts (titles, buyers, categories, activities, briefs).", flush=True)
        return added


def main():
    args = _parse_args()
    if args.command in SERVICE_COMMANDS:
        SERVICE_COMMANDS[args.command](Path(args.config))
        return
    radar = TenderRadar(Path(args.config))
    min_score = args.min_score if args.min_score is not None else radar.config.get("min_score", 3)
    new_keys = set()
    if args.command == "rescore":
        print(f"Rescored {radar.store.rescore(radar.scorer)} stored tenders.")
    if args.command in ("run", "collect"):
        new_keys = radar.collect(args.sources.split(",") if args.sources else [])["new_keys"]
    if args.command in ("run", "report", "rescore"):
        leads = radar.report(min_score, args.days, new_keys)
        if args.json:
            print(json.dumps(leads, ensure_ascii=False, indent=1))
    if args.command in ("run", "translate"):
        radar.translate_all()


def _serve(config_path: Path):
    from tender_radar.web import serve
    serve(config_path)


def _service(action: str):
    def run(config_path: Path):
        from tender_radar import service
        getattr(service, action)(config_path)
    return run


SERVICE_COMMANDS = {
    "serve": _serve,
    "install-service": _service("install"),
    "uninstall-service": _service("uninstall"),
    "service-status": _service("status"),
}


def _parse_args():
    parser = argparse.ArgumentParser(prog="tender_radar", description="Collect tender/RFQ leads.")
    commands = ["run", "collect", "report", "rescore", "translate", *SERVICE_COMMANDS]
    parser.add_argument("command", choices=commands, nargs="?", default="run")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--sources", help="Comma list, e.g. monaqasat,etimad")
    parser.add_argument("--min-score", type=int)
    parser.add_argument("--days", type=int, default=0, help="Only leads first seen in the last N days")
    parser.add_argument("--json", action="store_true", help="Also print leads as JSON")
    return parser.parse_args()

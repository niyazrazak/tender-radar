import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tender_radar.ai import LeadAnalyst
from tender_radar.http_client import PoliteClient
from tender_radar.lead import Lead
from tender_radar.report import LeadReport
from tender_radar.runs import RunLog
from tender_radar.scorer import KeywordScorer
from tender_radar.sources import SOURCES
from tender_radar.store import COLUMNS, LeadStore
from tender_radar.translator import Translator

ROOT = Path(__file__).resolve().parent.parent
TRANSLATED_FIELDS = ("title", "buyer", "category", "activities", "brief")
DEFAULT_MIN_FIT = 6


class TenderRadar:
    """Collects leads from every enabled portal, scores them, stores them and reports."""

    def __init__(self, config_path: Path):
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        http = self.config.get("http", {})
        self.client = PoliteClient(http.get("delay_seconds", 1.0), http.get("timeout_seconds", 30))
        self.scorer = KeywordScorer(self.config["keywords"])
        self.store = LeadStore(ROOT / "data" / "leads.db")
        self.ai_settings = self.config.get("ai", {})
        self.analyst = LeadAnalyst(self.config) if LeadAnalyst.available(self.config) else None
        use_claude = self.analyst and self.ai_settings.get("translate_fallback", True)
        self.translator = Translator(self.store.db, fallback=self.analyst.translate if use_claude else None)

    @property
    def min_fit(self) -> int:
        return self.ai_settings.get("min_fit", DEFAULT_MIN_FIT)

    def collect(self, only: list[str]) -> dict:
        """Returns {"new_keys", "total", "new", "sources": {name: {"ok", "count", "error"}}}."""
        known = self.store.known_keys()
        previous = RunLog(self.store.db).last_counts()
        leads, sources = [], {}
        for name, settings in self.config["sources"].items():
            if not settings.get("enabled") or (only and name not in only):
                continue
            print(f"Collecting {name} …", flush=True)
            try:
                found = SOURCES[name](self.client, settings).collect(known)
                leads += found
                sources[name] = {"ok": True, "count": len(found), "error": ""}
                if not found and previous.get(name):
                    # A portal that answers but lists nothing usually changed its page, and the parser broke.
                    sources[name] = {"ok": False, "count": 0, "error": _empty_warning(previous[name])}
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
        countries = self.config.get("focus_countries", [])
        leads = self.store.query(min_score, since, countries=countries, min_fit=self.min_fit)
        self._add_english(leads)
        html_path, xlsx_path = LeadReport(ROOT / "reports").write(leads, new_keys)
        print(f"{len(leads)} relevant leads (score >= {min_score}).")
        print(f"Report: {html_path}\nExcel:  {xlsx_path}")
        return leads

    def screen(self) -> int:
        """Claude rates open leads it has not rated yet. Returns how many it rated; 0 when AI is off."""
        if not self.analyst:
            return 0
        settings = self.ai_settings
        leads = self.store.unscreened(settings.get("screen_min_score", 1), settings.get("max_per_run", 150))
        if not leads:
            return 0
        print(f"AI screening {len(leads)} leads …", flush=True)
        self._add_english(leads)
        rated = self.analyst.screen(leads)
        for key, fit, reason in rated:
            self.store.set_ai_fit(key, fit, reason)
        print(f"AI rated {len(rated)} leads.", flush=True)
        return len(rated)

    def analyze(self, key: str, documents: list[tuple[str, bytes]]) -> dict:
        """Bid / no-bid analysis of one lead, stored with the lead."""
        if not self.analyst:
            raise ValueError("AI is off. Set ANTHROPIC_API_KEY and restart the service.")
        lead = self.store.get(key)
        if not lead:
            raise ValueError(f"Unknown lead: {key}")
        self._add_english([lead])
        analysis = self.analyst.analyze(lead, documents)
        self.store.set_ai_analysis(key, analysis)
        return analysis

    def backfill_awards(self, limit: int) -> int:
        """Reads award reports for stored Monaqasat tenders that were already awarded when first seen."""
        from tender_radar.sources.monaqasat import MonaqasatSource

        source = MonaqasatSource(self.client, self.config["sources"].get("monaqasat", {}))
        rows = self.store.awarded_without_report("monaqasat", limit)
        print(f"Reading {len(rows)} award reports …", flush=True)
        for row in rows:
            lead = Lead(**{c: row[c] for c in COLUMNS})
            source.add_award(lead)
            if "award_report" in lead.extra:
                self.store.set_extra(lead.key, lead.extra)
        return len(rows)

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


def load_env(path: Path):
    """KEY=value lines from .env into the environment. The launchd service does not get shell variables,
    so secrets (ANTHROPIC_API_KEY, SMTP password, Telegram token) live in this git-ignored file."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name and not name.startswith("#"):
            os.environ.setdefault(name.strip().removeprefix("export "), value.strip().strip("'\""))


def main():
    load_env(ROOT / ".env")
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
    if args.command in ("run", "screen"):
        radar.screen()
    if args.command in ("run", "report", "rescore"):
        leads = radar.report(min_score, args.days, new_keys)
        if args.json:
            print(json.dumps(leads, ensure_ascii=False, indent=1))
    if args.command in ("run", "translate"):
        radar.translate_all()
    if args.command == "backfill-awards":
        print(f"Checked {radar.backfill_awards(args.limit)} awarded tenders.")
    if args.command == "test-alerts":
        from tender_radar.alerts import Alerts
        print("\n".join(Alerts(radar.config).test()))
    if args.command == "remind":
        from tender_radar.alerts import Alerts
        print(f"Sent {Alerts(radar.config).send_reminders(radar.store)} deadline reminders.")


def _empty_warning(last_count: int) -> str:
    return f"returned 0 tenders (last time {last_count}); the portal page may have changed"


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
    commands = [
        "run", "collect", "report", "rescore", "translate", "screen", "backfill-awards", "test-alerts", "remind",
        *SERVICE_COMMANDS,
    ]
    parser.add_argument("command", choices=commands, nargs="?", default="run")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--sources", help="Comma list, e.g. monaqasat,etimad")
    parser.add_argument("--min-score", type=int)
    parser.add_argument("--days", type=int, default=0, help="Only leads first seen in the last N days")
    parser.add_argument("--json", action="store_true", help="Also print leads as JSON")
    parser.add_argument("--limit", type=int, default=200, help="backfill-awards: how many tenders to read")
    return parser.parse_args()

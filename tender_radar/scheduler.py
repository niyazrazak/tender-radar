import threading
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tender_radar.cli import ROOT, TenderRadar
from tender_radar.alerts import Alerts
from tender_radar.runs import RunLog, parse_utc
from tender_radar.store import LeadStore

TICK_SECONDS = 60
RETRY_AFTER_ERROR = timedelta(minutes=30)


class Scheduler:
    """Runs a collection every `interval_hours` in a background thread.

    It checks the wall clock every minute instead of sleeping for the whole interval,
    so a run missed while the Mac slept starts within a minute of waking.
    """

    def __init__(self, config_path: Path, interval_hours: float):
        self.config_path = config_path
        self.interval = timedelta(hours=interval_hours)
        self._wake = threading.Event()
        self._state = threading.Lock()
        self._running_since = None
        self._manual = False
        runs = RunLog(LeadStore(ROOT / "data" / "leads.db").db)
        runs.close_interrupted()
        self._last = runs.last()

    def start(self):
        threading.Thread(target=self._loop, name="scheduler", daemon=True).start()

    def request_run(self) -> bool:
        """Starts a run now. False if one is already running."""
        with self._state:
            if self._running_since:
                return False
            self._manual = True
        self._wake.set()
        return True

    def status(self) -> dict:
        with self._state:
            return {
                "running": self._running_since is not None,
                "running_since": self._running_since,
                "next_run": self._next_run().strftime("%Y-%m-%d %H:%M:%S"),
                "interval_hours": self.interval.total_seconds() / 3600,
            }

    def _loop(self):
        while True:
            with self._state:
                trigger = "manual" if self._manual else "schedule" if self._due() else None
                if trigger:
                    self._manual = False
                    self._running_since = _now().strftime("%Y-%m-%d %H:%M:%S")
            if trigger:
                self._run(trigger)
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    def _run(self, trigger: str):
        print(f"[{_now():%Y-%m-%d %H:%M}] {trigger} run started", flush=True)
        radar = TenderRadar(self.config_path)  # fresh each run, so config edits apply without a restart
        runs = RunLog(radar.store.db)
        run_id = runs.start(trigger)
        result, error, new_leads = {}, "", []
        try:
            result = radar.collect([])
            radar.screen()  # before the report, so the digest can use the AI fit
            leads = radar.report(radar.config.get("min_score", 3), 0, result["new_keys"])
            new_leads = [lead for lead in leads if lead["key"] in result["new_keys"]]
            radar.translate_all()
        except Exception as exc:
            traceback.print_exc()
            error = str(exc)[:500]
        runs.finish(run_id, result, error)
        alerts = Alerts(radar.config)
        try:
            alerts.run_finished(new_leads, result, error)
            alerts.send_reminders(radar.store)  # also after a failed check: deadlines do not wait
        except Exception:
            traceback.print_exc()
        with self._state:
            self._last = runs.last()
            self._running_since = None

    def _due(self) -> bool:
        return not self._last or _now() >= self._next_run()

    def _next_run(self) -> datetime:
        if not self._last:
            return _now()
        wait = RETRY_AFTER_ERROR if self._last["status"] in ("error", "interrupted") else self.interval
        return parse_utc(self._last["started"]) + wait


def _now() -> datetime:
    return datetime.now(timezone.utc)

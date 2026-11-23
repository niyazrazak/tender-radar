import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tender_radar.cli import ROOT, TRANSLATED_FIELDS
from tender_radar.runs import RunLog
from tender_radar.scheduler import Scheduler
from tender_radar.store import LeadStore
from tender_radar.translator import Translator

STATIC = Path(__file__).parent / "static"
DEFAULT_PORT = 8765


def serve(config_path: Path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    settings = config.get("schedule", {})
    scheduler = Scheduler(config_path, settings.get("interval_hours", 6))
    scheduler.start()
    port = settings.get("port", DEFAULT_PORT)
    # Localhost only: the dashboard has no login.
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(config_path, scheduler))
    print(f"Tender Radar dashboard: http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


def _handler(config_path: Path, scheduler: Scheduler):
    class Handler(DashboardHandler):
        pass

    Handler.config_path = config_path
    Handler.scheduler = scheduler
    return Handler


class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the dashboard page and its JSON API.

    Each request opens its own SQLite connection, because connections cannot cross threads.
    """

    config_path: Path
    scheduler: Scheduler

    def do_GET(self):
        url = urlparse(self.path)
        routes = {"/api/leads": self._leads, "/api/status": self._status, "/api/export": self._export}
        if url.path in routes:
            return self._safely(routes[url.path], parse_qs(url.query))
        self._static(url.path)

    def do_POST(self):
        routes = {"/api/run": self._run, "/api/lead-status": self._lead_status}
        path = urlparse(self.path).path
        # A JSON content type forces a CORS preflight, which we never answer, so other sites cannot post here.
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"error": "JSON only"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        if path not in routes:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._safely(routes[path], self._body())

    def _leads(self, query: dict):
        config = self._config()
        min_score = config.get("min_score", 3) if _first(query, "scope") != "all" else -999
        store = _store()
        leads = store.query(min_score, include_closed=_first(query, "closed") == "1")
        translator = Translator(store.db)
        for lead in leads:
            for field in TRANSLATED_FIELDS:
                lead[f"{field}_en"] = translator.cached(lead[field])
        self._json({
            "leads": leads,
            "min_score": config.get("min_score", 3),
            "focus_countries": config.get("focus_countries", []),
        })

    def _status(self, _query: dict):
        store = _store()
        counts = store.db.execute(
            "SELECT source, country, COUNT(*) AS total FROM leads GROUP BY source, country"
        ).fetchall()
        self._json({
            "scheduler": self.scheduler.status(),
            "runs": RunLog(store.db).recent(8),
            "sources": [dict(row) for row in counts],
            "company": self._config().get("company", ""),
        })

    def _run(self, _body: dict):
        started = self.scheduler.request_run()
        self._json({"started": started}, HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT)

    def _lead_status(self, body: dict):
        if not _store().set_lead_status(str(body.get("key", "")), str(body.get("status", ""))):
            return self._json({"error": "lead not found"}, HTTPStatus.NOT_FOUND)
        self._json({"ok": True})

    def _export(self, _query: dict):
        reports = sorted((ROOT / "reports").glob("leads-*.xlsx"))
        if not reports:
            return self._json({"error": "no report yet; run a check first"}, HTTPStatus.NOT_FOUND)
        self._file(reports[-1], download=True)

    def _static(self, path: str):
        target = (STATIC / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._file(target)

    def _safely(self, route, arg):
        try:
            route(arg)
        except ValueError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:  # keep serving; the page shows the message
            self._json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _config(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _json(self, data: dict, status: HTTPStatus = HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(payload, "application/json; charset=utf-8", status)

    def _file(self, path: Path, download: bool = False):
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith("javascript"):
            kind += "; charset=utf-8"
        headers = {"Content-Disposition": f'attachment; filename="{path.name}"'} if download else {}
        self._send(path.read_bytes(), kind, HTTPStatus.OK, headers)

    def _send(self, payload: bytes, kind: str, status: HTTPStatus, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass  # the dashboard polls every few seconds; per-request lines would flood the log


def _store() -> LeadStore:
    return LeadStore(ROOT / "data" / "leads.db")


def _first(query: dict, name: str) -> str:
    return (query.get(name) or [""])[0]

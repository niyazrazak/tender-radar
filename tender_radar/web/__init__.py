import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tender_radar.ai import LeadAnalyst
from tender_radar.cli import COMPANY, DEFAULT_MIN_FIT, ROOT, TRANSLATED_FIELDS, TenderRadar
from tender_radar.company import CompanyProfile
from tender_radar.market import add_company_english, add_report_english, market_report
from tender_radar.runs import RunLog
from tender_radar.small_company import DEFAULT_MAX_UPFRONT_USD, assess
from tender_radar.scheduler import Scheduler
from tender_radar.store import LeadStore
from tender_radar.translator import Translator

STATIC = Path(__file__).parent / "static"
DOCUMENTS = ROOT / "data" / "documents"
DEFAULT_PORT = 8765
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
MAX_BODY = 60 * 1024 * 1024  # tender documents are uploaded as base64 JSON
DOCUMENT_TYPES = (".pdf", ".txt", ".md")
SAFE_NAME = re.compile(r"[^\w.\- ]+")


def serve(config_path: Path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    settings = config.get("schedule", {})
    scheduler = Scheduler(config_path, settings.get("interval_hours", 6))
    scheduler.start()
    port = settings.get("port", DEFAULT_PORT)
    host, password = _listen_settings(config.get("server", {}))
    server = ThreadingHTTPServer((host, port), _handler(config_path, scheduler, password))
    print(f"Tender Radar dashboard: http://{host}:{port}{' (login required)' if password else ''}", flush=True)
    server.serve_forever()


def _listen_settings(settings: dict) -> tuple[str, str]:
    """Localhost needs no login. Any other address (a shared server) refuses to start without a password."""
    host = os.environ.get("TENDER_RADAR_HOST") or settings.get("host", "127.0.0.1")
    password = os.environ.get(settings.get("password_env", "TENDER_RADAR_PASSWORD"), "")
    if host not in LOCAL_HOSTS and not password:
        raise SystemExit(
            f"server.host is {host}, so other computers can reach the dashboard. "
            f"Set a password in ${settings.get('password_env', 'TENDER_RADAR_PASSWORD')} first."
        )
    return host, password


def _handler(config_path: Path, scheduler: Scheduler, password: str = ""):
    class Handler(DashboardHandler):
        pass

    Handler.config_path = config_path
    Handler.scheduler = scheduler
    Handler.password = password
    return Handler


class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the dashboard page and its JSON API.

    Each request opens its own SQLite connection, because connections cannot cross threads.
    """

    config_path: Path
    scheduler: Scheduler
    password: str = ""

    def do_GET(self):
        if not self._authorized():
            return
        url = urlparse(self.path)
        routes = {
            "/api/leads": self._leads, "/api/status": self._status, "/api/export": self._export,
            "/api/market": self._market, "/api/company": self._company,
        }
        if url.path == "/api/company-document":
            return self._safely(self._company_document, parse_qs(url.query))
        if url.path in routes:
            return self._safely(routes[url.path], parse_qs(url.query))
        self._static(url.path)

    def do_POST(self):
        if not self._authorized():
            return
        routes = {
            "/api/run": self._run, "/api/lead-status": self._lead_status, "/api/lead-update": self._lead_update,
            "/api/analyze": self._analyze, "/api/pitch": self._pitch,
            "/api/company": self._company_save, "/api/company-upload": self._company_upload,
            "/api/company-document": self._company_document_update, "/api/company-read": self._company_read,
        }
        path = urlparse(self.path).path
        # A JSON content type forces a CORS preflight, which we never answer, so other sites cannot post here.
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"error": "JSON only"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        if path not in routes:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if int(self.headers.get("Content-Length") or 0) > MAX_BODY:
            return self._json({"error": "upload too large (60 MB at most)"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self._safely(routes[path], self._body())

    def _authorized(self) -> bool:
        """HTTP Basic login when a password is set (any user name). The browser remembers it."""
        if not self.password:
            return True
        header = self.headers.get("Authorization", "")
        try:
            given = base64.b64decode(header.removeprefix("Basic ")).decode().partition(":")[2]
        except ValueError:
            given = ""
        if header.startswith("Basic ") and hmac.compare_digest(given.encode(), self.password.encode()):
            return True
        self._send(b"Login required", "text/plain", HTTPStatus.UNAUTHORIZED,
                   {"WWW-Authenticate": 'Basic realm="Tender Radar", charset="UTF-8"'})
        return False

    def _leads(self, query: dict):
        config = self._config()
        min_score = config.get("min_score", 3) if _first(query, "scope") != "all" else -999
        store = _store()
        min_fit = config.get("ai", {}).get("min_fit", DEFAULT_MIN_FIT) if min_score > -999 else None
        leads = store.query(min_score, include_closed=_first(query, "closed") == "1", min_fit=min_fit)
        translator = Translator(store.db)
        small = config.get("small_company", {})
        max_upfront = small.get("max_upfront_usd", DEFAULT_MAX_UPFRONT_USD)
        for lead in leads:
            for field in TRANSLATED_FIELDS:
                lead[f"{field}_en"] = translator.cached(lead[field])
            add_company_english(lead["extra"], translator.cached)
            lead["small"] = assess(lead, max_upfront)
        self._json({
            "small_company": {"enabled": bool(small.get("enabled")), "max_upfront_usd": max_upfront},
            "freelancer": {
                "enabled": bool(config.get("freelancer", {}).get("enabled")),
                "award_days": config.get("freelancer", {}).get("award_days", 30),
            },
            "leads": leads,
            "min_score": config.get("min_score", 3),
            "focus_countries": config.get("focus_countries", []),
            "ai_enabled": LeadAnalyst.available(config),
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
            "company": self._profile().display_name(),
            "ai_enabled": LeadAnalyst.available(self._config()),
        })

    def _market(self, _query: dict):
        store = _store()
        leads = store.query(-999, include_closed=True)
        translator = Translator(store.db)
        for lead in leads:
            lead["title_en"], lead["buyer_en"] = translator.cached(lead["title"]), translator.cached(lead["buyer"])
        report = market_report(leads, self._config().get("min_score", 3))
        add_report_english(report, translator.cached)
        report["awarded_total"] = store.db.execute("SELECT COUNT(*) FROM leads WHERE status = 'awarded'").fetchone()[0]
        self._json(report)

    def _lead_update(self, body: dict):
        if not _store().set_team_fields(str(body.get("key", "")), body):
            return self._json({"error": "lead not found"}, HTTPStatus.NOT_FOUND)
        self._json({"ok": True})

    def _analyze(self, body: dict):
        """Saves uploaded tender documents next to the lead, then asks Claude for a bid / no-bid analysis."""
        key = str(body.get("key", ""))
        folder = DOCUMENTS / hashlib.sha1(key.encode()).hexdigest()[:16]
        for upload in body.get("files", []):
            name = SAFE_NAME.sub("_", Path(str(upload.get("name", ""))).name).strip() or "document.pdf"
            if not name.lower().endswith(DOCUMENT_TYPES):
                raise ValueError(f"{name}: only PDF and text files can be read")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(base64.b64decode(upload.get("data", "")))
        documents = sorted((path.name, path.read_bytes()) for path in folder.glob("*")) if folder.is_dir() else []
        analysis = TenderRadar(self.config_path).analyze(key, documents)
        self._json({"analysis": analysis})

    def _pitch(self, body: dict):
        pitch = TenderRadar(self.config_path).pitch(str(body.get("key", "")))
        self._json({"pitch": pitch})

    def _company(self, _query: dict):
        self._json(self._profile().load() | {"ai_enabled": LeadAnalyst.available(self._config())})

    def _company_save(self, body: dict):
        self._json(self._profile().save_details(body.get("details") or {}))

    def _company_upload(self, body: dict):
        profile = self._profile()
        for upload in body.get("files", []):
            profile.add_document(str(upload.get("name", "")), base64.b64decode(upload.get("data", "")))
        self._json(profile.load())

    def _company_document(self, query: dict):
        self._file(self._profile().document_path(_first(query, "name")))

    def _company_document_update(self, body: dict):
        """Changes a document's kind or its attach flag, or removes it."""
        profile, name = self._profile(), str(body.get("name", ""))
        if body.get("remove"):
            profile.remove_document(name)
        else:
            profile.update_document(name, body.get("kind"), body.get("attach"))
        self._json(profile.load())

    def _company_read(self, _body: dict):
        self._json({"details": TenderRadar(self.config_path).read_company_documents()})

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

    def _profile(self) -> CompanyProfile:
        return CompanyProfile(COMPANY, self._config().get("company", ""))

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

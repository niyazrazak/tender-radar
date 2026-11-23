"""The AI module against a local stand-in for the Messages API: checks what we send and how we read answers."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tender_radar.ai import MODEL, LeadAnalyst


class StubAPI:
    def __init__(self):
        self.requests, self.replies = [], []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                payload = json.dumps(stub.replies.pop(0)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def reply(self, data: dict, stop_reason="end_turn"):
        self.replies.append({
            "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL,
            "content": [{"type": "text", "text": json.dumps(data)}] if stop_reason != "refusal" else [],
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10},
        })


@pytest.fixture
def api(monkeypatch):
    stub = StubAPI()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", stub.url)
    yield stub
    stub.server.shutdown()


def lead(key, title):
    return {"key": key, "title": title, "buyer": "وزارة", "buyer_en": "Ministry", "country": "Qatar", "status": "open"}


def test_screen_sends_the_profile_and_reads_fits(api):
    api.reply({"results": [
        {"index": 0, "fit": 9, "reason": "ERP rollout"}, {"index": 1, "fit": 1, "reason": "Catering"},
    ]})
    analyst = LeadAnalyst({"company": "ERP house", "ai": {}})
    rated = analyst.screen([lead("a", "ERP implementation"), lead("b", "Catering services")])
    assert rated == [("a", 9, "ERP rollout"), ("b", 1, "Catering")]
    sent = api.requests[0]
    assert sent["body"]["model"] == MODEL
    assert sent["body"]["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in sent["headers"].get("anthropic-beta", "")
    assert "ERP house" in sent["body"]["system"]
    assert sent["body"]["output_config"]["format"]["type"] == "json_schema"
    assert "[1] Catering services" in sent["body"]["messages"][0]["content"]


def test_refused_batch_is_skipped_not_fatal(api):
    api.reply({}, stop_reason="refusal")
    assert LeadAnalyst({"ai": {}}).screen([lead("a", "x")]) == []


def test_out_of_range_index_is_ignored(api):
    api.reply({"results": [{"index": 5, "fit": 9, "reason": "?"}]})
    assert LeadAnalyst({"ai": {}}).screen([lead("a", "x")]) == []


def test_analyze_attaches_pdf_documents(api):
    api.reply({
        "recommendation": "bid", "reasoning": "Fits.", "summary": "An ERP.", "scope": ["ERP"], "requirements": [],
        "key_dates": [], "risks": [], "questions": [], "documents_read": True,
    })
    analysis = LeadAnalyst({"ai": {}}).analyze(lead("a", "ERP"), [("rfp.pdf", b"%PDF-1.4 test")])
    assert analysis["recommendation"] == "bid" and analysis["documents"] == ["rfp.pdf"]
    content = api.requests[0]["body"]["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert content[-1]["type"] == "text"


def test_off_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert not LeadAnalyst.available({"ai": {"enabled": True}})

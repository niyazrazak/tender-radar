"""The AI module against a local stand-in for the Messages API: checks what we send and how we read answers."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tender_radar.ai import MODEL, LeadAnalyst
from tender_radar.claude_backends import CliBackend


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


def test_off_without_a_key_or_cli(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(CliBackend, "find", staticmethod(lambda configured="": ""))
    assert not LeadAnalyst.available({"ai": {"enabled": True}})


def test_pitch_names_the_winner_and_uses_the_profile(api):
    api.reply({
        "subject": "Mobile app for your new contract", "message": "Congratulations...", "work_to_offer": ["App"],
    })
    award = lead("a", "Smart portal") | {"extra": {"winners": [{"company": "Alpha Co"}], "award_value": "5,000.00"}}
    pitch = LeadAnalyst({"ai": {}}).pitch(award, "Flutter developer, 6 years")
    assert pitch["subject"] == "Mobile app for your new contract"
    body = api.requests[0]["body"]
    assert "Flutter developer" in body["system"] and "Winner: Alpha Co" in body["messages"][0]["content"]


# A stand-in for `claude -p`: saves its arguments and stdin, prints the reply in the test's FAKE_REPLY.
FAKE_CLI = """#!{python}
import json, os, sys
open(os.environ["FAKE_LOG"], "w").write(json.dumps({{"args": sys.argv[1:], "stdin": sys.stdin.read()}}))
print(os.environ["FAKE_REPLY"])
"""


@pytest.fixture
def cli(monkeypatch, tmp_path):
    script = tmp_path / "claude"
    script.write_text(FAKE_CLI.format(python=sys.executable))
    script.chmod(0o755)
    log = tmp_path / "log.json"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("FAKE_LOG", str(log))

    def reply(data, is_error=False):
        result = data if isinstance(data, str) else json.dumps(data)
        subtype = "error" if is_error else "success"
        monkeypatch.setenv("FAKE_REPLY", json.dumps({"subtype": subtype, "is_error": is_error, "result": result}))

    reply.config = {"company": "ERP house", "ai": {"backend": "cli", "claude_path": str(script)}}
    reply.sent = lambda: json.loads(log.read_text())
    return reply


def test_cli_backend_needs_no_key_and_reads_fits(cli):
    cli({"results": [{"index": 0, "fit": 8, "reason": "ERP rollout"}]})
    assert LeadAnalyst.available(cli.config)
    assert LeadAnalyst(cli.config).screen([lead("a", "ERP implementation")]) == [("a", 8, "ERP rollout")]
    sent = cli.sent()
    assert "ERP house" in sent["args"][sent["args"].index("--system-prompt") + 1]
    assert json.loads(sent["args"][sent["args"].index("--json-schema") + 1])["type"] == "object"
    assert sent["args"][sent["args"].index("--tools") + 1] == ""
    assert "[0] ERP implementation" in sent["stdin"]


def test_cli_backend_gives_documents_as_readable_files(cli):
    cli("```json\n" + json.dumps({
        "recommendation": "consider", "reasoning": "Maybe.", "summary": "An ERP.", "scope": [], "requirements": [],
        "key_dates": [], "risks": [], "questions": [], "documents_read": True,
    }) + "\n```")
    analysis = LeadAnalyst(cli.config).analyze(lead("a", "ERP"), [("../../etc/terms.txt", b"Bond 2 percent")])
    assert analysis["recommendation"] == "consider"
    sent = cli.sent()
    path = sent["stdin"].split("Document file: ")[1].split("\n")[0]
    assert path.endswith("/0-terms.txt") and "/etc/" not in path  # only the base name is kept
    folder = path.rsplit("/", 1)[0]
    assert sent["args"][sent["args"].index("--tools") + 1] == "Read"
    assert sent["args"][sent["args"].index("--allowedTools") + 1] == f"Read({folder}/**)"


def test_cli_error_is_skipped_not_fatal(cli):
    cli("You have hit your usage limit", is_error=True)
    assert LeadAnalyst(cli.config).screen([lead("a", "x")]) == []

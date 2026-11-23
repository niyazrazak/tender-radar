from datetime import date, timedelta

from tender_radar.alerts import Alerts
from tests.conftest import make_lead


class FakeNotifier:
    def __init__(self):
        self.shown = []

    def run_finished(self, *args):
        pass

    def show(self, title, message):
        self.shown.append(title)


class FakeChannel:
    def __init__(self):
        self.sent = []

    def send(self, subject, text, html_body):
        self.sent.append((subject, text))


def alerts(settings=None):
    instance = Alerts({"alerts": settings or {}}, notifier=FakeNotifier())
    instance.channels = [FakeChannel()]
    return instance


def lead_dict(key, fit=None, score=3):
    return {"key": key, "title": key, "url": f"https://x/{key}", "score": score, "ai_fit": fit, "ai_reason": "",
            "buyer": "Ministry", "country": "Qatar", "closing": "2026-12-01"}


def test_digest_drops_leads_the_ai_rated_low():
    sender = alerts({"digest_min_fit": 5})
    sender.run_finished([lead_dict("good", 8), lead_dict("bad", 2), lead_dict("unrated")], {"sources": {}})
    subject, text = sender.channels[0].sent[0]
    assert subject == "2 new tender leads"
    assert "good" in text and "unrated" in text and "bad" not in text


def test_failed_portal_is_reported():
    sender = alerts()
    sender.run_finished([], {"sources": {"etimad": {"ok": False, "count": 0, "error": "returned 0 tenders"}}})
    assert sender.channels[0].sent[0][0] == "Tender Radar: some portals failed"


def test_nothing_new_sends_nothing():
    sender = alerts()
    sender.run_finished([], {"sources": {"etimad": {"ok": True, "count": 4, "error": ""}}})
    assert sender.channels[0].sent == []


def test_reminders_are_marked_only_after_sending(store):
    closing = (date.today() + timedelta(days=1)).isoformat()
    store.save([make_lead("1", closing=closing)])
    store.set_lead_status("test:1", "bidding")
    sender = alerts()
    assert sender.send_reminders(store) == 1
    assert "closes in 1 day" in sender.channels[0].sent[0][1]
    assert sender.send_reminders(store) == 0


def test_unconfigured_channels_are_off():
    assert Alerts({"alerts": {"email": {"enabled": True}, "telegram": {"enabled": True}}}).channels == []


def test_small_company_mode_keeps_only_affordable_leads():
    sender = alerts()
    sender.small_company, sender.max_upfront = True, 2000
    cheap = lead_dict("cheap") | {"tender_type": "RFQ", "doc_fee": "", "bond": "", "currency": "QAR"}
    costly = lead_dict("costly") | {"tender_type": "مناقصة عامة", "doc_fee": "800", "bond": "80,000", "currency": "QAR"}
    assert [lead["key"] for lead in sender.digest_leads([cheap, costly])] == ["cheap"]

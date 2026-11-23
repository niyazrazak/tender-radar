import json

import pytest

import tender_radar.cli as cli
from tender_radar.ai import LeadAnalyst
from tender_radar.company import CompanyProfile
from tender_radar.outreach import Mailer, OutreachStore
from tests.conftest import make_lead
from tests.test_ai import api  # noqa: F401 (fixture)

SMTP = {"smtp_host": "smtp.test", "smtp_port": 587, "username": "sales@opal.test"}


@pytest.fixture
def outreach(store):
    return OutreachStore(store.db)


def contact(**fields):
    return {"company": "Alpha Co", "email": "ceo@alpha.test", "role": "partner"} | fields


def test_contacts_are_validated(outreach):
    with pytest.raises(ValueError):
        outreach.save_contact(contact(email="not an email"))
    with pytest.raises(ValueError):
        outreach.save_contact(contact(company=" "))
    contact_id = outreach.save_contact(contact(role="spy"))
    assert outreach.contact(contact_id)["role"] == "other"
    outreach.save_contact(contact(id=contact_id, person="Sara"))
    assert outreach.contact(contact_id)["person"] == "Sara"


def test_sent_emails_stay_when_the_contact_goes(outreach):
    contact_id = outreach.save_contact(contact())
    sent, draft = outreach.add_draft(contact_id, "", "Hello", "Body"), outreach.add_draft(contact_id, "", "Hi", "B")
    outreach.mark_sent(sent, ["profile.pdf"])
    with pytest.raises(ValueError):
        outreach.update_draft(sent, "Changed", "Body")
    outreach.delete_contact(contact_id)
    intros = outreach.intros()
    assert [i["id"] for i in intros] == [sent] and intros[0]["attachments"] == ["profile.pdf"]
    assert draft not in [i["id"] for i in intros] and outreach.sent_today() == 1


def test_message_has_signature_reply_to_and_attachments(tmp_path):
    profile = CompanyProfile(tmp_path / "company")
    profile.save_details({"name": "Opal", "email": "info@opal.test", "signature": "Niyaz\nOpal Technologies"})
    profile.add_document("Company Profile.pdf", b"%PDF profile")
    profile.add_document("CR.pdf", b"%PDF cr")
    profile.update_document("CR.pdf", attach=False)
    mailer = Mailer({"alerts": {"email": SMTP}, "outreach": {"bcc": ["me@opal.test"]}})
    intro = {"subject": "Introducing Opal", "body": "Dear Sara,\n\nKind regards,"}
    message = mailer.build(intro, contact(person="Sara"), profile.load(), profile.attachments())
    assert message["From"] == "Opal <sales@opal.test>" and message["To"] == "Sara <ceo@alpha.test>"
    assert message["Reply-To"] == "info@opal.test" and message["Bcc"] == "me@opal.test"
    assert message.get_body().get_content().endswith("Kind regards,\n\nNiyaz\nOpal Technologies\n")
    assert [part.get_filename() for part in message.iter_attachments()] == ["Company Profile.pdf"]


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture
def radar(tmp_path, monkeypatch):
    """A TenderRadar with its database and company folder in tmp_path, AI off."""
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "COMPANY", tmp_path / "company")
    monkeypatch.setattr("tender_radar.outreach.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr(cli.LeadAnalyst, "available", staticmethod(lambda config: False))
    FakeSMTP.sent = []
    config = {"keywords": {}, "sources": {}, "alerts": {"email": SMTP}, "outreach": {"daily_limit": 1}}
    (tmp_path / "config.json").write_text(json.dumps(config))
    return cli.TenderRadar(tmp_path / "config.json")


def test_send_marks_sent_and_keeps_to_the_daily_limit(radar):
    outreach = OutreachStore(radar.store.db)
    contact_id = outreach.save_contact(contact())
    first, second = (outreach.add_draft(contact_id, "", "Hello", "Body") for _ in range(2))
    assert radar.send_intro(first)["status"] == "sent" and len(FakeSMTP.sent) == 1
    with pytest.raises(ValueError, match="sent already"):
        radar.send_intro(first)
    with pytest.raises(ValueError, match="daily limit"):
        radar.send_intro(second)
    with pytest.raises(ValueError, match="AI is off"):
        radar.draft_intro(contact_id)


def test_intro_tells_claude_who_and_which_tender(api):  # noqa: F811
    api.reply({"subject": "Introducing Opal", "body": "Dear Sara, ... Kind regards,"})
    lead = make_lead("1", title="HR system", buyer="Ashghal", status="open").__dict__ | {"extra": {}}
    email = LeadAnalyst({"ai": {}}, "Company: Opal").intro(contact(person="Sara", role="buyer"), lead)
    assert email == {"subject": "Introducing Opal", "body": "Dear Sara, ... Kind regards,"}
    body = api.requests[0]["body"]
    assert "Company: Opal" in body["system"] and "do not ask about it" in body["system"]
    text = body["messages"][0]["content"]
    assert "Contact person: Sara" in text and "Buyer (issues tenders)" in text and "HR system" in text

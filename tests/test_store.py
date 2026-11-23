import sqlite3
from datetime import date, timedelta

import pytest

from tender_radar.store import LeadStore
from tests.conftest import make_lead


def iso(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def test_save_counts_only_new_leads(store):
    assert store.save([make_lead("1"), make_lead("2")]) == 2
    assert store.save([make_lead("1"), make_lead("3")]) == 1


def test_collection_never_overwrites_triage_ai_or_team_fields(store):
    store.save([make_lead("1", score=5)])
    store.set_lead_status("test:1", "bidding")
    store.set_ai_fit("test:1", 8, "Core ERP work")
    store.set_team_fields("test:1", {"owner": "Sara", "notes": "Partner with X"})
    store.save([make_lead("1", title="ERP system (amended)", score=5)])
    lead = store.get("test:1")
    kept = (lead["title"], lead["lead_status"], lead["ai_fit"], lead["owner"])
    assert kept == ("ERP system (amended)", "bidding", 8, "Sara")


def test_query_includes_ai_matches_below_the_keyword_score(store):
    store.save([make_lead("1", score=5), make_lead("2", score=0), make_lead("3", score=0)])
    store.set_ai_fit("test:2", 7, "Digital platform")
    store.set_ai_fit("test:3", 2, "Construction")
    assert {lead["key"] for lead in store.query(3)} == {"test:1"}
    assert {lead["key"] for lead in store.query(3, min_fit=6)} == {"test:1", "test:2"}


def test_query_hides_closed_open_tenders(store):
    store.save([make_lead("1", score=5, closing=iso(-1)), make_lead("2", score=5, closing=iso(3))])
    assert [lead["key"] for lead in store.query(3)] == ["test:2"]
    assert len(store.query(3, include_closed=True)) == 2


def test_unscreened_skips_rated_and_closed(store):
    store.save([make_lead("1", score=2), make_lead("2", score=2), make_lead("3", score=2, closing=iso(-2))])
    store.set_ai_fit("test:1", 5, "")
    assert [lead["key"] for lead in store.unscreened(1, 10)] == ["test:2"]


def test_team_fields_validate_the_deadline(store):
    store.save([make_lead("1")])
    with pytest.raises(ValueError):
        store.set_team_fields("test:1", {"bid_due": "next week"})
    with pytest.raises(ValueError):
        store.set_team_fields("test:1", {"unknown": "x"})
    assert store.set_team_fields("test:1", {"bid_due": iso(5)})


def test_reminders_fire_once_per_threshold_and_follow_a_moved_deadline(store):
    store.save([make_lead("1", closing=iso(3)), make_lead("2", closing=iso(2))])
    store.set_lead_status("test:1", "shortlisted")  # test:2 stays "new": no reminder
    due = store.due_reminders([7, 3, 1])
    assert [(lead["key"], deadline, days) for lead, deadline, days in due] == [("test:1", iso(3), 3)]
    store.mark_reminded("test:1", iso(3), 3)
    assert store.due_reminders([7, 3, 1]) == []
    store.set_team_fields("test:1", {"bid_due": iso(1)})  # our own deadline is earlier
    assert [(deadline, days) for _, deadline, days in store.due_reminders([7, 3, 1])] == [(iso(1), 1)]


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE leads (key TEXT PRIMARY KEY, title TEXT, first_seen TEXT, last_seen TEXT)")
    db.commit()
    db.close()
    LeadStore(path)
    columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(leads)")}
    assert {"ai_fit", "ai_reason", "ai_analysis", "notes", "owner", "bid_due"} <= columns

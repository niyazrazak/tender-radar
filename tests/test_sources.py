"""Every portal source, run offline against recorded real responses (see tests/recorder.py).

When a portal changes its pages, re-record its fixtures and these tests show what the parser now misses.
"""

import re

import pytest

from tender_radar.sources import SOURCES
from tests.recorder import FIXTURES, RECORD_SETTINGS, ReplayClient

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
RECORDED = [name for name in RECORD_SETTINGS if (FIXTURES / name).is_dir()]


def collect(name: str):
    return SOURCES[name](ReplayClient(FIXTURES / name), RECORD_SETTINGS[name]).collect({})


def test_every_source_has_fixtures():
    assert set(RECORDED) == set(SOURCES), "record missing ones: .venv/bin/python -m tests.recorder <name>"


@pytest.mark.parametrize("name", RECORDED)
def test_source_reads_normalized_leads(name):
    leads = collect(name)
    assert leads, f"{name}: no leads parsed from the recorded pages"
    assert len({lead.key for lead in leads}) == len(leads), "source_id must be unique and stable"
    for lead in leads:
        assert lead.source == name and lead.title and lead.url.startswith("http") and lead.country
        assert lead.status in ("open", "future", "opened", "awarded")
        for date in (lead.published, lead.closing):
            assert date == "" or ISO.fullmatch(date), f"{lead.key}: date {date!r} is not ISO"


@pytest.mark.parametrize("name", RECORDED)
def test_source_fills_text_for_scoring(name):
    leads = collect(name)
    with_text = [lead for lead in leads if lead.brief or lead.activities or lead.category or lead.buyer]
    assert len(with_text) >= len(leads) // 2, f"{name}: most leads have only a title, so scoring is weak"


def test_monaqasat_reads_award_reports():
    awarded = [lead for lead in collect("monaqasat") if lead.status == "awarded"]
    with_winner = [lead for lead in awarded if lead.extra.get("winners")]
    assert with_winner, "no winners parsed from award reports"
    assert all(winner["company"] for lead in with_winner for winner in lead.extra["winners"])


def test_monaqasat_reads_details():
    opened = [lead for lead in collect("monaqasat") if lead.status == "open"]
    assert any(lead.activities for lead in opened) and any(lead.brief for lead in opened)


def test_monaqasat_keeps_the_winner_registration_number():
    winners = [w for lead in collect("monaqasat") for w in lead.extra.get("winners", [])]
    assert winners and all(w["cr"] for w in winners)

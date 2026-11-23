import pytest

from tender_radar.lead import Lead
from tender_radar.store import LeadStore


@pytest.fixture
def store(tmp_path):
    return LeadStore(tmp_path / "leads.db")


def make_lead(source_id="1", **fields) -> Lead:
    defaults = {
        "source": "test", "source_id": source_id, "country": "Qatar", "title": "ERP system", "url": "https://x/1",
    }
    return Lead(**(defaults | fields))

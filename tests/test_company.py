import pytest

from tender_radar.ai import LeadAnalyst
from tender_radar.company import CompanyProfile
from tests.test_ai import api  # noqa: F401 (fixture)


@pytest.fixture
def profile(tmp_path):
    return CompanyProfile(tmp_path / "company", fallback="Software company: ERP")


def test_empty_profile_falls_back_to_the_config_line(profile):
    data = profile.load()
    assert not data["saved"] and data["details"]["services"] == []
    assert profile.summary() == "Software company: ERP"
    assert profile.display_name() == "Software company: ERP"


def test_saved_details_keep_known_fields_and_split_lists(profile):
    profile.save_details({
        "name": " Opal ", "services": "ERP\n\nMobile apps\n", "clients": ["Ashghal: HR system (2024)"], "unknown": "x",
    })
    details = profile.load()["details"]
    assert details["name"] == "Opal" and details["services"] == ["ERP", "Mobile apps"] and "unknown" not in details
    summary = profile.summary()
    assert "Company: Opal" in summary and "- Mobile apps" in summary and "Software company" not in summary


def test_documents_are_listed_guessed_and_removed(profile):
    profile.add_document("../CR copy.pdf", b"%PDF cr")
    profile.add_document("Company Profile 2026.pdf", b"%PDF profile")
    profile.add_document("logo.docx", b"word")
    kinds = {doc["name"]: doc["kind"] for doc in profile.load()["documents"]}
    assert kinds == {"CR copy.pdf": "cr", "Company Profile 2026.pdf": "profile", "logo.docx": "other"}
    # The company profile is read first; Word files are not sent to Claude.
    assert [name for name, _ in profile.readable_documents()] == ["Company Profile 2026.pdf", "CR copy.pdf"]
    profile.update_document("CR copy.pdf", attach=False)
    assert not next(doc for doc in profile.load()["documents"] if doc["name"] == "CR copy.pdf")["attach"]
    profile.remove_document("CR copy.pdf")
    assert not (profile.documents_folder / "CR copy.pdf").exists()


def test_only_listed_documents_are_served(profile):
    profile.add_document("profile.pdf", b"%PDF")
    assert profile.document_path("profile.pdf").read_bytes() == b"%PDF"
    with pytest.raises(ValueError):
        profile.document_path("../profile.json")
    with pytest.raises(ValueError):
        profile.add_document("script.sh", b"echo")


def test_read_company_sends_the_documents(api):  # noqa: F811
    found = {
        "name": "Opal", "legal_name": "Opal Technologies W.L.L.", "cr_number": "12345", "established": "2015",
        "employees": "40", "website": "", "contact_name": "", "contact_title": "", "email": "", "phone": "",
        "address": "Doha", "about": "Builds ERP systems.", "services": ["ERP"], "sectors": ["Government"],
        "certifications": [], "clients": [], "differentiators": "",
    }
    api.reply(found)
    assert LeadAnalyst({"ai": {}}).read_company([("profile.pdf", b"%PDF-1.4 test")]) == found
    content = api.requests[0]["body"]["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["title"] == "profile.pdf"
    with pytest.raises(ValueError):
        LeadAnalyst({"ai": {}}).read_company([])


def test_analyst_rates_against_the_profile(api):  # noqa: F811
    api.reply({"results": [{"index": 0, "fit": 8, "reason": "ERP"}]})
    tender = {"key": "a", "title": "ERP", "buyer": "", "country": "Qatar", "status": "open"}
    LeadAnalyst({"company": "old line", "ai": {}}, "Company: Opal\nServices:\n- ERP").screen([tender])
    assert "Company: Opal" in api.requests[0]["body"]["system"]

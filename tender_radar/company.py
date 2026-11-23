"""Your company's profile: the details and documents (company profile PDF, CR, certificates) that
introduce you to a buyer or a partner.

Kept in data/company/: profile.json holds the details and the list of documents, documents/ holds the
files. When the profile has content, Claude rates and analyzes tenders against it instead of the
one line in config.json -> "company". Documents marked `attach` are the ones to send with
introduction emails.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

TEXT_FIELDS = (
    "name", "legal_name", "cr_number", "established", "employees", "website",
    "contact_name", "contact_title", "email", "phone", "address",
    "about", "differentiators", "signature",
)
LIST_FIELDS = ("services", "sectors", "certifications", "clients")
DOCUMENT_KINDS = ("profile", "cr", "license", "certificate", "other")
DOCUMENT_TYPES = (".pdf", ".png", ".jpg", ".jpeg", ".docx")
READABLE_TYPES = (".pdf", ".png", ".jpg", ".jpeg")  # what Claude can read to fill the profile
SAFE_NAME = re.compile(r"[^\w.\- ]+")

# How each field is labelled in the text Claude reads.
PROMPT_LABELS = {
    "name": "Company", "legal_name": "Legal name", "cr_number": "Commercial registration",
    "established": "Established", "employees": "Employees", "website": "Website", "address": "Address",
    "about": "About", "services": "Services", "sectors": "Sectors served", "certifications": "Certifications",
    "clients": "Clients and projects", "differentiators": "Strengths",
}


class CompanyProfile:
    def __init__(self, folder: Path, fallback: str = ""):
        """`fallback` (config.json -> "company") describes the company while the profile is empty."""
        self.folder = folder
        self.documents_folder = folder / "documents"
        self.path = folder / "profile.json"
        self.fallback = fallback

    def load(self) -> dict:
        """{"details": {...}, "documents": [...], "saved": bool, "fallback": str}."""
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        return {
            "details": _clean(data.get("details", {})), "documents": data.get("documents", []),
            "saved": bool(data), "fallback": self.fallback,
        }

    def save_details(self, details: dict) -> dict:
        data = self.load()
        data["details"] = _clean(details)
        self._write(data)
        return self.load()

    def add_document(self, name: str, content: bytes, kind: str = "") -> dict:
        name = SAFE_NAME.sub("_", Path(name).name).strip() or "document.pdf"
        if not name.lower().endswith(DOCUMENT_TYPES):
            raise ValueError(f"{name}: upload a PDF, image or Word file")
        self.documents_folder.mkdir(parents=True, exist_ok=True)
        (self.documents_folder / name).write_bytes(content)
        data = self.load()
        others = [doc for doc in data["documents"] if doc["name"] != name]
        entry = {
            "name": name, "kind": kind if kind in DOCUMENT_KINDS else _guess_kind(name), "attach": True,
            "size": len(content), "added": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        data["documents"] = others + [entry]
        self._write(data)
        return entry

    def update_document(self, name: str, kind: str | None = None, attach: bool | None = None):
        data = self.load()
        entry = self._entry(data, name)
        if kind is not None:
            if kind not in DOCUMENT_KINDS:
                raise ValueError(f"Unknown document kind: {kind}")
            entry["kind"] = kind
        if attach is not None:
            entry["attach"] = bool(attach)
        self._write(data)

    def remove_document(self, name: str):
        data = self.load()
        entry = self._entry(data, name)
        data["documents"].remove(entry)
        (self.documents_folder / entry["name"]).unlink(missing_ok=True)
        self._write(data)

    def document_path(self, name: str) -> Path:
        """Only names in the profile's list are served, so a request cannot reach other files."""
        return self.documents_folder / self._entry(self.load(), name)["name"]

    def readable_documents(self) -> list[tuple[str, bytes]]:
        """(name, bytes) of the documents Claude can read, the company profile first."""
        documents = sorted(self.load()["documents"], key=lambda doc: doc["kind"] != "profile")
        return [
            (doc["name"], (self.documents_folder / doc["name"]).read_bytes()) for doc in documents
            if doc["name"].lower().endswith(READABLE_TYPES) and (self.documents_folder / doc["name"]).is_file()
        ]

    def attachments(self) -> list[tuple[str, bytes]]:
        """(name, bytes) of the documents marked to go with introduction emails."""
        return [
            (doc["name"], (self.documents_folder / doc["name"]).read_bytes()) for doc in self.load()["documents"]
            if doc.get("attach") and (self.documents_folder / doc["name"]).is_file()
        ]

    def summary(self) -> str:
        """The profile as text for Claude, or `fallback` when nothing is filled in."""
        details = self.load()["details"]
        lines = []
        for field, label in PROMPT_LABELS.items():
            value = details.get(field)
            if isinstance(value, list) and value:
                lines.append(f"{label}:\n" + "\n".join(f"- {item}" for item in value))
            elif value and not isinstance(value, list):
                lines.append(f"{label}: {value}")
        return "\n".join(lines) or self.fallback

    def display_name(self) -> str:
        details = self.load()["details"]
        return details["name"] or details["legal_name"] or self.fallback

    def _entry(self, data: dict, name: str) -> dict:
        for entry in data["documents"]:
            if entry["name"] == name:
                return entry
        raise ValueError(f"No document named {name}")

    def _write(self, data: dict):
        self.folder.mkdir(parents=True, exist_ok=True)
        payload = {"details": data["details"], "documents": data["documents"]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(details: dict) -> dict:
    """Known fields only. List fields accept a list or one item per line."""
    clean = {name: str(details.get(name) or "").strip() for name in TEXT_FIELDS}
    for name in LIST_FIELDS:
        value = details.get(name) or []
        items = value.splitlines() if isinstance(value, str) else value
        clean[name] = [str(item).strip() for item in items if str(item).strip()]
    return clean


def _guess_kind(name: str) -> str:
    """From words in the file name, such as "CR copy.pdf" or "ISO 9001 certificate.pdf"."""
    words = [word for word in re.split(r"[^a-z0-9]+", Path(name).stem.lower()) if word]
    for kind, starts in (("cr", ("cr", "commercial", "registration")), ("license", ("licen",)),
                         ("certificate", ("iso", "certif")), ("profile", ("profile", "brochure"))):
        if any(word == start or (len(start) > 2 and word.startswith(start)) for word in words for start in starts):
            return kind
    return "other"

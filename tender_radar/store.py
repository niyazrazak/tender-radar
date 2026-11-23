import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tender_radar.lead import Lead

COLUMNS = [
    "source", "source_id", "country", "title", "url", "status", "ref_no", "buyer",
    "category", "tender_type", "published", "closing", "bond", "doc_fee", "currency",
    "brief", "activities", "extra", "score", "matched",
]

# Triage state the user sets in the dashboard. Collection never overwrites it.
LEAD_STATUSES = ("new", "shortlisted", "bidding", "dismissed")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS leads (
    key TEXT PRIMARY KEY,
    {", ".join(f"{c} TEXT" for c in COLUMNS)},
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    lead_status TEXT NOT NULL DEFAULT 'new'
)
"""


class LeadStore:
    """SQLite store. Keeps first_seen so we know which leads are new since the last run."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # The dashboard and the scheduler each open their own connection; WAL lets them read while a run writes.
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(SCHEMA)

    def known_keys(self) -> dict:
        """{key: status} of every stored lead. `key in known_keys` works as for a set."""
        return {row["key"]: row["status"] for row in self.db.execute("SELECT key, status FROM leads")}

    def restore_details(self, leads: list[Lead]):
        """Details are fetched only once; copy stored ones back so rescoring sees them."""
        for lead in leads:
            if lead.brief or lead.activities:
                continue
            row = self.db.execute("SELECT brief, activities, extra FROM leads WHERE key = ?", (lead.key,)).fetchone()
            if row:
                lead.brief, lead.activities = row["brief"] or "", row["activities"] or ""
                lead.extra = {**json.loads(row["extra"] or "{}"), **lead.extra}

    def save(self, leads: list[Lead]) -> int:
        """Insert or update leads. Returns how many were never seen before."""
        now = _now()
        known = self.known_keys()
        for lead in leads:
            self._upsert(lead, now)
        self.db.commit()
        return sum(1 for lead in leads if lead.key not in known)

    def rescore(self, scorer) -> int:
        """Apply the current keywords to every stored lead, without any network call."""
        rows = self.db.execute("SELECT * FROM leads").fetchall()
        for row in rows:
            data = self._row_to_dict(row)
            lead = Lead(**{c: data[c] for c in COLUMNS if c not in ("score", "matched")})
            scorer.score(lead)
            self.db.execute(
                "UPDATE leads SET score = ?, matched = ? WHERE key = ?", (lead.score, lead.matched, row["key"])
            )
        self.db.commit()
        return len(rows)

    def query(self, min_score: int, since: str = "", include_closed: bool = False, countries=()) -> list[dict]:
        sql = "SELECT * FROM leads WHERE CAST(score AS INTEGER) >= ?"
        args = [min_score]
        if since:
            sql += " AND first_seen >= ?"
            args.append(since)
        if countries:
            sql += f" AND country IN ({', '.join('?' * len(countries))})"
            args += list(countries)
        if not include_closed:
            sql += " AND (status != 'open' OR closing = '' OR closing >= date('now'))"
        sql += " ORDER BY first_seen DESC, CAST(score AS INTEGER) DESC"
        return [self._row_to_dict(row) for row in self.db.execute(sql, args)]

    def set_lead_status(self, key: str, status: str) -> bool:
        if status not in LEAD_STATUSES:
            raise ValueError(f"Unknown lead status: {status}")
        changed = self.db.execute("UPDATE leads SET lead_status = ? WHERE key = ?", (status, key)).rowcount
        self.db.commit()
        return bool(changed)

    def _upsert(self, lead: Lead, now: str):
        values = {c: getattr(lead, c) for c in COLUMNS}
        values["extra"] = json.dumps(lead.extra, ensure_ascii=False)
        cols = ", ".join(["key", *values, "first_seen", "last_seen"])
        marks = ", ".join("?" * (len(values) + 3))
        updates = ", ".join(f"{c} = excluded.{c}" for c in [*values, "last_seen"])
        self.db.execute(
            f"INSERT INTO leads ({cols}) VALUES ({marks}) ON CONFLICT(key) DO UPDATE SET {updates}",
            [lead.key, *values.values(), now, now],
        )

    def _row_to_dict(self, row) -> dict:
        data = dict(row)
        data["extra"] = json.loads(data["extra"] or "{}")
        data["score"] = int(data["score"] or 0)
        return data


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

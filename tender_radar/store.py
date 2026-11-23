import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from tender_radar.lead import Lead

COLUMNS = [
    "source", "source_id", "country", "title", "url", "status", "ref_no", "buyer",
    "category", "tender_type", "published", "closing", "bond", "doc_fee", "currency",
    "brief", "activities", "extra", "score", "matched",
]

# Triage state the user sets in the dashboard. Collection never overwrites it.
LEAD_STATUSES = ("new", "shortlisted", "bidding", "dismissed")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Columns added after the first release. The store adds missing ones to an older database on open.
# Collection never writes them: they hold the AI assessment and the team's own notes.
LATER_COLUMNS = {
    "ai_fit": "INTEGER",
    "ai_reason": "TEXT NOT NULL DEFAULT ''",
    "ai_analysis": "TEXT NOT NULL DEFAULT ''",
    "notes": "TEXT NOT NULL DEFAULT ''",
    "owner": "TEXT NOT NULL DEFAULT ''",
    "bid_due": "TEXT NOT NULL DEFAULT ''",
    "pitch": "TEXT NOT NULL DEFAULT ''",
}
TEAM_FIELDS = ("notes", "owner", "bid_due")

REMINDERS = """
CREATE TABLE IF NOT EXISTS reminders (
    key TEXT NOT NULL,
    deadline TEXT NOT NULL,
    days INTEGER NOT NULL,
    sent TEXT NOT NULL,
    PRIMARY KEY (key, deadline, days)
)
"""

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
        self.db.execute(REMINDERS)
        self._add_later_columns()

    def _add_later_columns(self):
        present = {row[1] for row in self.db.execute("PRAGMA table_info(leads)")}
        for name, kind in LATER_COLUMNS.items():
            if name not in present:
                self.db.execute(f"ALTER TABLE leads ADD COLUMN {name} {kind}")
        self.db.commit()

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

    def query(
        self, min_score: int, since: str = "", include_closed: bool = False, countries=(), min_fit: int | None = None
    ) -> list[dict]:
        """Leads that match by keywords, or that the AI rated at least `min_fit` (catches other wording)."""
        sql = "SELECT * FROM leads WHERE (CAST(score AS INTEGER) >= ?"
        args = [min_score]
        if min_fit is not None:
            sql += " OR ai_fit >= ?"
            args.append(min_fit)
        sql += ")"
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

    def get(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM leads WHERE key = ?", (key,)).fetchone()
        return self._row_to_dict(row) if row else None

    def set_team_fields(self, key: str, fields: dict) -> bool:
        """Notes, owner and bid deadline, set by people in the dashboard."""
        values = {name: str(fields[name]).strip() for name in TEAM_FIELDS if name in fields}
        if not values:
            raise ValueError(f"Nothing to save. Fields: {', '.join(TEAM_FIELDS)}")
        if values.get("bid_due") and not ISO_DATE.fullmatch(values["bid_due"]):
            raise ValueError("bid_due must be YYYY-MM-DD")
        assignments = ", ".join(f"{name} = ?" for name in values)
        changed = self.db.execute(f"UPDATE leads SET {assignments} WHERE key = ?", [*values.values(), key]).rowcount
        self.db.commit()
        return bool(changed)

    def unscreened(self, min_score: int, limit: int) -> list[dict]:
        """Open leads the AI has not rated yet, best keyword score first."""
        rows = self.db.execute(
            """SELECT * FROM leads WHERE ai_fit IS NULL AND CAST(score AS INTEGER) >= ?
               AND status IN ('open', 'future') AND (closing = '' OR closing >= date('now'))
               ORDER BY CAST(score AS INTEGER) DESC, first_seen DESC LIMIT ?""",
            (min_score, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def set_ai_fit(self, key: str, fit: int, reason: str):
        self.db.execute("UPDATE leads SET ai_fit = ?, ai_reason = ? WHERE key = ?", (fit, reason, key))
        self.db.commit()

    def set_ai_analysis(self, key: str, analysis: dict):
        text = json.dumps(analysis, ensure_ascii=False)
        self.db.execute("UPDATE leads SET ai_analysis = ? WHERE key = ?", (text, key))
        self.db.commit()

    def recent_awards(self, days: int, min_score: int, min_fit: int | None = None) -> list[dict]:
        """Awarded tenders in your field with a known winner, awarded in the last `days` days, newest first.

        For awarded tenders `published` holds the award date (Monaqasat's "تاريخ الترسية").
        """
        sql = """SELECT * FROM leads WHERE status = 'awarded' AND extra LIKE '%"winners"%'
                 AND published >= date('now', ?) AND (CAST(score AS INTEGER) >= ?"""
        args = [f"-{int(days)} day", min_score]
        if min_fit is not None:
            sql += " OR ai_fit >= ?"
            args.append(min_fit)
        sql += ") ORDER BY published DESC"
        return [self._row_to_dict(row) for row in self.db.execute(sql, args)]

    def set_pitch(self, key: str, pitch: dict):
        self.db.execute("UPDATE leads SET pitch = ? WHERE key = ?", (json.dumps(pitch, ensure_ascii=False), key))
        self.db.commit()

    def awarded_without_report(self, source: str, limit: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM leads WHERE source = ? AND status = 'awarded' AND extra NOT LIKE '%award_report%'
               ORDER BY first_seen DESC LIMIT ?""",
            (source, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def set_extra(self, key: str, extra: dict):
        self.db.execute("UPDATE leads SET extra = ? WHERE key = ?", (json.dumps(extra, ensure_ascii=False), key))
        self.db.commit()

    def due_reminders(self, days_before: list[int]) -> list[tuple[dict, str, int]]:
        """(lead, deadline, days left) for shortlisted or bidding leads whose deadline is near and not yet reminded.

        The deadline is the team's own bid_due when set, else the portal's closing date.
        One reminder per lead, deadline and threshold, so a moved deadline reminds again.
        """
        rows = self.db.execute(
            """SELECT * FROM leads WHERE lead_status IN ('shortlisted', 'bidding')
               AND COALESCE(NULLIF(bid_due, ''), closing) >= date('now')"""
        ).fetchall()
        due = []
        for row in rows:
            lead = self._row_to_dict(row)
            deadline = lead["bid_due"] or lead["closing"]
            left = (date.fromisoformat(deadline) - date.today()).days
            # Only the nearest threshold reached; skipped ones (e.g. shortlisted 2 days before) do not pile up.
            reached = [days for days in sorted(days_before) if left <= days]
            if reached and not self._reminded(lead["key"], deadline, reached[0]):
                due.append((lead, deadline, reached[0]))
        return due

    def mark_reminded(self, key: str, deadline: str, days: int):
        self.db.execute("INSERT OR IGNORE INTO reminders VALUES (?, ?, ?, ?)", (key, deadline, days, _now()))
        self.db.commit()

    def _reminded(self, key: str, deadline: str, days: int) -> bool:
        return self.db.execute(
            "SELECT 1 FROM reminders WHERE key = ? AND deadline = ? AND days = ?", (key, deadline, days)
        ).fetchone() is not None

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
        data["ai_analysis"] = json.loads(data["ai_analysis"]) if data.get("ai_analysis") else None
        data["pitch"] = json.loads(data["pitch"]) if data.get("pitch") else None
        return data


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

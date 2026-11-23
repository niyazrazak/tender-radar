import json
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,
    started TEXT NOT NULL,
    finished TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    total INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    sources TEXT DEFAULT '{}',
    error TEXT DEFAULT ''
)
"""


class RunLog:
    """History of collection runs, so the dashboard can show when we last checked and what failed."""

    def __init__(self, db):
        self.db = db
        self.db.execute(SCHEMA)

    def start(self, trigger: str) -> int:
        cursor = self.db.execute("INSERT INTO runs (trigger, started) VALUES (?, ?)", (trigger, now_utc()))
        self.db.commit()
        return cursor.lastrowid

    def finish(self, run_id: int, result: dict, error: str = ""):
        failed = error or any(not item["ok"] for item in result.get("sources", {}).values())
        self.db.execute(
            "UPDATE runs SET finished = ?, status = ?, total = ?, new_count = ?, sources = ?, error = ? WHERE id = ?",
            (
                now_utc(), "error" if error else "partial" if failed else "ok",
                result.get("total", 0), result.get("new", 0),
                json.dumps(result.get("sources", {}), ensure_ascii=False), error, run_id,
            ),
        )
        self.db.commit()

    def close_interrupted(self):
        """A run still 'running' at startup was killed with the process."""
        self.db.execute("UPDATE runs SET status = 'interrupted', finished = started WHERE status = 'running'")
        self.db.commit()

    def recent(self, limit: int = 10) -> list[dict]:
        rows = self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "sources": json.loads(row["sources"] or "{}")} for row in rows]

    def last(self) -> dict | None:
        runs = self.recent(1)
        return runs[0] if runs else None


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

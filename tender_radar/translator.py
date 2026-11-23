import re
import time

import requests

ARABIC = re.compile(r"[؀-ۿ]")
# Google's free web endpoint: no API key needed. Tender titles are public data.
ENDPOINT = "https://translate.googleapis.com/translate_a/single"


class Translator:
    """Translates Arabic text to English, caching every result in SQLite so each text is sent once."""

    def __init__(self, db, delay_seconds: float = 1.0):
        self.db = db
        self.delay = delay_seconds
        self.blocked = False  # set after a 429; retrying only extends the block
        self.db.execute("CREATE TABLE IF NOT EXISTS translations (source TEXT PRIMARY KEY, english TEXT NOT NULL)")

    def english(self, text: str) -> str:
        """English version of text; text unchanged if it has no Arabic or translation fails."""
        if not text or not ARABIC.search(text):
            return text or ""
        row = self.db.execute("SELECT english FROM translations WHERE source = ?", (text,)).fetchone()
        if row:
            return row[0]
        english = "" if self.blocked else self._fetch(text)
        if english:
            self.db.execute("INSERT OR REPLACE INTO translations VALUES (?, ?)", (text, english))
            self.db.commit()
        return english or text

    def cached(self, text: str) -> str:
        """English from the cache only, never the network: for the dashboard, which must answer fast."""
        if not text or not ARABIC.search(text):
            return text or ""
        row = self.db.execute("SELECT english FROM translations WHERE source = ?", (text,)).fetchone()
        return row[0] if row else text

    def _fetch(self, text: str) -> str:
        time.sleep(self.delay)
        try:
            # POST, because a long brief does not fit in a URL.
            response = requests.post(
                ENDPOINT, params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t"}, data={"q": text}, timeout=20
            )
            if response.status_code == 429:
                self.blocked = True
                print("  ! translation rate-limited by Google; the rest will be translated on the next run")
                return ""
            response.raise_for_status()
            return "".join(part[0] for part in response.json()[0] if part[0]).strip()
        except (requests.RequestException, ValueError, IndexError, TypeError) as error:
            print(f"  ! translation failed: {error}")
            return ""

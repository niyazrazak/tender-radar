import re
import time

import requests

ARABIC = re.compile(r"[؀-ۿ]")
# Google's free endpoint used by its Chrome extension: no API key, many texts per request,
# one result per text. Tender titles are public data.
ENDPOINT = "https://clients5.google.com/translate_a/t"
PARAMS = {"client": "dict-chrome-ex", "sl": "auto", "tl": "en"}
BATCH_TEXTS = 40
BATCH_CHARS = 4000


class Translator:
    """Translates Arabic text to English, caching every result in SQLite so each text is sent once."""

    def __init__(self, db, delay_seconds: float = 1.0, fallback=None):
        """`fallback(texts) -> list[str]` translates when Google rate-limits (Claude, when AI is on)."""
        self.db = db
        self.delay = delay_seconds
        self.fallback = fallback
        self.blocked = False  # set after a 429; retrying only extends the block
        self.db.execute("CREATE TABLE IF NOT EXISTS translations (source TEXT PRIMARY KEY, english TEXT NOT NULL)")

    def english(self, text: str) -> str:
        """English version of text; text unchanged if it has no Arabic or translation fails."""
        self.translate_many([text])
        return self.cached(text)

    def translate_many(self, texts, fallback_first: bool = False) -> int:
        """Translates every uncached Arabic text, in batches. Returns how many were added to the cache.
        `fallback_first` sends texts to the fallback (Claude) before Google: Google translates the words
        of a company name ("Canary Zoo" becomes "Kaniri Zoo"), Claude keeps the name."""
        added = 0
        for batch in _batches(self._uncached(texts)):
            if self.blocked and not self.fallback:
                break
            use_fallback = self.fallback and (self.blocked or fallback_first)
            english = self.fallback(batch) if use_fallback else self._fetch(batch)
            pairs = [(src, en) for src, en in zip(batch, english) if en]
            self.db.executemany("INSERT OR REPLACE INTO translations VALUES (?, ?)", pairs)
            self.db.commit()
            added += len(pairs)
        return added

    def cached(self, text: str) -> str:
        """English from the cache only, never the network: for the dashboard, which must answer fast."""
        if not text or not ARABIC.search(text):
            return text or ""
        row = self.db.execute("SELECT english FROM translations WHERE source = ?", (text,)).fetchone()
        return row[0] if row else text

    def _uncached(self, texts) -> list[str]:
        wanted = {t for t in texts if t and ARABIC.search(t)}
        if not wanted:
            return []
        done = {row[0] for row in self.db.execute("SELECT source FROM translations")}
        return sorted(wanted - done)

    def _fetch(self, batch: list[str]) -> list[str]:
        """One English string per input text; empty strings when the request fails."""
        time.sleep(self.delay)
        try:
            response = requests.post(ENDPOINT, params=PARAMS, data=[("q", t) for t in batch], timeout=30)
            if response.status_code == 429:
                self.blocked = True
                rest = "Claude translates the rest" if self.fallback else "the rest will be translated on the next run"
                print(f"  ! translation rate-limited by Google; {rest}")
                return [""] * len(batch)
            response.raise_for_status()
            return [_text_of(item) for item in response.json()]
        except (requests.RequestException, ValueError, IndexError, TypeError) as error:
            print(f"  ! translation failed: {error}")
            return [""] * len(batch)


def _text_of(item) -> str:
    # A batch answers [[english, lang], ...]; a single text may answer just "english".
    return (item[0] if isinstance(item, list) else item or "").strip()


def _batches(texts: list[str]):
    batch, size = [], 0
    for text in texts:
        if batch and (len(batch) >= BATCH_TEXTS or size + len(text) > BATCH_CHARS):
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += len(text)
    if batch:
        yield batch

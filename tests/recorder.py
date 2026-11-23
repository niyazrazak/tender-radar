"""Records real portal responses once, and replays them in tests without the network.

Re-record after a portal changes (and the parser is fixed):
    .venv/bin/python -m tests.recorder            # every source
    .venv/bin/python -m tests.recorder etimad     # one source

Each source runs with small settings (one page) so the fixtures stay small. Responses are
stored gzipped under tests/fixtures/<source>/, keyed by a hash of the request.
"""

import gzip
import hashlib
import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# Small runs: enough rows to test parsing, details and paging, few requests to the portals.
RECORD_SETTINGS = {
    "monaqasat": {"max_pages": 1, "awarded_pages": 1, "fetch_details": True, "award_reports": True},
    "mwani": {"max_items": 20},
    "qfa": {"max_pages": 2},
    "sidra": {},
    "woqod": {"max_pages": 1},
    "etimad": {"max_pages": 1, "publish_window": "week"},
    "oman_tender_board": {"max_pages": 1, "in_process_pages": 1},
    "kuwait_capt": {"max_pages": 2},
    "bahrain_tender_board": {"max_pages": 1, "fetch_details": True},
}


def request_key(method: str, url: str, kwargs: dict) -> str:
    detail = json.dumps(
        {"m": method, "u": url, "p": kwargs.get("params"), "b": kwargs.get("body")}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha1(detail.encode()).hexdigest()[:16]


class RecordingClient:
    """Passes calls to the real client and saves every answer."""

    def __init__(self, client, folder: Path):
        self.client = client
        self.folder = folder
        self.timeout = client.timeout

    def get_text(self, url, **kwargs):
        return self._save("get_text", url, kwargs, self.client.get_text(url, **kwargs))

    def get_json(self, url, **kwargs):
        return self._save("get_json", url, kwargs, self.client.get_json(url, **kwargs))

    def post_json(self, url, body, **kwargs):
        return self._save("post_json", url, {**kwargs, "body": body}, self.client.post_json(url, body, **kwargs))

    def _save(self, method, url, kwargs, answer):
        path = self.folder / f"{request_key(method, url, kwargs)}.json.gz"
        record = {"method": method, "url": url, "answer": answer}
        path.write_bytes(gzip.compress(json.dumps(record, ensure_ascii=False).encode()))
        return answer


class ReplayClient:
    """Answers from recorded fixtures. A request that was not recorded fails, as a broken portal would."""

    timeout = 30

    def __init__(self, folder: Path):
        self.folder = folder

    def get_text(self, url, **kwargs):
        return self._load("get_text", url, kwargs)

    def get_json(self, url, **kwargs):
        return self._load("get_json", url, kwargs)

    def post_json(self, url, body, **kwargs):
        return self._load("post_json", url, {**kwargs, "body": body})

    def _load(self, method, url, kwargs):
        path = self.folder / f"{request_key(method, url, kwargs)}.json.gz"
        if not path.is_file():
            raise ConnectionError(f"not recorded: {method} {url}")
        return json.loads(gzip.decompress(path.read_bytes()))["answer"]


def record(names: list[str]):
    from tender_radar.http_client import PoliteClient
    from tender_radar.sources import SOURCES

    for name in names or RECORD_SETTINGS:
        folder = FIXTURES / name
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.json.gz"):
            old.unlink()
        client = RecordingClient(PoliteClient(delay=1.0), folder)
        leads = SOURCES[name](client, RECORD_SETTINGS[name]).collect({})
        size = sum(path.stat().st_size for path in folder.glob("*")) // 1024
        print(f"{name}: {len(leads)} leads, {len(list(folder.glob('*')))} responses, {size} KB")


if __name__ == "__main__":
    record(sys.argv[1:])

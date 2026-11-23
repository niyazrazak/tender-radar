"""Fetch one portal URL with the project's PoliteClient and save the body.

Use it before you write a parser, and when a source breaks, to see what the
real run receives (same TLS settings, headers and retries).

    .venv/bin/python .claude/skills/tender-portal/scripts/probe_url.py URL [--json] [--out FILE]
"""

import argparse
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT))

from tender_radar.http_client import PoliteClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--json", action="store_true", help="Send XHR/JSON headers")
    parser.add_argument("--out", help="Save the body here (default: print the first 3000 characters)")
    args = parser.parse_args()

    client = PoliteClient(delay=0, retries=1)
    headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"} if args.json else {}
    try:
        response = client._get(args.url, headers=headers)
    except Exception as error:
        print(f"FAILED: {type(error).__name__}: {error}")
        sys.exit(1)

    print(f"HTTP {response.status_code}  {response.headers.get('Content-Type', '')}  {len(response.content)} bytes")
    print(f"Final URL: {response.url}")
    if args.out:
        Path(args.out).write_text(response.text, encoding="utf-8")
        print(f"Saved to {args.out}")
    else:
        print(response.text[:3000])


if __name__ == "__main__":
    main()

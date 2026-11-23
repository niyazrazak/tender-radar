"""Company names go to Claude before Google: Google translates the words of a brand name."""

import sqlite3

from tender_radar.translator import Translator


def test_fallback_first_skips_google(monkeypatch):
    claude = lambda texts: ["Canary Zoo Services"]  # noqa: E731
    translator = Translator(sqlite3.connect(":memory:"), delay_seconds=0, fallback=claude)
    monkeypatch.setattr(translator, "_fetch", lambda batch: ["Kaniri Zoo Lalkhudats"])
    translator.translate_many(["كناري زوو للخدمات"], fallback_first=True)
    assert translator.cached("كناري زوو للخدمات") == "Canary Zoo Services"


def test_google_first_by_default(monkeypatch):
    translator = Translator(sqlite3.connect(":memory:"), delay_seconds=0, fallback=lambda texts: ["Claude"])
    monkeypatch.setattr(translator, "_fetch", lambda batch: ["Google"])
    translator.translate_many(["نص"])
    assert translator.cached("نص") == "Google"

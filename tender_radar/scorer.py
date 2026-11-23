import re

from tender_radar.lead import Lead

STRONG_WEIGHT = 3
WEAK_WEIGHT = 1
EXCLUDE_PENALTY = 5

ARABIC_FOLDS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ـ": ""})
ARABIC_MARKS = re.compile(r"[ً-ْٰ]")
LATIN = re.compile(r"[a-z]")


class KeywordScorer:
    """Scores a lead by keyword hits. Arabic is folded so spelling variants still match."""

    def __init__(self, keywords: dict):
        self.rules = []
        for group, weight in (("strong", STRONG_WEIGHT), ("weak", WEAK_WEIGHT), ("exclude", -EXCLUDE_PENALTY)):
            for word in keywords.get(group, []):
                self.rules.append((word, weight, self._pattern(word)))

    def score(self, lead: Lead) -> Lead:
        text = normalize(lead.searchable_text())
        hits = _drop_nested([(word, weight) for word, weight, pattern in self.rules if pattern.search(text)])
        lead.score = sum(weight for _, weight in hits)
        lead.matched = ", ".join(word for word, weight in hits if weight > 0)
        excluded = [word for word, weight in hits if weight < 0]
        if excluded:
            lead.matched += f" | excluded: {', '.join(excluded)}"
        return lead

    def _pattern(self, word: str) -> re.Pattern:
        folded = re.escape(normalize(word))
        # Latin words need word boundaries ("it" must not match "with").
        # Arabic words attach prefixes (ال، و، ب), so plain substring is right there.
        return re.compile(rf"\b{folded}\b" if LATIN.search(folded) else folded)


def _drop_nested(hits: list) -> list:
    """Count "نظام اداره" once, not again for the "نظام" inside it."""
    words = [normalize(word) for word, _ in hits]
    return [
        hit for hit, word in zip(hits, words)
        if not any(word != other and word in other for other in words)
    ]


def normalize(text: str) -> str:
    text = ARABIC_MARKS.sub("", text.lower())
    return " ".join(text.translate(ARABIC_FOLDS).split())

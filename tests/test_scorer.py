from tender_radar.scorer import KeywordScorer, normalize
from tests.conftest import make_lead

SCORER = KeywordScorer({
    "strong": ["erp", "ai", "نظام اداره"], "weak": ["system", "نظام"], "exclude": ["cleaning"],
})


def test_strong_and_weak_words_add_up():
    lead = SCORER.score(make_lead(title="New ERP system"))
    assert lead.score == 4
    assert lead.matched == "erp, system"


def test_latin_words_need_word_boundaries():
    assert SCORER.score(make_lead(title="Supply of chairs with paint")).score == 0  # no "ai" inside "chairs"/"paint"


def test_exclude_subtracts_and_is_listed():
    lead = SCORER.score(make_lead(title="ERP for cleaning company"))
    assert lead.score == 3 - 5
    assert lead.matched.endswith("| excluded: cleaning")


def test_arabic_spelling_variants_match_and_nested_words_count_once():
    lead = SCORER.score(make_lead(title="توريد نظام إدارة الموارد"))  # hamza on إدارة
    assert lead.score == 3
    assert lead.matched == "نظام اداره"


def test_normalize_folds_marks_and_letters():
    assert normalize("مُنَصَّة  إدارة") == "منصه اداره"

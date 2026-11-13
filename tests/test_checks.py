from __future__ import annotations

from ai_news.pipeline import checks


def test_numbers_normalized_across_formats() -> None:
    assert checks.numbers_in("1 200 blessés") == {"1200"}
    assert checks.numbers_in("1,200 injured") == {"1200"}
    assert checks.numbers_in("0,25 point") == checks.numbers_in("0.25 point")
    assert checks.numbers_in("le 23 octobre 2026") == {"23", "2026"}


def test_separate_numbers_not_merged() -> None:
    assert checks.numbers_in("en 2025, 300 personnes") == {"2025", "300"}
    assert checks.numbers_in("14 ou 16 pays") == {"14", "16"}


def test_single_digits_ignored() -> None:
    assert checks.numbers_in("3 morts") == set()


def test_drop_unverified_sentences() -> None:
    source = checks.numbers_in("Le bilan est de 12 morts selon la police.")
    text = "Le bilan est de 12 morts. Il y aurait 40 blessés. La police enquête."
    cleaned, dropped = checks.drop_unverified_sentences(text, source)
    assert dropped == 1
    assert cleaned == "Le bilan est de 12 morts. La police enquête."


def test_sensational_terms_detected() -> None:
    assert checks.sensational_terms("Un bilan CHOC et des images spectaculaires") == {
        "choc",
        "spectaculaires",
    }
    assert checks.sensational_terms("Le parlement adopte le budget.") == set()


def test_word_count_and_read_minutes() -> None:
    assert checks.word_count("L'Assemblée a voté", "aujourd'hui") == 4
    assert checks.read_minutes(0, 230) == 1
    assert checks.read_minutes(231, 230) == 2

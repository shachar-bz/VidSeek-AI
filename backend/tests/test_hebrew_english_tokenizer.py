"""Tests for how Hebrew and English text is split into the terms lexical search compares."""

from backend.services.lexical_search import tokenize


def test_english_is_casefolded_and_split_on_punctuation():
    assert tokenize("Hello, WORLD! Python-3") == ["hello", "world", "python", "3"]


def test_nfkc_folds_full_width_letters():
    assert tokenize("ＰＹＴＨＯＮ") == ["python"]


def test_niqqud_and_cantillation_are_stripped():
    assert tokenize("גָּדוֹל") == tokenize("גדול") == ["גדול"]
    assert tokenize("בְּרֵאשִׁ֖ית") == ["בראשית", "ראשית"]


def test_maqaf_separates_words():
    assert tokenize("כל־אחד") == ["כל", "אחד"]


def test_gershayim_acronym_becomes_one_term_whatever_the_quote():
    for spelling in ('צה"ל', "צה״ל", "צה“ל", "צה”ל"):
        assert tokenize(spelling) == ["צהל"], spelling


def test_geresh_inside_word_is_removed():
    assert tokenize("ג׳ורג׳ אמר") == ["גורג", "אמר"]


def test_quotes_outside_words_separate():
    assert tokenize('"hello" \'world\'') == ["hello", "world"]
    assert tokenize("אמר ״טוב״") == ["אמר", "טוב"]


def test_hebrew_prefix_yields_original_then_unprefixed():
    assert tokenize("בפייתון") == ["בפייתון", "פייתון"]
    assert tokenize("והמחשב") == ["והמחשב", "המחשב"]


def test_short_hebrew_word_keeps_its_first_letter():
    assert tokenize("בה") == ["בה"]
    assert tokenize("שלו") == ["שלו", "לו"]


def test_word_without_prefix_letter_has_no_variant():
    assert tokenize("פייתון") == ["פייתון"]


def test_final_form_letters_are_kept():
    assert tokenize("מחשבים") == ["מחשבים", "חשבים"]


def test_mixed_hebrew_and_english():
    assert tokenize("למדנו Python ב־2024 בכיתה") == [
        "למדנו",
        "מדנו",
        "python",
        "ב",
        "2024",
        "בכיתה",
        "כיתה",
    ]


def test_numbers_are_terms_and_decimal_point_splits():
    assert tokenize("version 16 costs 3.5") == ["version", "16", "costs", "3", "5"]


def test_underscore_separates():
    assert tokenize("snake_case") == ["snake", "case"]


def test_empty_and_punctuation_only_text():
    assert tokenize("") == []
    assert tokenize(" ,.!? ") == []

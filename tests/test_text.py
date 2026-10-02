from datetime import date

from reg.core.model import HistEntry, ParsedDoc, Prov
from reg.core.text import Joiner, clean, parse_dot_date, split_notes


def test_clean_strips_controls_and_spaces():
    assert clean("\x0b제1조　(목적)  이  규정") == "제1조 (목적) 이 규정"


def test_split_notes_extracts_amendment_annotations():
    text, notes = split_notes("증빙서를 제출하여야 한다. <개정 '19.1.21., 2020.11.6.> [본조신설 '07.12.28]")
    assert text == "증빙서를 제출하여야 한다."
    assert notes == ["<개정 '19.1.21., 2020.11.6.>", "[본조신설 '07.12.28]"]


def test_parse_dot_date_variants():
    assert parse_dot_date("2024. 1. 17.") == date(2024, 1, 17)
    assert parse_dot_date("<2023.12.21.>") == date(2023, 12, 21)
    assert parse_dot_date("20260911") == date(2026, 9, 11)
    assert parse_dot_date("'19.1.21.") == date(2019, 1, 21)
    assert parse_dot_date("없음") is None


def test_joiner_merges_mid_word_and_spaces_known_words():
    j = Joiner(["7일 이내에 출장을 확인할 수 있다", "실비로 지급한 여비 항목", "이 규정은"])
    assert j.join("7일 이내에 출", "장을 확인") == "7일 이내에 출장을 확인"   # '출'은 사전에 없음 → 붙임
    assert j.join("실비로 지급한", "여비 항목") == "실비로 지급한 여비 항목"   # '지급한'은 어절 → 띄움
    assert j.join("7일 이", "내에 출장") == "7일 이내에 출장"                  # 합친 '이내에'가 사전에 있음 → 붙임
    assert j.join("다음과 같다.", "1. 운임") == "다음과 같다. 1. 운임"


def test_parsed_doc_roundtrip():
    d = ParsedDoc("여비규정", "2120", [HistEntry("개정", date(2024, 1, 17), "339")],
                  [Prov("a1", "article", "제1조", "목적", "이 규정은", meta={"x": 1})], {"k": "v"})
    assert ParsedDoc.from_json(d.to_json()) == d

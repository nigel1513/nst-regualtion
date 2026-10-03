import pytest

from reg.compare.normalize import majority, normalize, path_label, quote_span, value_supported


@pytest.mark.parametrize("value,rule,want", [
    ("7일", "duration", "7일"), ("7일 이내", "duration", "7일"), ("2주", "duration", "14일"), ("1주일", "duration", "7일"),
    ("3개월", "duration", "3개월"), ("5년", "duration", "5년"), ("다음 달 10일까지", "duration", "다음달10일까지"),
    ("50,000원", "won", "50000"), ("5만원", "won", "50000"), ("2천만원", "won", "20000000"),
    ("2,000만원", "won", "20000000"), ("1억 5천만원", "won", "150000000"), ("20,000천원", "won", "20000000"),
    ("실비", "won", "실비"), ("있음", "boolean", "있음"), ("필요", "boolean", "있음"), ("없음", "boolean", "없음"),
    ("불가", "boolean", "없음"), (" 1월 1일 ~ 12월 31일 ", "text", "1월1일~12월31일"), ("", "text", None),
])
def test_normalize(value, rule, want):
    assert normalize(value, rule) == want


def test_value_must_be_in_quote_for_numbers():
    assert value_supported("7일", "duration", "출장 종료일 다음 날을 기점으로 7일 이내에 증빙서를 제출")
    assert not value_supported("10일", "duration", "출장 종료일 다음 날을 기점으로 7일 이내에")
    assert value_supported("2천만원", "won", "추정가격이 2,000만원 이하인 물품")
    assert value_supported("1주", "duration", "1주일 이내")
    assert value_supported("있음", "boolean", "아무 글")           # 숫자 없는 규칙은 인용 일치로만 본다
    assert not value_supported("5만원", "won", "숙박비는 실비로 지급한다")


def test_majority_needs_two_and_a_unique_top():
    assert majority(["7일", "7일", "5일", None]) == ("7일", 2)
    assert majority(["7일", "5일"]) is None
    assert majority(["7일", "7일", "5일", "5일"]) is None
    assert majority(["7일", "7일", "7일"]) == ("7일", 3)


def test_path_label():
    assert path_label("a27") == "제27조"
    assert path_label("a27.p1") == "제27조 제1항"
    assert path_label("a3-2.p2.i3-2.s가") == "제3조의2 제2항 제3호의2 가목"
    assert path_label("annex1") == "별표 1"
    assert path_label("annex2-1") == "별표 2의1"
    assert path_label("form3") == "별지 제3호서식"
    assert path_label("supp@2024-01-17/a1") == "부칙 제1조"


def test_quote_span_ignores_whitespace_and_returns_original_offsets():
    text = "① 출장자는 출장 종료일 다음 날을 기점으로\n7일 이내에 증빙서를 제출하여야 한다."
    s, e = quote_span("기점으로 7일 이내에", text)
    assert text[s:e] == "기점으로\n7일 이내에"
    assert quote_span("없는 구절", text) is None

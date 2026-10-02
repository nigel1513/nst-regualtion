# tests/core/test_text_m66.py
from reg.core.text import Joiner, clean, despace_line, lexicon, normalize_glyphs


def test_packaged_lexicon_is_loaded():
    lex = lexicon()
    assert len(lex) > 20_000 and lex.get("필요한", 0) > 100 and lex.get("관하여필요한", 0) == 0


def test_joiner_spaces_known_words_and_glues_fragments():
    j = Joiner([])
    assert j.join("관하여", "필요한 사항을") == "관하여 필요한 사항을"
    assert j.join("지휘 감독하", "며, 정보보안은") == "지휘 감독하며, 정보보안은"
    assert j.join("개인정", "보보호법") == "개인정보보호법"
    assert j.join("다음과 같다.", "1. 운임") == "다음과 같다. 1. 운임"  # 한글-한글 경계가 아니면 띄운다


def test_hwp_pua_quotes_middle_dots_and_rule_lines():
    assert normalize_glyphs("(이하\U000f0852연구회\U000f0853라 한다)") == "(이하“연구회”라 한다)"
    assert normalize_glyphs("설립\U0000f09e운영") == "설립·운영"
    assert clean(normalize_glyphs("(인) " + "\U000f081c" * 16)) == "(인)"
    assert normalize_glyphs("\U0000f0fe 신규 \U0000f06f 재신청") == "☑ 신규 □ 재신청"


def test_kist_f000_quotes_only_when_paired():
    assert normalize_glyphs("\U0000f000물품의 반출\U0000f000이라") == "“물품의 반출”이라"
    assert normalize_glyphs("성명 \U0000f000 서명") == "성명   서명"  # 짝이 없으면 지운다


def test_despace_whole_line_only():
    assert despace_line("소 액 구 매 신 청 서") == "소액구매신청서"
    assert despace_line("및 그 밖의 사항") == "및 그 밖의 사항"
    assert despace_line("검 토 의 견 서 (보안부서에서 기재)") == "검 토 의 견 서 (보안부서에서 기재)"

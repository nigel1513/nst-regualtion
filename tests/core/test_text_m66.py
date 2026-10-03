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


def test_tripled_glyph_runs_collapse():
    """굵은 글씨를 여러 번 겹쳐 찍은 PDF 제목: 같은 길이(3번 이상)로 반복된 글자가 3개 이상 이어질 때만 합친다."""
    krict = ("중" * 36 + " " + "소" * 36 + " " + "기" * 36 + " " + "업" * 36 + " " + "준" * 36
             + "지" * 20 + "원" * 20 + " " + "사" * 20 + "업" * 20 + " 1. 목적")
    assert normalize_glyphs(krict) == "중 소 기 업 준지원 사업 1. 목적"
    assert normalize_glyphs("[별지 제2-2호 서식] KKKRRRIIICCCTTT 멤멤멤버버버십십십기기기업업업 지지지정정정서서서업체명 :") \
        == "[별지 제2-2호 서식] KRICT 멤버십기업 지정서업체명 :"
    assert normalize_glyphs("출출출 자자자 기기기 업업업 설설설 립립립 절절절 차차차 □ 내부절차순서") \
        == "출 자 기 업 설 립 절 차 □ 내부절차순서"
    assert normalize_glyphs("1부. 출출출자자자예예예정정정 기기기술술술 및및및 출출출자자자회회회사사사") == "1부. 출자예정 기술 및 출자회사"


def test_natural_repeats_and_table_cells_are_kept():
    for s in ("전기기기 설계용 공학 소프트웨어", "금품향응수수수동강등", "구 분년년년자본금매출액",
              "감 사담당장장장원장결재", "특허국제등록건건건건건건건건건건건건건건국내등록건건건건건건건건건건건건건건",
              "보단터터터팀팀팀설팀팀팀팀팀",  # 표 칸의 세로 글자: 두 덩어리뿐이라 그대로
              "QA - " + "년" * 30 + " " + "도" * 30, "OOOOOO OOO OOO", "042 yyy zzzz", "YYYY YYYY YYYY",
              "부부부로로로로로개부부연"):
        assert normalize_glyphs(s) == s, s

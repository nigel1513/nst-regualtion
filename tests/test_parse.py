from datetime import date
from pathlib import Path

from reg.core.extract import extract
from reg.core.model import Block
from reg.core.parse import parse_blocks

S = Path(__file__).parent / "fixtures" / "samples"


def kasi():
    return parse_blocks(extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf"))


def nst():
    return parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))


def test_kasi_header_and_history():
    d = kasi()
    assert d.title == "여비규정" and d.class_code == "2120"
    assert d.history[0].kind == "제정" and d.history[0].date == date(1999, 12, 21)
    assert (d.history[-1].kind, d.history[-1].date, d.history[-1].number) == ("개정", date(2024, 1, 17), "339")


def test_kasi_chapters_from_body_not_toc():
    d = kasi()
    chapters = [p for p in d.provisions if p.unit == "chapter"]
    assert [c.path for c in chapters] == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert chapters[0].heading == "총칙" and chapters[0].anchor["page"] > 3  # 목차(앞쪽)가 아니라 본문 위치


def test_kasi_article_27_paragraphs():
    d = kasi()
    a27 = d.get("a27")
    assert a27.heading == "출장증빙의 제출" and a27.parent == "c6" and a27.anchor["page"] == 12
    p1 = d.get("a27.p1")
    assert p1.label == "①" and "출장 종료일 다음 날을 기점으로 7일 이내에 출장을 확인할 수 있는 증빙서를" in p1.text
    assert any("2020.11.6" in n for n in p1.annotations) and "<개정" not in p1.text
    assert any("본조신설" in n for n in a27.annotations)
    assert [p.path for p in d.children("a27")] == ["a27.p1", "a27.p2", "a27.p3"]


def test_kasi_branch_article_and_items():
    d = kasi()
    assert d.get("a4-2").heading == "여비의 정산"
    items = d.children("a26.p1")
    assert [i.label for i in items][:3] == ["1.", "2.", "3."] and items[1].deleted


def test_reference_at_line_start_is_not_an_article():
    blocks = [Block("제1조(목적) 이 규정은 목적을 정한다."), Block("제2조(적용) ① 이 규정은"),
              Block("제13조의 근무지내 출장에 적용한다."), Block("제3조(기타) 끝.")]
    d = parse_blocks(blocks)
    assert [p.path for p in d.provisions if p.unit == "article"] == ["a1", "a2", "a3"]
    assert "제13조의 근무지내 출장" in d.get("a2.p1").text


def test_supplement_articles_do_not_override_body():
    d = kasi()
    assert d.get("a1").heading == "목적"
    supps = d.supplements()
    assert supps[-1].path == "supp@2024-01-17" and "2024년 1월 17일부터 시행한다" in supps[-1].text


def test_nst_inline_paragraphs_deleted_article_and_duplicate_supplements():
    d = nst()
    assert d.title == "여비규정"
    assert [p.path for p in d.children("a4")] == ["a4.p1", "a4.p2"]
    assert d.get("a7").deleted
    assert "10일 이내" in d.get("a9-2").text
    paths = [s.path for s in d.supplements()]
    assert paths[-1] == "supp@2023-12-21" and len(paths) == len(set(paths)) == 19


def test_duplicate_supplement_dates_get_distinct_paths():
    d = parse_blocks([Block("제1조(목적) 목적."), Block("부 칙 <2023.12.21.>"), Block("이 규정은 공포한 날부터 시행한다."),
                      Block("부 칙 <2023.12.21.>"), Block("제1조(시행일) 이 규정은 2024년 1월 2일부터 시행한다.")])
    assert [s.path for s in d.supplements()] == ["supp@2023-12-21", "supp@2023-12-21~2"]
    assert d.get("supp@2023-12-21~2/a1").heading == "시행일"


def _arts(d):
    return [p.path for p in d.provisions if p.unit == "article"]


def test_review_date_wrap_is_not_an_item():
    d = parse_blocks([Block("제1조(목적) 목적이다."), Block("배율은"), Block("3.5배로 한다."),
                      Block("부 칙 <2024.3.1.>"), Block("이 규정은"), Block("2024. 3. 1.부터 시행한다.")])
    assert not any(p.unit == "item" for p in d.provisions)
    assert "2024. 3. 1.부터 시행한다" in d.get("supp@2024-03-01").text


def test_review_body_line_starting_with_buchik_is_not_a_supplement():
    d = parse_blocks([Block("제1조(목적) 목적."), Block("부칙 제3조에 따른 경과조치는 다음과 같다."), Block("제2조(정의) 정의.")])
    assert _arts(d) == ["a1", "a2"] and d.supplements() == []


def test_review_wrapped_reference_with_heading_is_not_an_article():
    d = parse_blocks([Block("제1조(목적) 목적."), Block("제2조(정의) 정의는"), Block("제9조(징계)에 따른 절차를 따른다."),
                      Block("제3조(적용) 적용.")])
    assert _arts(d) == ["a1", "a2", "a3"]


def test_review_toc_with_headings_does_not_displace_body():
    d = parse_blocks([Block("어떤 규정"), Block("제1조(목적)"), Block("제2조(정의)"), Block("제3조(적용)"),
                      Block("제1조(목적) 이 규정은 목적을 정한다."), Block("제2조(정의) 정의는 다음과 같다."), Block("제3조(적용) 적용한다.")])
    assert _arts(d) == ["a1", "a2", "a3"] and d.get("a1").text == "이 규정은 목적을 정한다."
    assert d.meta["toc"] == ["a1", "a2", "a3"]


def test_class_code_with_spaces_and_hyphen():
    d = parse_blocks([Block("초빙연구원 운영기준"), Block("( 원규분류기호 : 기 - 21 )"), Block("제1조(목적) 목적.")])
    assert d.class_code == "기-21"

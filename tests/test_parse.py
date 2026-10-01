from datetime import date
from pathlib import Path

from reg.extract import extract
from reg.structure.model import Block
from reg.structure.parse import parse_blocks

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

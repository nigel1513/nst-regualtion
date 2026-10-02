from datetime import date
from pathlib import Path

from reg.core.extract import extract
from reg.core.effective import resolve
from reg.core.model import Block, HistEntry, ParsedDoc, Prov
from reg.core.parse import parse_blocks

S = Path(__file__).parent / "fixtures" / "samples"


def test_kasi_real_file_confirmed():
    d = parse_blocks(extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf"))
    e = resolve(d, alio_date=date(2024, 1, 17))
    assert (e.effective_from, e.basis, e.status) == (date(2024, 1, 17), "supplement", "CONFIRMED")


def test_nst_promulgation_date_in_parentheses():
    d = parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))
    e = resolve(d)
    assert e.effective_from == date(2024, 1, 2) and e.promulgated_on == date(2023, 12, 21)
    assert e.status == "CONFIRMED"


def doc(hist, supps):
    provs = [Prov(f"supp@{dt}", "supplement", "부칙", text=t, meta={"date": dt}) for dt, t in supps]
    return ParsedDoc("x", None, [HistEntry("개정", h) for h in hist], provs)


def test_publication_day_uses_supplement_header_date():
    e = resolve(doc([date(2022, 3, 1)], [("2022-03-01", "이 규정은 공포한 날부터 시행한다.")]))
    assert (e.effective_from, e.status) == (date(2022, 3, 1), "CONFIRMED")


def test_conflict_when_history_and_supplement_disagree():
    e = resolve(doc([date(2022, 3, 1)], [("2022-05-01", "이 규정은 2022년 5월 1일부터 시행한다.")]))
    assert e.status == "CONFLICT" and e.effective_from == date(2022, 5, 1)


def test_history_only_is_uncertain():
    e = resolve(doc([date(2021, 1, 5)], []))
    assert (e.effective_from, e.basis, e.status) == (date(2021, 1, 5), "history", "UNCERTAIN")


def test_filename_fallback_and_overrides():
    e = resolve(doc([], []), filename="연구사업 관리규정(2020년 12월 개정).pdf")
    assert e.basis == "filename" and e.effective_from is None and e.status == "UNCERTAIN"
    e2 = resolve(doc([date(2022, 1, 1)], [("2022-01-01",
        "이 규정은 2022년 1월 1일부터 시행한다. 다만, 제5조 및 제7조의2는 2022년 7월 1일부터 시행한다.")]))
    assert e2.overrides == {"a5": date(2022, 7, 1), "a7-2": date(2022, 7, 1)}


def test_law_meta_is_api_confirmed():
    d = ParsedDoc("법", None, [], [], {"effective_on": "2026-09-11", "promulgated_on": "2026-03-10"})
    e = resolve(d)
    assert (e.effective_from, e.basis, e.status, e.promulgated_on) == (
        date(2026, 9, 11), "api", "CONFIRMED", date(2026, 3, 10))


def test_real_phrasings_of_approval_day():
    cases = [
        ("2019-03-14", "이 규칙은 이사장 결재를 받은 날(2019년 3월 14일)부터 시행한다.", date(2019, 3, 14)),
        ("2018-05-10", "이 규칙은 이사장 결재를 받은 날(2018년 5월 10일) 부터 시행한다.", date(2018, 5, 10)),
        ("2018-05-18", "이 규정은 이사회의 의결을 받은 날(2018.05.18.)부터 시행한다. 다만, 제20조제3항의 개정규정은"
                       " 2018년 5월 29일부터 시행한다.", date(2018, 5, 18)),
        ("2020-02-01", "이 기준은 이사회의 의결을 거쳐 연구기관에 통보한 날부터 시행한다.", date(2020, 2, 1)),
        ("2021-07-01", "이 규정은 공포한 날로부터 시행한다.", date(2021, 7, 1)),
    ]
    for header, text, want in cases:
        e = resolve(doc([date.fromisoformat(header)], [(header, text)]))
        assert (e.effective_from, e.basis) == (want, "supplement"), text


def test_review_supplement_article_paragraphs_are_read():
    d = parse_blocks([Block("제1조(목적) 목적."), Block("제2조(정의) 정의."), Block("부 칙 <2024.3.1.>"),
                      Block("제1조(시행일) ① 이 규정은 2024년 3월 1일부터 시행한다."),
                      Block("② 다만, 제2조는 2024년 6월 1일부터 시행한다.")])
    e = resolve(d)
    assert e.effective_from == date(2024, 3, 1) and e.overrides == {"a2": date(2024, 6, 1)}


def test_review_alio_date_equal_to_supplement_header_is_not_conflict():
    e = resolve(doc([], [("2024-01-01", "이 규정은 2024년 2월 1일부터 시행한다.")]), alio_date=date(2024, 1, 1))
    assert (e.effective_from, e.status) == (date(2024, 2, 1), "CONFIRMED")

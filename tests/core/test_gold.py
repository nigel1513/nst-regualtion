# tests/core/test_gold.py
"""M6-6 회귀 정답셋 (tests/core/fixtures/gold). 실데이터에서 뽑은 줄·조문·PDF 쪽으로 추출·파싱·참조를 확인한다.

섹션별 테스트는 그 기능을 만드는 Task가 이 파일 아래에 더한다 (Task 2 pdf, Task 3 joins·glyphs·despace,
Task 4 parse, Task 5·6 refs)."""
import json

from tests.core.helpers import FX, PDF

GOLD = json.loads((FX / "gold" / "gold.json").read_text(encoding="utf-8"))


def test_gold_file_is_well_formed():
    assert {"joins", "despace", "parse", "pdf", "refs"} <= set(GOLD)
    assert len(GOLD["joins"]) + len(GOLD["despace"]) + len(GOLD["parse"]) + len(GOLD["pdf"]) + len(GOLD["refs"]) >= 30
    assert all((PDF / c["file"]).exists() for c in GOLD["pdf"])
    assert len({r["id"] for r in GOLD["refs"]}) == len(GOLD["refs"])


import re

import pytest

from reg.core.extract.pdf import extract_pdf


@pytest.mark.parametrize("case", [c for c in GOLD["pdf"] if "order" in c], ids=lambda c: c["file"])
def test_gold_pdf(case):
    lines = [b.text for b in extract_pdf((PDF / case["file"]).read_bytes())]
    pos = [next(i for i, t in enumerate(lines) if t.startswith(h)) for h in case["order"]]
    assert pos == sorted(pos)
    assert not [t for t in lines if re.search(case["absent_re"], t)]


from reg.core.text import Joiner, clean, despace_line, normalize_glyphs

# HWP·PDF 사용자 정의 영역 글리프 (JSON에 넣기 어려워 여기 둔다). 출처: 실서버 판본 텍스트
GLYPHS = [
    ("국가과학기술연구회(이하\U000f0852연구회\U000f0853라 한다)", "국가과학기술연구회(이하“연구회”라 한다)"),  # NST 판공비류사용기준 a1
    ("정부출연연구기관 등의 설립\U0000f09e운영 및 육성", "정부출연연구기관 등의 설립·운영 및 육성"),        # NST 기본사업운영규정 a1
    ("\U0000f000물품의 반출\U0000f000이라 함은 일상 운행하는", "“물품의 반출”이라 함은 일상 운행하는"),      # KIST 비유동자산관리요령 a33
    ("년 월 일신 청 인 (인) " + "\U000f081c" * 16, "년 월 일신 청 인 (인)"),                              # KIST 유연근무제운영지침 annex1
    ("신청서 등록구분 \U0000f0fe 신규 \U0000f06f 재신청", "신청서 등록구분 ☑ 신규 □ 재신청"),              # NST 정보보안업무규칙 annex3
]


@pytest.mark.parametrize("case", GOLD["joins"], ids=lambda c: f"{c['prev']}+{c['next']}")
def test_gold_joins(case):
    out = Joiner([]).join(case["prev"], case["next"])
    glued = not out[len(case["prev"]):].startswith(" ")
    assert glued == (case["want"] == "glue")


@pytest.mark.parametrize(("raw", "want"), GLYPHS)
def test_gold_glyphs(raw, want):
    assert clean(normalize_glyphs(raw)) == want


@pytest.mark.parametrize("case", GOLD["despace"], ids=lambda c: c["in"])
def test_gold_despace(case):
    assert despace_line(case["in"]) == case["want"]


@pytest.mark.parametrize("case", [c for c in GOLD["pdf"] if "contains" in c], ids=lambda c: c["file"])
def test_gold_pdf_glyphs(case):
    lines = [b.text for b in extract_pdf((PDF / case["file"]).read_bytes())]
    assert any(case["contains"] in clean(normalize_glyphs(t)) for t in lines)


from reg.core.model import Block
from reg.core.parse import parse_blocks


@pytest.mark.parametrize("case", GOLD["parse"], ids=lambda c: c["source"][:30])
def test_gold_parse(case):
    doc = parse_blocks([Block(t) for t in case["lines"]])
    for path, want in case["want"].items():
        p = doc.get(path)
        assert p is not None, path
        for k, v in want.items():
            if k == "text_endswith":
                assert p.text.endswith(v)
            elif k == "text_startswith":
                assert p.text.startswith(v)
            else:
                assert getattr(p, k) == v, (path, k)


from reg.core.ingest.loader import norm_title
from reg.core.model import Prov
from reg.core.refs import INST_WORDS, RefContext, collect_abbreviations, collect_definitions, extract_refs, match_title

REFS_TASK5 = {"R3", "R4", "R5", "R6", "R10", "R11", "R12", "R13", "R14"}


def classify(r, case) -> str:
    """참조 후보 → 'self' | work id | 'ext:이름' | 'none' (resolve_and_store와 같은 규칙, DB 없이)."""
    if r.kind in ("internal", "annex"):
        return "self"
    if r.kind == "delegation":
        return "none"
    titles: dict[str, list[str]] = {}
    for wid, t in case["titles"].items():
        titles.setdefault(norm_title(t), []).append(wid)
    code, name = case["institution"]
    defs = collect_definitions(case.get("doc_texts", []) + [case["text"]])
    prefixes = frozenset({norm_title(name), code, *INST_WORDS}
                         | {norm_title(k) for k, v in defs.items() if norm_title(v) == norm_title(name)})
    hits = match_title(r.name, titles, prefixes) if r.kind != "external" else titles.get(norm_title(r.name), [])
    if len(hits) == 1:
        return "self" if hits[0] == case["work"] else hits[0]
    return f"ext:{r.name}"


def check_ref_case(case):
    ctx = RefContext(collect_abbreviations(case.get("doc_texts", []) + [case["text"]]))
    refs = extract_refs(Prov(case["path"], case["unit"], "", case["heading"], case["text"]), ctx)
    got = [(r.evidence, r.rel_type, classify(r, case), r.target_path, r.kind) for r in refs]
    for w in case["want"]:
        match = [g for g in got if g[0] == w["evidence"] or g[0].endswith(w["evidence"])]
        assert match, (w, got)
        _ev, rel, target, path, _kind = match[0]
        if "rel" in w:
            assert rel == w["rel"], (w, got)
        if "target" in w:
            assert target == w["target"], (w, got)
        assert path == w["path"], (w, got)
    for p in case.get("forbid_self_paths", []):
        assert not [g for g in got if g[2] == "self" and g[3] == p], got
    for rel in case.get("forbid_rel", []):
        assert not [g for g in got if g[1] == rel], got
    for kind in case.get("forbid_kinds", []):
        assert not [g for g in got if g[4] == kind], got


@pytest.mark.parametrize("case", [c for c in GOLD["refs"] if c["id"] in REFS_TASK5], ids=lambda c: c["id"])
def test_gold_refs_extraction(case):
    check_ref_case(case)

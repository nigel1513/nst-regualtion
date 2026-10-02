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

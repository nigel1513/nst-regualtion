"""법령 범위 (필요한 법령만): 순수 선별 함수 + 인용 수 읽기 + CLI."""
import json

from reg.core.model import Prov
from reg.sources.lawgo.config import LawgoConfig, load_config
from reg.sources.lawgo.scope import (
    CHILD,
    CITED,
    CONFIG,
    KEPT,
    cited_law_counts,
    is_law_name,
    law_plan,
    plan_targets,
    select_rows,
)
from reg.sources.lawgo.xml import LawRow

SUFFIXES = ["법", "법률", "시행령", "시행규칙", "영", "에 관한 규정"]
EXCLUDE = ["법", "법률", "시행령", "시행규칙", "영", "동법", "같은 법", "동법 시행령"]
CHILDREN = ["시행령", "시행규칙"]


def plan(seeds=(), cited=None, cap=100, min_citations=1):
    return plan_targets(list(seeds), cited or {}, suffixes=SUFFIXES, exclude=EXCLUDE, children=CHILDREN,
                        max_targets=cap, min_citations=min_citations)


def row(law_id, name, abbr=None, status="현행", mst=None):
    return LawRow(mst or f"m{law_id}", law_id, name, abbr, "법률", None, None, None, None, None, status)


def test_is_law_name_takes_law_suffixes_and_drops_generic_or_internal_names():
    ok = ["근로기준법", "공공기관의 운영에 관한 법률", "개인정보 보호법 시행령", "산업안전보건법 시행규칙",
          "관공서의 공휴일에 관한 규정"]
    assert all(is_law_name(n, SUFFIXES, EXCLUDE) for n in ok)
    bad = ["법", "시행령", "동법", "같은법", "동법 시행령", "인사규정", "연구관리지침", "", None]
    assert not any(is_law_name(n, SUFFIXES, EXCLUDE) for n in bad)
    assert not is_law_name("계속기록방법", SUFFIXES, EXCLUDE, ["방법"]) and is_law_name("민법", SUFFIXES, EXCLUDE, ["방법"])


def test_plan_orders_config_then_cited_by_count_with_children_after_parent():
    p = plan(seeds=["국가재정법"], cited={"근로기준법": 5, "민법": 9, "인사규정": 50, "법": 99})
    names = [t.name for t in p.targets]
    assert names == ["국가재정법", "국가재정법 시행령", "국가재정법 시행규칙",
                     "민법", "민법 시행령", "민법 시행규칙",
                     "근로기준법", "근로기준법 시행령", "근로기준법 시행규칙"]
    t = p.by_norm()["민법시행령"]
    assert t.reasons == [CHILD] and t.parent == "민법"
    assert p.by_norm()["국가재정법"].reasons == [CONFIG]
    assert p.counts() == {"config": 1, "cited": 2, "child": 6, "total": 9, "dropped": 0}


def test_plan_merges_spacing_and_middle_dot_variants_and_seed_wins_name():
    p = plan(seeds=["개인정보 보호법"], cited={"개인정보보호법": 378, "개인정보 보호법": 559,
                                       "과학기술분야 정부출연연구기관 등의 설립ㆍ운영 및 육성에 관한 법률": 240,
                                       "과학기술분야 정부출연연구기관 등의 설립·운영 및 육성에 관한 법률": 100})
    first = p.targets[0]
    assert first.name == "개인정보 보호법" and first.reasons == [CONFIG, CITED] and first.citations == 937
    gri = [t for t in p.targets if t.norm.startswith("과학기술분야") and t.parent is None]
    assert len(gri) == 1 and gri[0].citations == 340 and "ㆍ" in gri[0].name  # 많이 쓴 표기를 이름으로


def test_cited_child_keeps_both_reasons_and_is_not_expanded_again():
    p = plan(cited={"국가연구개발혁신법": 928, "국가연구개발혁신법 시행령": 218})
    t = p.by_norm()["국가연구개발혁신법시행령"]
    assert t.reasons == [CHILD, CITED] and t.citations == 218 and t.parent == "국가연구개발혁신법"
    assert "국가연구개발혁신법시행령시행령" not in p.by_norm()
    assert len(p.targets) == 3


def test_plan_cap_drops_lowest_ranked_and_reports_them():
    p = plan(seeds=["가법"], cited={"나법": 10, "다법": 1}, cap=4)
    assert [t.name for t in p.targets] == ["가법", "가법 시행령", "가법 시행규칙", "나법"]
    assert [t.name for t in p.dropped] == ["나법 시행령", "나법 시행규칙", "다법", "다법 시행령", "다법 시행규칙"]
    assert p.counts()["dropped"] == 5


def test_min_citations_ignores_rare_names_but_not_config():
    p = plan(seeds=["가법"], cited={"나법": 1, "다법": 2}, min_citations=2)
    assert {t.name for t in p.targets if t.parent is None} == {"가법", "다법"}


def test_select_rows_matches_name_or_abbr_and_children_of_official_name():
    p = plan(seeds=["청탁금지법"], cited={"근로기준법": 3})
    rows = [row("1", "부정청탁 및 금품등 수수의 금지에 관한 법률", abbr="청탁금지법"),
            row("2", "부정청탁 및 금품등 수수의 금지에 관한 법률 시행령"),
            row("3", "근로기준법"), row("4", "근로기준법 시행령"),
            row("5", "도로교통법"), row("6", "근로기준법", status="연혁", mst="old")]
    sel = select_rows(p, rows)
    assert sorted(r.law_id for r in sel.rows) == ["1", "2", "3", "4"]
    assert sel.reasons["m2"] == [CHILD] and sel.reasons["m1"] == [CONFIG]
    st = sel.stats()
    assert st["selected"] == 4 and st["skipped"] == 1
    # 약칭으로 맞은 법령의 시행령은 정식 이름으로 찾았으므로 채워진 것으로 본다
    assert sorted(sel.unmatched) == ["근로기준법 시행규칙", "청탁금지법 시행규칙"] and st["unmatched_targets"] == 2


def test_select_rows_keeps_already_mirrored_laws_even_if_renamed():
    sel = select_rows(plan(), [row("9", "새 이름 법"), row("8", "무관법")], keep_ids={"9"})
    assert [r.law_id for r in sel.rows] == ["9"] and sel.reasons["m9"] == [KEPT]


def test_config_has_law_seed_list():
    cfg = load_config()
    for name in ("국가연구개발혁신법", "공무원 여비 규정", "보안업무규정", "국가재정법", "근로기준법",
                 "과학기술분야 정부출연연구기관 등의 설립·운영 및 육성에 관한 법률"):
        assert name in cfg.law_include
    assert cfg.law_children == ["시행령", "시행규칙"] and cfg.law_max_targets > 0
    assert "법" in cfg.law_cited_exclude and "법률" in cfg.law_cited_suffixes


def test_cited_counts_come_from_external_references_only(lconn, blob):
    from tests.sources.lawgo.helpers import load_reg

    load_reg(lconn, blob, "kr/reg/KASI/a", "인사규정",
             [Prov("a1", "article", "제1조", "목적", "「근로기준법」 제2조와 「근로기준법」 제3조, 「민법」 제5조에 따른다.")])
    load_reg(lconn, blob, "kr/reg/KASI/b", "복무규정",
             [Prov("a1", "article", "제1조", "목적", "「인사규정」 제1조에 따른다.")])
    lconn.commit()
    counts = cited_law_counts(lconn)
    assert counts["근로기준법"] == 2 and counts["민법"] == 1
    assert "인사규정" not in counts  # 같은 기관 work로 풀린 내부 인용
    p = law_plan(lconn, LawgoConfig(law_include=["국가재정법"], law_cited_suffixes=SUFFIXES,
                                    law_cited_exclude=EXCLUDE, law_children=CHILDREN, law_max_targets=100))
    assert [t.name for t in p.targets if t.parent is None] == ["국가재정법", "근로기준법", "민법"]


def test_cli_targets_prints_reasons_and_counts(monkeypatch, migrated, lconn, blob):
    from typer.testing import CliRunner

    from reg.cli import app
    from reg.platform.settings import get_settings
    from tests.sources.lawgo.helpers import load_reg

    load_reg(lconn, blob, "kr/reg/KASI/a", "인사규정",
             [Prov("a1", "article", "제1조", "목적", "「근로기준법」 제2조에 따른다.")])
    lconn.commit()
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    get_settings.cache_clear()
    try:
        out = CliRunner().invoke(app, ["law", "targets", "--json"])
        assert out.exit_code == 0, out.output
        d = json.loads(out.output)
        assert d["counts"]["config"] >= 15 and d["counts"]["cited"] >= 1
        t = next(x for x in d["targets"] if x["name"] == "근로기준법")
        assert set(t["reasons"]) == {CONFIG, CITED} and t["citations"] == 1
        text = CliRunner().invoke(app, ["law", "targets", "--top", "60"])
        assert text.exit_code == 0 and "근로기준법" in text.output and "config" in text.output
    finally:
        get_settings.cache_clear()
    assert not lconn.execute("SELECT 1 FROM ops.pipeline_run").fetchone()  # 읽기 전용: 실행 기록도 남기지 않는다

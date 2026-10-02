from pathlib import Path

import pytest

from reg.sources.lawgo.errors import ResponseChanged
from reg.sources.lawgo.xml import parse_admrul_xml

FX = Path(__file__).parent / "fixtures"


def doc():
    return parse_admrul_xml((FX / "admrul_2100000285346.xml").read_bytes())


def test_admrul_basic_info():
    d = doc()
    assert d.title == "영장심의위원회 운영세칙"
    assert d.meta == {"admrul_id": "75610", "promulgated_on": "2026-10-02", "effective_on": "2026-10-02",
                      "amendment_kind": "일부개정", "kind": "훈령", "promulgation_no": "1624", "ministry": "법무부"}


def test_admrul_articles_and_paragraphs():
    d = doc()
    arts = [p for p in d.provisions if p.unit == "article"]
    assert [a.path for a in arts] == [f"a{i}" for i in range(1, 12)]
    assert d.get("a1").heading == "목적" and d.get("a1").text.startswith("이 세칙은 영장심의위원회 규칙")
    assert d.get("a3").text == "" and d.get("a3.p2").label == "②"
    assert d.get("a3.p2").text.startswith("광역공소청장은 제1항에 따라") and d.get("a3.p2").parent == "a3"
    assert "<개정 2026. 9. 18.>" in d.get("a2").annotations
    assert len({p.path for p in d.provisions}) == len(d.provisions)


def test_admrul_supplements():
    paths = [s.path for s in doc().supplements()]
    assert paths == ["supp@2020-12-31", "supp@2026-10-02"]


def test_non_article_notice_and_chapters():
    xml = ('<?xml version="1.0" encoding="UTF-8"?><AdmRulService><행정규칙기본정보><행정규칙명>가고시</행정규칙명>'
           '<행정규칙ID>1</행정규칙ID><시행일자>20260101</시행일자></행정규칙기본정보>'
           '<조문내용><![CDATA[제1장 총칙]]></조문내용><조문내용><![CDATA[제1조의2(정의) 이 고시에서]]></조문내용>'
           '<조문내용><![CDATA[1. 지원 대상은 다음과 같다.]]></조문내용></AdmRulService>').encode()
    d = parse_admrul_xml(xml)
    assert d.get("c1").unit == "chapter" and d.get("a1-2").label == "제1조의2" and d.get("a1-2").parent == "c1"
    assert d.get("body3").unit == "article" and d.get("body3").label == "본문"


def test_admrul_structure_change():
    with pytest.raises(ResponseChanged, match="행정규칙기본정보"):
        parse_admrul_xml(b'<?xml version="1.0" encoding="UTF-8"?><AdmRulService/>')

"""검색 서비스의 기관 결정과 인용 조 고정 (search-inst): 가짜 OpenSearch로 보낸 질의를 본다."""
import reg.search.service as svc
from reg.search.citation import mentioned_institution
from reg.search.service import search
from tests.index.fakes import FakeEmbedder

ALIASES = {"KASI": ["한국천문연구원", "천문연구원", "천문연", "KASI"], "KBSI": ["한국기초과학지원연구원", "기초지원연", "KBSI"],
           "KIST": ["한국과학기술연구원", "KIST"], "KISTI": ["한국과학기술정보연구원", "KISTI"]}


def _unit(work, title, inst, path, text, score):
    vid = f"v-{work}"
    return {"_score": score, "_source": {
        "doc_id": f"{vid}|{path}", "work_id": f"kr/reg/{inst}/{work}", "version_id": vid, "base_path": path,
        "article_path": path.split(".")[0], "article_key": f"{vid}|{path.split('.')[0]}", "unit": "article",
        "label": "제27조", "full_label": f"{title} 제27조", "title": title, "institution": inst,
        "institution_name": inst, "family": "reg", "text": text, "article_text": text, "window": 0}}


SCHOOL = _unit("스쿨운영규정", "한국천문연구원 스쿨운영규정", "KASI", "a27", "제27조(여비) 여비는 …", 3.0)
TRAVEL = _unit("여비규정", "여비규정", "KASI", "a27", "제27조(출장증빙의 제출) 출장자는 …", 9.0)


class FakeOS:
    """하이브리드에는 hybrid 후보를, 번호 조회(article_no 필터)에는 lookup 후보를, 단위 조회에는 해당 조를 준다."""

    def __init__(self, hybrid=(), lookup=()):
        self.hybrid, self.lookup, self.bodies = list(hybrid), list(lookup), []

    def search(self, body, pipeline=None, index=None):
        self.bodies.append(body)
        q = body.get("query", {})
        if "hybrid" in q:
            return {"hits": {"hits": self.hybrid}}
        flt = q.get("bool", {}).get("filter", [])
        if any("article_no" in f.get("term", {}) for f in flt):
            return {"hits": {"hits": self.lookup}}
        keys = next((f["terms"]["article_key"] for f in flt if "article_key" in f.get("terms", {})), None)
        if keys is not None:
            return {"hits": {"hits": [h for h in [*self.hybrid, *self.lookup] if h["_source"]["article_key"] in keys]}}
        return {"hits": {"hits": []}}

    def hybrid_institution(self) -> set[str]:
        body = next(b for b in self.bodies if "hybrid" in b.get("query", {}))
        flt = body["query"]["hybrid"]["queries"][0]["bool"]["filter"]
        return {s["term"]["institution"] for f in flt for s in f.get("bool", {}).get("should", [])
                if "institution" in s.get("term", {})}


def _facets_spy(monkeypatch):
    seen = []
    monkeypatch.setattr(svc, "facet_counts", lambda os, q, inst, *a: seen.append(inst) or {})
    return seen


def test_mentioned_institution():
    assert mentioned_institution("천문연 출장 증빙", ALIASES) == "KASI"
    assert mentioned_institution("KISTI 출장", ALIASES) == "KISTI"          # KISTI 속 KIST는 언급이 아니다
    assert mentioned_institution("천문연과 KBSI 비교", ALIASES) is None      # 둘이면 정하지 않는다
    assert mentioned_institution("출장 증빙", ALIASES) is None
    assert mentioned_institution("천문연", None) is None


def test_citation_institution_filters_hybrid_and_facets(monkeypatch):
    seen = _facets_spy(monkeypatch)
    os = FakeOS(hybrid=[SCHOOL], lookup=[TRAVEL])
    search(os, FakeEmbedder(), None, "천문연 여비규정 27조", aliases=ALIASES, rerank=False)
    assert os.hybrid_institution() == {"KASI"} and seen == ["KASI"]


def test_plain_mention_filters_hybrid_and_facets(monkeypatch):
    seen = _facets_spy(monkeypatch)
    os = FakeOS()
    search(os, FakeEmbedder(), None, "천문연 출장 증빙", aliases=ALIASES, rerank=False)
    assert os.hybrid_institution() == {"KASI"} and seen == ["KASI"]


def test_explicit_institution_wins_over_mention(monkeypatch):
    seen = _facets_spy(monkeypatch)
    os = FakeOS()
    search(os, FakeEmbedder(), None, "천문연 출장 증빙", institution="KBSI", aliases=ALIASES, rerank=False)
    assert os.hybrid_institution() == {"KBSI"} and seen == ["KBSI"]


def test_ambiguous_mention_does_not_filter(monkeypatch):
    _facets_spy(monkeypatch)
    os = FakeOS()
    search(os, FakeEmbedder(), None, "천문연과 KBSI 출장 비교", aliases=ALIASES, rerank=False)
    assert os.hybrid_institution() == set()


def test_cited_article_is_first_hit(monkeypatch):
    _facets_spy(monkeypatch)
    os = FakeOS(hybrid=[SCHOOL], lookup=[TRAVEL])
    r = search(os, FakeEmbedder(), None, "천문연 여비규정 27조", aliases=ALIASES, rerank=False)
    assert r["lookup"][0]["title"] == "여비규정"
    assert [h["title"] for h in r["hits"]] == ["여비규정", "한국천문연구원 스쿨운영규정"]
    top = r["hits"][0]
    assert top["article_path"] == "a27" and top["units"] and "release_id" not in top


def test_cited_article_already_in_hits_moves_first(monkeypatch):
    _facets_spy(monkeypatch)
    os = FakeOS(hybrid=[SCHOOL, {**TRAVEL, "_score": 1.0}], lookup=[TRAVEL])   # 하이브리드에선 2위
    r = search(os, FakeEmbedder(), None, "천문연 여비규정 27조", aliases=ALIASES, rerank=False)
    assert [h["title"] for h in r["hits"]] == ["여비규정", "한국천문연구원 스쿨운영규정"]


def test_no_pin_without_institution_or_against_kind(monkeypatch):
    _facets_spy(monkeypatch)
    os = FakeOS(hybrid=[SCHOOL], lookup=[TRAVEL])
    r = search(os, FakeEmbedder(), None, "여비규정 27조", aliases=ALIASES, rerank=False)   # 어느 기관 것인지 모른다
    assert [h["title"] for h in r["hits"]] == ["한국천문연구원 스쿨운영규정"] and r["lookup"]
    os = FakeOS(hybrid=[], lookup=[TRAVEL])
    r = search(os, FakeEmbedder(), None, "천문연 여비규정 27조", kind="law", aliases=ALIASES, rerank=False)
    assert r["hits"] == []

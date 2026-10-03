"""주제 설정과 분류 (spec §4: 제목 규칙 → 임베딩 유사도, 규정당 최대 2개)."""
import math

import pytest

from reg.compare.classify import WorkText, classify, title_topics
from reg.compare.config import load


@pytest.fixture(scope="module")
def cfg():
    return load()


def test_config_has_all_topics_and_spec_items(cfg):
    labels = [t.label for t in cfg.topics]
    assert labels[:6] == ["회계·재무", "계약·구매", "인사", "복무", "보수·수당", "여비·출장"]
    assert len(cfg.topics) == 20 and cfg.topics[-1].id == "other"
    travel = [i.id for i in cfg.items["travel"]]
    assert travel == ["evidence_deadline", "settlement_deadline", "per_diem", "lodging_cap", "overseas_review"]
    assert cfg.item("travel", "per_diem").norm == "won"
    assert all(i.norm in ("duration", "won", "boolean", "text") for its in cfg.items.values() for i in its)
    assert set(cfg.items) <= {t.id for t in cfg.topics}
    assert cfg.topic("travel").label == "여비·출장"


@pytest.mark.parametrize("title,want", [
    ("여비규정", ["travel"]),
    ("연구개발능률성과급 지급지침", ["pay", "research"]),        # 머리말(끝 쪽) 낱말이 첫째
    ("연구개발적립금관리요령", ["accounting", "research"]),
    ("연수직운영지침", ["hr"]),                                  # 긴 낱말이 먼저 자리를 차지한다 (연수직 > 연수)
    ("학·연협동 연구 석·박사과정 운영규정", ["training"]),
    ("휴대용 저장매체 보안관리지침", ["security", "it"]),
    ("국외파견관리및체재비지급지침", ["travel", "hr"]),
    ("제정 1992-04-22", []),
])
def test_title_rules(cfg, title, want):
    assert [t for t, _ in title_topics(title, cfg.topics)] == want


class FakeEmbed:
    """주제 설명과 규정 글에 들어 있는 낱말로 만든 벡터 (결정적)."""
    WORDS = ("공익신고", "여비", "연봉", "복지")

    def __call__(self, texts):
        out = []
        for t in texts:
            v = [float(t.count(w)) for w in self.WORDS]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def test_classify_uses_embedding_when_title_is_broken(cfg):
    works = [WorkText("kr/reg/X/a", "여비규정", ""),
             WorkText("kr/reg/X/b", "<최종공포일 2022.8.19.>", "제1조(정의) 공익신고란 공익신고자 보호"),
             WorkText("kr/reg/X/c", "1차개정", ""),
             WorkText("kr/reg/X/d", "제정 1992-04-22",
                      "제1조(목적) 이 요령은 「인사규정」 제7조에 의거 안전성평가연구소(이하 “연구소”라 한다)의 여비 지급에 "
                      "관한 사항을 정함을 목적으로 한다.")]
    topics = [t for t in cfg.topics]
    topics[cfg.topics.index(cfg.topic("audit"))] = cfg.topic("audit").__class__(
        **{**cfg.topic("audit").__dict__, "description": "공익신고 공익신고 부패"})
    got = classify(works, topics, FakeEmbed(), min_sim=0.5)
    assert got["kr/reg/X/a"] == [("travel", 1.0, "title")]
    assert got["kr/reg/X/b"][0][0] == "audit" and got["kr/reg/X/b"][0][2] == "embedding"
    assert got["kr/reg/X/c"] == [("other", 0.0, "none")]
    # 목적 조항 규칙: 근거 규정(인사규정)과 기관명(안전성평가연구소의 '안전')은 주제로 보지 않는다
    assert got["kr/reg/X/d"] == [("travel", 0.8, "purpose")]

"""규정 도우미 (UI v2 §5) 단위 테스트: 컨테이너 없이 가짜 검색·LLM·DB로 의도·범위·인용·비교표·SSE를 본다."""
import json

import pytest

import reg.qa.chat as chat_mod
from reg.platform.llm import ProviderError
from reg.qa.chat import card, chat, collect, followups, is_lookup, mentions, plan, sse, standalone, verbatim

ALIASES = {"KASI": ["한국천문연구원", "천문연구원", "천문연", "KASI"], "KBSI": ["한국기초과학지원연구원", "기초지원연", "KBSI"],
           "KIST": ["한국과학기술연구원", "KIST"], "KISTI": ["한국과학기술정보연구원", "KISTI"]}
ALL = {"mode": "all"}


def only(*codes):
    return {"mode": "institutions", "institutions": list(codes)}


# ---------------------------------------------------------------- 범위·의도

def test_mentions_in_order_and_boundaries():
    assert mentions("KBSI랑 천문연 비교", ALIASES) == ["KBSI", "KASI"]
    assert mentions("KISTI 출장", ALIASES) == ["KISTI"]          # KISTI 속 KIST는 언급이 아니다
    assert mentions("출장 증빙", ALIASES) == []


@pytest.mark.parametrize("q,scope,intent,insts,focus", [
    ("천문연 여비규정 27조", ALL, "lookup", ["KASI"], "KASI"),
    ("여비규정 제27조 제1항", ALL, "lookup", None, None),
    ("천문연 여비규정", ALL, "lookup", ["KASI"], "KASI"),
    ("출장 다녀온 지 10일 지났는데 증빙 안 냈어요", only("KASI"), "question", ["KASI"], "KASI"),
    ("천문연 출장 증빙 기한은?", ALL, "question", ["KASI"], "KASI"),              # 언급이 범위를 좁힌다
    ("천문연 출장 증빙 기한은?", only("KBSI"), "question", ["KBSI"], "KBSI"),     # 선택이 언급보다 우선
    ("출장 증빙은 출장 후 며칠 안에 내야 하나요? 다른 기관도", ALL, "comparison", None, None),
    ("출장 증빙 기한은?", ALL, "comparison", None, None),                          # 전체 범위·기관 없음
    ("출장 증빙 기한은? 다른 기관도 알려 주세요", only("KASI"), "comparison", None, "KASI"),
    ("천문연과 KBSI 출장 증빙 기한", ALL, "comparison", ["KASI", "KBSI"], None),
    ("출장 증빙 기한", only("KASI", "KBSI"), "comparison", ["KASI", "KBSI"], None),
    ("천문연 수의계약 비교견적 생략 기준은?", ALL, "question", ["KASI"], "KASI"),   # 비교견적은 비교 요청이 아니다
    ("천문연 여비규정 27조에 따르면 증빙 기한은?", ALL, "question", ["KASI"], "KASI"),
    # 전체 범위·기관 없음: 비교할 값(기한·금액·횟수…)이나 비교 표현이 있을 때만 비교, 아니면 전체 기관 질문
    ("연구장비 구매 절차", ALL, "question", None, None),
    ("연구노트는 어떻게 작성하나요?", ALL, "question", None, None),
    ("국내 출장 숙박비 상한은 얼마인가요?", ALL, "comparison", None, None),
    ("수의계약 한도 금액", ALL, "comparison", None, None),
    ("연차는 언제까지 써야 하나요?", ALL, "comparison", None, None),
    ("어디가 유연근무 신청이 쉬운가요?", ALL, "comparison", None, None),
    ("연구장비 구매 절차를 기관별로 알려 주세요", ALL, "comparison", None, None),
])
def test_plan(q, scope, intent, insts, focus):
    p = plan(q, scope, ALIASES)
    assert (p["intent"], p["institutions"], p["focus"]) == (intent, insts, focus)


def test_unknown_selected_institution_is_ignored():
    assert plan("출장 증빙 기한은?", only("NOPE"), ALIASES)["intent"] == "comparison"


def test_is_lookup_rejects_questions_and_plain_topics():
    assert is_lookup("천문연 여비규정 27조", ALIASES)
    assert not is_lookup("연구장비 구매 절차", ALIASES)
    assert not is_lookup("여비규정 27조는 무슨 내용인가요?", ALIASES)


# ---------------------------------------------------------------- 후속 질문 바꾸기

class RewriteLLM:
    def __init__(self, out="질문: 한국천문연구원 출장 증빙 제출 기한은 KBSI도 같은가요?", fail=False):
        self.out, self.fail, self.calls = out, fail, []

    def regex(self, messages, pattern, **kw):
        self.calls.append(messages)
        if self.fail:
            raise ProviderError("down")
        return self.out


def _msgs(*turns):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": t} for i, t in enumerate(turns)]


def test_standalone_rewrites_follow_up_with_context():
    llm = RewriteLLM(out="질문: 천문연 출장 증빙 기한 안에 못 내면 어떻게 되나요?")
    q, rw = standalone(llm, _msgs("천문연 출장 증빙 기한은?", "7일 이내입니다.", "그럼 기한 안에 못 내면 어떻게 되나요?"), ALIASES)
    assert rw and q == "천문연 출장 증빙 기한 안에 못 내면 어떻게 되나요?" and len(llm.calls) == 1
    assert "천문연 출장 증빙 기한은?" in llm.calls[0][1]["content"] and "7일 이내입니다." in llm.calls[0][1]["content"]


def test_standalone_rejects_rewrite_that_invents_a_topic():
    llm = RewriteLLM(out="질문: KBSI의 연구비 사용 실적 보고 기한은 어떻게 되나요?")
    q, rw = standalone(llm, _msgs("천문연 출장 증빙 기한은?", "7일 이내입니다.", "그럼 늦으면요?"), ALIASES)
    assert rw and q == "천문연 출장 증빙 기한은? 그럼 늦으면요?"


def test_standalone_rules_for_institution_switch_and_compare_request():
    llm = RewriteLLM(fail=True)
    q, _ = standalone(llm, _msgs("천문연 출장 증빙 기한은?", "7일", "KBSI는요?"), ALIASES)
    assert q == "한국기초과학지원연구원 출장 증빙 기한은?" and plan(q, ALL, ALIASES)["institutions"] == ["KBSI"]
    q, _ = standalone(llm, _msgs("천문연 출장 증빙 기한은?", "7일", "다른 기관도요?"), ALIASES)
    assert q == "천문연 출장 증빙 기한은? 다른 기관도" and plan(q, ALL, ALIASES)["intent"] == "comparison"
    assert llm.calls == []


def test_standalone_keeps_complete_question_without_llm_call():
    llm = RewriteLLM()
    assert standalone(llm, _msgs("천문연 출장 증빙 기한은?", "7일", "연구장비 구매 절차")) == ("연구장비 구매 절차", False)
    assert standalone(llm, _msgs("천문연 출장 증빙 기한은?")) == ("천문연 출장 증빙 기한은?", False)
    assert llm.calls == []


def test_standalone_falls_back_to_previous_question():
    q, rw = standalone(RewriteLLM(fail=True), _msgs("천문연 출장 증빙 기한은?", "7일", "다른 기관도 같나요?"))
    assert rw and q == "천문연 출장 증빙 기한은? 다른 기관도 같나요?"
    assert plan(q, ALL, ALIASES)["intent"] == "comparison"


# ---------------------------------------------------------------- 인용·카드·SSE

TEXT = "① 출장자는 출장을 마친 다음 날부터 7일 이내에 출장을 확인할 수 있는 증빙서를 회계담당부서에 제출하여야 한다."


def test_verbatim_quote_filter():
    assert verbatim("7일 이내에 출장을 확인할 수 있는 증빙서를", TEXT) == "7일 이내에 출장을 확인할 수 있는 증빙서를"
    assert verbatim("10일 이내에 출장을 확인할 수 있는 증빙서를", TEXT) is None          # 숫자가 다르면 버린다
    assert verbatim("출장 후 일주일 안에 영수증을 낸다", TEXT) is None                   # 말 바꾸기는 버린다
    got = verbatim("7일 이내에 출장을 확인할 수 있는 증빙서를 제출하여야 한다", TEXT)   # 줄여 쓴 인용 → 원문 구간
    assert got and got in TEXT and got.startswith("7일 이내에")


def test_card_snippet_highlights_and_href():
    h = {"work_id": "kr/reg/KASI/여비규정", "version_id": "v1", "path": "a27.p1", "article_path": "a27",
         "title": "여비규정", "institution": "KASI", "institution_name": "한국천문연구원", "family": "reg",
         "path_label": "제27조(출장증빙의 제출)", "text": TEXT, "score": 3.0, "rerank_score": 0.9,
         "matches": [{"path": "a27.p1", "label": "①", "highlight": "출장자는 <mark>7일</mark> 이내에 <mark>증빙서</mark>를"}]}
    c = card(h, "2025-01-01")
    assert c["snippet"] == "출장자는 7일 이내에 증빙서를"
    assert [c["snippet"][s:e] for s, e in c["highlights"]] == ["7일", "증빙서"]
    assert c["matched"] == [{"path": "a27.p1", "label": "제1항"}] and c["institution"]["code"] == "KASI"
    assert c["href"] == "/regulations/kr/reg/KASI/%EC%97%AC%EB%B9%84%EA%B7%9C%EC%A0%95?a=a27&as_of=2025-01-01#a27.p1"


def test_sse_framing():
    frame = sse("answer_delta", {"text": "한 줄\n두 줄"})
    assert frame.startswith("event: answer_delta\ndata: ") and frame.endswith("\n\n")
    _, data = frame.rstrip("\n").split("\n", 1)
    assert "\n" not in data and json.loads(data.removeprefix("data: ")) == {"text": "한 줄\n두 줄"}


def test_followups_are_three_short_questions():
    assert len(followups("question", qtype="기한")) == 3
    top = {"title": "여비규정", "label": "제27조(출장증빙의 제출)"}
    assert followups("lookup", top=top)[0] == "여비규정 제27조 내용을 쉽게 설명해 주세요"


# ---------------------------------------------------------------- 비교 (가짜 검색·DB·LLM)

def _hit(inst, name, title, text, score, art="a10"):
    return {"work_id": f"kr/reg/{inst}/{title}", "version_id": f"v-{inst}", "path": art, "article_path": art,
            "title": title, "institution": inst, "institution_name": name, "family": "reg",
            "path_label": "제10조(출장증빙)", "text": text, "score": score, "rerank_score": score, "matches": []}


HITS = [_hit("KASI", "한국천문연구원", "여비규정", "제10조(출장증빙) ① 출장자는 출장 후 7일 이내에 증빙서를 제출하여야 한다.", 0.9),
        _hit("KBSI", "한국기초과학지원연구원", "여비지침", "제10조(출장증빙) 출장자는 귀임 후 5일 이내에 증빙서류를 제출한다.", 0.8),
        _hit("KASI", "한국천문연구원", "회계규정", "제3조 다른 조문", 0.5, art="a3"),
        _hit("KIST", "한국과학기술연구원", "여비규정", "제10조(출장증빙) 출장 증빙은 소속 부서장이 정한다.", 0.7)]


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    """규정 도우미가 보내는 SQL만 흉내낸다."""

    def __init__(self, cells=None):
        self.cells, self.sql = cells, []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if "to_regclass" in sql:
            return Rows([{"r": "regulation.compare_cell" if self.cells is not None and params[0].endswith("compare_cell")
                          else None}])
        if "FROM regulation.institution" in sql:
            return Rows([{"code": c, "name": al[0], "aliases": al[1:]} for c, al in ALIASES.items()])
        if "FROM regulation.work w" in sql:
            return Rows([{"id": h["work_id"], "code": h["institution"], "name": h["institution_name"]} for h in HITS
                         if h["work_id"] in params[0]])
        if "FROM regulation.compare_cell" in sql:
            assert params == ("travel", "evidence_deadline")
            return Rows(self.cells)
        if "version_state = 'CURRENT'" in sql:
            h = next(h for h in HITS if h["work_id"] == params[0])
            body = h["text"].split(") ", 1)[1].lstrip("① ")
            return Rows([{"path": "a10.p1", "text": body, "version_id": h["version_id"], "title": h["title"]}])
        if "FROM regulation.version_provision" in sql:
            h = next(h for h in HITS if h["version_id"] == params[0])
            body = h["text"].split(") ", 1)[1]
            return Rows([{"path": "a10", "text": "제10조(출장증빙)"}, {"path": "a10.p1", "text": body.lstrip("① ")}])
        raise AssertionError(sql)

    def commit(self):
        pass


class ExtractLLM:
    """값 뽑기: KASI는 원문 인용, KBSI는 원문에 없는 인용(버려야 함), KIST는 없음."""

    def __init__(self):
        self.calls = 0

    def regex(self, messages, pattern, **kw):
        self.calls += 1
        user = messages[-1]["content"]
        if "한국천문연구원" in user:
            return "값: 7일 이내\n인용: 출장 후 7일 이내에 증빙서를 제출하여야 한다"
        if "한국기초과학지원연구원" in user:
            return "값: 5일 이내\n인용: 출장 후 5일 안에 영수증을 제출한다"
        return "값: 없음\n인용: 없음"


@pytest.fixture
def fake_search(monkeypatch):
    seen = []

    def retrieve(deps, query, institution, as_of, aliases, size=10, kind=None, with_units=False):
        seen.append({"query": query, "institution": institution, "kind": kind})
        hits = [h for h in HITS if institution in (None, h["institution"])]
        return {"hits": hits, "lookup": [], "release_id": "r1", "reranked": True}, hits

    monkeypatch.setattr(chat_mod, "retrieve", retrieve)
    return seen


def _events(conn, llm, q, scope=ALL):
    return collect(chat(conn, {"llm": llm}, [{"role": "user", "content": q}], scope, log=False))


def test_comparison_table_from_extraction_keeps_only_verbatim_quotes(fake_search):
    ev = _events(FakeConn(), ExtractLLM(), "출장 증빙은 출장 후 며칠 안에 내야 하나요? 다른 기관도")
    kinds = [e["event"] for e in ev]
    assert kinds[0] == "status" and kinds[-1] == "done" and "answer" not in kinds
    assert kinds.index("results") < kinds.index("table") < kinds.index("citations")
    assert fake_search[0]["institution"] is None and fake_search[0]["kind"] == "reg" and "다른 기관" not in fake_search[0]["query"]
    cards = next(e["data"]["cards"] for e in ev if e["event"] == "results")
    assert [c["institution"]["code"] for c in cards] == ["KASI", "KBSI", "KIST"]          # 기관마다 1위 조 하나
    table = next(e["data"] for e in ev if e["event"] == "table")
    rows = {r["institution"]["code"]: r for r in table["rows"]}
    assert table["source"] == "extracted"
    assert rows["KASI"]["value"] == "7일 이내" and rows["KASI"]["cite"] == 1
    assert rows["KBSI"]["value"] is None and rows["KBSI"]["cite"] is None                # 원문에 없는 인용은 버린다
    assert rows["KIST"]["value"] is None
    cites = next(e["data"]["items"] for e in ev if e["event"] == "citations")
    assert len(cites) == 1 and cites[0]["quote"] in HITS[0]["text"] and cites[0]["path"] == "a10.p1"
    assert cites[0]["label"] == "여비규정 제10조 제1항"
    done = ev[-1]["data"]
    assert done["status"] == "compared" and done["intent"] == "comparison" and done["qa_id"] is None
    assert len(next(e["data"]["items"] for e in ev if e["event"] == "followups")) == 3


def test_comparison_puts_focus_institution_first(fake_search):
    ev = _events(FakeConn(), ExtractLLM(), "출장 증빙 기한은? 다른 기관도 알려 주세요", only("KIST"))
    cards = next(e["data"]["cards"] for e in ev if e["event"] == "results")
    assert cards[0]["institution"]["code"] == "KIST"


def test_comparison_over_selected_institutions_searches_each(fake_search):
    ev = _events(FakeConn(), ExtractLLM(), "출장 증빙 기한", only("KASI", "KBSI"))
    assert sorted(x["institution"] for x in fake_search) == ["KASI", "KBSI"]
    cards = next(e["data"]["cards"] for e in ev if e["event"] == "results")
    assert {c["institution"]["code"] for c in cards} == {"KASI", "KBSI"}


ITEMS = {"travel": [
    {"id": "evidence_deadline", "label": "출장 증빙 제출 기한", "query": "출장 종료 후 출장 증빙서 제출 기한 며칠 이내",
     "ask": "국내 출장을 마친 뒤 출장 증빙서류나 출장복명서를 며칠 이내에 제출해야 하는가?", "unit": "일"},
    {"id": "settlement_deadline", "label": "여비 정산 기한", "query": "출장 여비 정산 신청 기한 출장 종료 후 이내 정산",
     "ask": "국내 출장 여비는 출장이 끝난(귀임한) 뒤 며칠 이내에 정산해야 하는가?", "unit": "일"}],
    "research": [{"id": "note_retention", "label": "연구노트 보존 기간", "query": "연구노트 보존 기간"}]}


def _cell(code, value, quote, method="llm"):
    return {"institution_code": code, "work_id": next(h["work_id"] for h in HITS if h["institution"] == code),
            "path": "a10.p1", "value": value, "value_norm": value, "quote": quote, "method": method, "confidence": 0.9}


def test_match_item_by_label_and_query():
    from reg.qa.chat import match_item

    t, it = match_item("출장 증빙은 출장 후 며칠 안에 내야 하나요?", ITEMS)
    assert (t, it["id"]) == ("travel", "evidence_deadline")
    assert match_item("여비 정산은 언제까지 하나요?", ITEMS)[1]["id"] == "settlement_deadline"
    assert match_item("연구장비 구매 절차", ITEMS) is None
    assert match_item("출장 증빙 제출 기한", ITEMS, topic="research") is None


def test_comparison_uses_compare_cell_when_present(fake_search, monkeypatch):
    monkeypatch.setattr(chat_mod, "compare_items", lambda: ITEMS)
    cells = [_cell("KASI", "7일", "7일 이내에 증빙서를"), _cell("KBSI", "5일", "5일 안에 영수증을"),   # KBSI 인용은 원문에 없다
             {**_cell("KIST", None, None, "absent"), "work_id": None, "path": None}]
    llm = ExtractLLM()
    ev = _events(FakeConn(cells), llm, "다른 기관도 출장 증빙 제출 기한은?")
    table = next(e["data"] for e in ev if e["event"] == "table")
    assert table["source"] == "compare_cell" and llm.calls == 0
    assert (table["item"], table["item_id"], table["topic"], table["unit"]) == ("출장 증빙 제출 기한", "evidence_deadline",
                                                                                "travel", "일")
    rows = {r["institution"]["code"]: r for r in table["rows"]}
    assert rows["KASI"]["value"] == "7일" and rows["KASI"]["cite"] == 1
    assert rows["KBSI"]["value"] is None and rows["KIST"] == {"institution": {"code": "KIST", "name": "한국과학기술연구원"},
                                                             "value": None, "cite": None, "absent": True}
    cites = next(e["data"]["items"] for e in ev if e["event"] == "citations")
    assert len(cites) == 1 and cites[0]["quote"] == "7일 이내에 증빙서를" and cites[0]["label"] == "여비규정 제10조 제1항"


def test_compare_cell_respects_selected_institutions_and_focus(fake_search, monkeypatch):
    monkeypatch.setattr(chat_mod, "compare_items", lambda: ITEMS)
    cells = [_cell("KASI", "7일", "7일 이내에 증빙서를"), _cell("KBSI", "5일", "5일 이내에 증빙서류를")]
    ev = _events(FakeConn(cells), ExtractLLM(), "출장 증빙 제출 기한", only("KBSI", "KASI"))
    table = next(e["data"] for e in ev if e["event"] == "table")
    assert [r["institution"]["code"] for r in table["rows"]] == ["KASI", "KBSI"] and all(r["cite"] for r in table["rows"])
    ev = _events(FakeConn(cells), ExtractLLM(), "출장 증빙 제출 기한은? 다른 기관도", only("KBSI"))
    table = next(e["data"] for e in ev if e["event"] == "table")
    assert table["rows"][0]["institution"]["code"] == "KBSI"


def test_compare_cell_without_matching_item_falls_back_to_extraction(fake_search, monkeypatch):
    monkeypatch.setattr(chat_mod, "compare_items", dict)
    ev = _events(FakeConn([]), ExtractLLM(), "다른 기관도 출장 증빙 제출 기한은?")
    assert next(e["data"] for e in ev if e["event"] == "table")["source"] == "extracted"


def test_comparison_without_llm_still_sends_cards(fake_search):
    ev = _events(FakeConn(), None, "출장 증빙 기한은?")
    assert any(e["event"] == "results" and e["data"]["cards"] for e in ev)
    assert ev[-1]["data"]["status"] == "evidence_only"


def test_failure_still_ends_with_done(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("os down")

    monkeypatch.setattr(chat_mod, "retrieve", boom)
    ev = _events(FakeConn(), None, "천문연 여비규정 27조")
    assert ev[-1]["event"] == "done" and ev[-1]["data"]["status"] == "error" and "os down" in ev[-1]["data"]["note"]


def test_rejects_when_last_message_is_not_user():
    ev = collect(chat(FakeConn(), {}, [{"role": "assistant", "content": "x"}], ALL, log=False))
    assert [e["event"] for e in ev] == ["done"] and ev[0]["data"]["status"] == "error"


def test_pii_is_masked_before_rewrite(fake_search):
    llm = RewriteLLM(out="질문: 천문연 출장 증빙 기한은 다른 기관도 같은가요?")
    msgs = _msgs("천문연 출장 증빙 기한은? 010-1234-5678", "7일", "다른 기관도요?")
    ev = collect(chat(FakeConn(), {"llm": llm}, msgs, ALL, log=False))
    assert llm.calls and not any("5678" in m["content"] for call in llm.calls for m in call)
    st = ev[0]["data"]
    assert st["rewritten"] and st["intent"] == "comparison" and st["institutions"] == []


def test_strip_compare_leaves_the_question():
    from reg.qa.chat import strip_compare

    assert strip_compare("출장 증빙은 출장 후 며칠 안에 내야 하나요? 다른 기관도") == "출장 증빙은 출장 후 며칠 안에 내야 하나요?"
    assert strip_compare("기관별로 출장 증빙 기한") == "출장 증빙 기한"
    assert strip_compare("다른 기관도 출장 증빙 제출 기한은?") == "출장 증빙 제출 기한은?"


def test_lookup_card_label_and_text_from_lookup_hit():
    from reg.qa.chat import cards

    x = {"work_id": "kr/reg/KASI/여비규정", "version_id": "v1", "path": "a27", "article_path": "a27", "unit": "article",
         "label": "제27조", "heading": "출장증빙의 제출", "full_label": "여비규정 제27조", "title": "여비규정",
         "institution": "KASI", "institution_name": "한국천문연구원", "family": "reg", "text": "",
         "article_text": "제27조(출장증빙의 제출)\n① 출장자는 7일 이내에 증빙서를 제출하여야 한다.", "score": 1.0}
    c = cards({"lookup": [x], "hits": []})[0]
    assert c["label"] == "제27조(출장증빙의 제출)" and "7일 이내" in c["snippet"]


def test_title_falls_back_from_work_id():
    h = {"work_id": "kr/reg/KIT/여비규정", "version_id": "v", "path": "a1", "title": "kr/reg/KIT/[본원규정]여비규정",
         "matches": [], "text": "x"}
    assert card(h)["title"] == "[본원규정]여비규정"


def test_standalone_compare_request_follow_up():
    q, rw = standalone(None, _msgs("연구장비 구매 절차", "…", "기관별로 비교해 주세요"), ALIASES)
    assert rw and q == "연구장비 구매 절차 다른 기관도" and plan(q, ALL, ALIASES)["intent"] == "comparison"


# ---------------------------------------------------------------- 전체 기관 질문 (비교할 값 없음)

class OverviewLLM:
    """분석 → 정리. 정리는 E1(원문 인용)과 E2(원문에 없는 인용)를 든다."""

    def __init__(self, expl="기관들은 출장 후 정해진 기한 안에 증빙서를 제출하도록 한다."):
        self.expl, self.calls = expl, []

    def regex(self, messages, pattern, **kw):
        self.calls.append(pattern)
        if pattern.startswith("유형"):
            return "유형: 절차\n검색어: 증빙"
        assert pattern.startswith("설명")
        return (f"설명: {self.expl}\n근거: E1\n인용: 출장자는 출장 후 7일 이내에 증빙서를 제출하여야 한다\n"
                "근거: E2\n인용: 출장자는 언제든지 영수증을 낸다")


@pytest.fixture
def fake_expand(monkeypatch):
    from reg.qa.evidence import Evidence

    def expand(conn, hits, limit_articles=4, **kw):
        return [Evidence(f"E{i + 1}", h["work_id"], h["version_id"], h["title"], h["article_path"], h["path_label"],
                         h["text"], "primary", None) for i, h in enumerate(hits[:limit_articles])]

    monkeypatch.setattr(chat_mod, "expand", expand)


def test_all_institution_question_groups_cards_and_summarises(fake_search, fake_expand):
    llm = OverviewLLM()
    ev = _events(FakeConn(), llm, "출장 증빙 제출 절차")
    kinds = [e["event"] for e in ev]
    assert ev[0]["data"]["intent"] == "question" and ev[0]["data"]["institutions"] == []
    assert "table" not in kinds and kinds.index("results") < kinds.index("answer") < kinds.index("citations")
    assert fake_search[0]["institution"] is None and fake_search[0]["kind"] == "reg"
    cards = next(e["data"]["cards"] for e in ev if e["event"] == "results")
    assert [c["institution"]["code"] for c in cards] == ["KASI", "KASI", "KBSI", "KIST"]      # 기관별로 묶고 최대 2장
    ans = next(e["data"] for e in ev if e["event"] == "answer")
    assert ans["conclusion"] is None and ans["based_on"] == [{"code": "KASI", "name": "한국천문연구원"}]
    assert ans["sentences"][0]["text"].startswith("한국천문연구원 규정을 바탕으로") and all(s["cites"] for s in ans["sentences"])
    cites = next(e["data"]["items"] for e in ev if e["event"] == "citations")
    assert len(cites) == 1 and cites[0]["quote"] in HITS[0]["text"]                     # 원문에 없는 E2 인용은 버린다
    assert ev[-1]["data"]["status"] == "answered"


def test_diverse_caps_cards_per_institution():
    from reg.qa.chat import diverse

    cs = [{"id": str(i), "institution": {"code": c}} for i, c in enumerate("AAABBAC")]
    assert [c["institution"]["code"] for c in diverse(cs)] == ["A", "A", "B", "B", "C"]


def test_all_institution_answer_with_invented_number_falls_back_to_cards(fake_search, fake_expand):
    llm = OverviewLLM(expl="모든 기관이 출장 후 15일 이내에 증빙서를 제출하도록 한다.")
    ev = _events(FakeConn(), llm, "출장 증빙 제출 절차")
    assert "answer" not in [e["event"] for e in ev] and ev[-1]["data"]["status"] == "evidence_only"
    assert sum(p.startswith("설명") for p in llm.calls) == 2                               # 한 번 다시 묻는다
    assert next(e["data"]["cards"] for e in ev if e["event"] == "results")


def test_overview_answer_ignores_evidence_ids_in_explanation():
    from reg.qa.chat import overview_answer
    from reg.qa.evidence import Evidence

    class L:
        def regex(self, messages, pattern, **kw):
            return ("설명: 구매는 관련 규정에 따른다 (E1: \"계약 규정\"). 기술검사를 거친다 E2.\n"
                    "근거: E1\n인용: 연구시설장비의 구매는 관련 규정에 따른다.")

    ev = [Evidence("E1", "w", "v", "지침", "a16", "제16조", "연구시설장비의 구매는 관련 규정에 따른다.", "primary", None)]
    got = overview_answer(L(), "연구장비 구매 절차", ev, {})
    assert got and got["설명"] == "구매는 관련 규정에 따른다. 기술검사를 거친다." and got["결론"] is None


def test_best_sentence_is_verbatim_and_requires_overlap():
    from reg.qa.chat import best_sentence

    text = "제7조(구매)\n① 시설·장비활용부서의 장은 심의를 통과한 시설·장비에 대해 구매신청한다.\n② 관리부서는 계약절차를 진행한다."
    got = best_sentence("시설·장비활용부서의 장이 심의를 통과한 장비에 대해 구매신청한다", text)
    assert got == "시설·장비활용부서의 장은 심의를 통과한 시설·장비에 대해 구매신청한다." and got in text
    assert best_sentence("연구노트는 30년 보존한다", text) is None

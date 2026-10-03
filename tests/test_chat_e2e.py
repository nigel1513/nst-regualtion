"""규정 도우미 통합 테스트: 실제 PostgreSQL·OpenSearch(테스트 컨테이너) + 가짜 임베딩·리랭커·LLM."""
import json

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from reg.platform.storage.blob import LocalBlobStore
from reg.qa.chat import chat, collect
from reg.qa.service import ask
from tests.test_indexer import FakeEmbedder
from tests.test_qa_service import SeqLLM, good
from tests.test_search import FakeReranker

KASI = {"mode": "institutions", "institutions": ["KASI"]}


@pytest.fixture
def deps(loaded, os_url):
    os = OpenSearch(os_url)
    build_release(loaded, os, FakeEmbedder(), "fake")
    return {"os": os, "embedder": FakeEmbedder(), "reranker": FakeReranker(), "llm_model": "fake"}


def _user(q):
    return [{"role": "user", "content": q}]


def _by(ev, kind):
    return [e["data"] for e in ev if e["event"] == kind]


def test_question_path_answers_with_verbatim_paragraph_citation(loaded, deps):
    llm = SeqLLM(good(loaded))
    ev = collect(chat(loaded, {**deps, "llm": llm}, _user("출장 다녀온 지 10일 지났는데 증빙 안 냈어요"), KASI, log=False))
    kinds = [e["event"] for e in ev]
    assert kinds[0] == "status" and kinds[-1] == "done"
    assert kinds.index("results") < kinds.index("answer_delta") < kinds.index("answer") < kinds.index("citations")
    assert _by(ev, "status")[0]["intent"] == "question"
    card = _by(ev, "results")[0]["cards"][0]
    assert card["article_path"] == "a27" and card["institution"] == {"code": "KASI", "name": "한국천문연구원"}
    ans = _by(ev, "answer")[0]
    assert ans["conclusion"] == "미충족" and ans["sentences"] and all(s["cites"] == [1] for s in ans["sentences"])
    assert _by(ev, "answer_delta")[0]["text"] == ans["explanation"]
    cite = _by(ev, "citations")[0]["items"][0]
    text = "\n".join(r["text"] for r in loaded.execute(
        "SELECT pv.text FROM regulation.provision_version pv JOIN regulation.version_provision vp"
        " ON vp.provision_version_id = pv.id WHERE vp.work_version_id = %s AND pv.path LIKE 'a27%%'",
        (cite["version_id"],)).fetchall())
    assert cite["quote"] in text and cite["path"] == "a27.p1" and cite["label"] == "여비규정 제27조 제1항"
    assert cite["institution"]["code"] == "KASI" and cite["href"].endswith("?a=a27#a27.p1")
    done = ev[-1]["data"]
    assert done["status"] == "answered" and done["first_results_ms"] <= done["latency_ms"]


def test_question_matches_qa_ask_evidence(loaded, deps):
    """같은 질문이면 /api/v1/qa(ask)와 같은 근거 조문을 인용한다 (공유 경로)."""
    q = "천문연 출장 다녀온 지 10일 지났는데 증빙서를 안 냈어요"
    r = ask(loaded, {**deps, "llm": SeqLLM(good(loaded))}, q, log=False)
    ev = collect(chat(loaded, {**deps, "llm": SeqLLM(good(loaded))}, _user(q), {"mode": "all"}, log=False))
    cite = _by(ev, "citations")[0]["items"][0]
    assert r["evidence"][0]["path"] == "a27" and cite["path"].startswith("a27")
    assert r["answer"]["결론"] == _by(ev, "answer")[0]["conclusion"]


def test_lookup_intent_returns_cards_without_generation(loaded, deps):
    llm = SeqLLM(None, fail=True)
    ev = collect(chat(loaded, {**deps, "llm": llm}, _user("천문연 여비규정 27조"), {"mode": "all"}, log=False))
    kinds = [e["event"] for e in ev]
    assert "answer" not in kinds and "table" not in kinds and llm.n == 0
    card = _by(ev, "results")[0]["cards"][0]
    assert card["article_path"] == "a27" and card["title"] == "여비규정"
    assert ev[-1]["data"]["status"] == "lookup" and len(_by(ev, "followups")[0]["items"]) == 3


def test_llm_down_still_sends_cards(loaded, deps):
    ev = collect(chat(loaded, {**deps, "llm": SeqLLM(None, fail=True)}, _user("천문연 출장 증빙 제출 기한이 며칠인가요"),
                      {"mode": "all"}, log=False))
    assert _by(ev, "results")[0]["cards"] and ev[-1]["data"]["status"] == "evidence_only"


def test_logs_turn_with_conversation_id(loaded, deps):
    msgs = _user("천문연 출장 다녀온 지 10일 지났는데 증빙서를 안 냈어요 010-1234-5678")
    ev = collect(chat(loaded, {**deps, "llm": SeqLLM(good(loaded))}, msgs, {"mode": "all"}, conversation_id="c-1"))
    done = ev[-1]["data"]
    row = loaded.execute("SELECT question, status, verdict, verification FROM ops.qa_log WHERE id = %s",
                         (done["qa_id"],)).fetchone()
    assert "5678" not in row["question"] and row["status"] == "answered" and row["verdict"] == "미충족"
    assert row["verification"]["chat"]["conversation_id"] == "c-1" and row["verification"]["chat"]["intent"] == "question"
    assert row["verification"]["chat"]["turn"] == 1


def test_no_log_writes_nothing(loaded, deps):
    before = loaded.execute("SELECT count(*) AS n FROM ops.qa_log").fetchone()["n"]
    collect(chat(loaded, {**deps, "llm": SeqLLM(good(loaded))}, _user("천문연 여비규정 27조"), {"mode": "all"}, log=False))
    assert loaded.execute("SELECT count(*) AS n FROM ops.qa_log").fetchone()["n"] == before


@pytest.fixture
def api(loaded, deps, migrated, tmp_path):
    app = create_app(migrated[0], LocalBlobStore(tmp_path), {**deps, "llm": SeqLLM(good(loaded)), "related": None})
    with TestClient(app) as c:
        yield app, c


def _frames(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.split("\n\n"):
        if block.strip():
            ev, data = block.split("\n", 1)
            assert ev.startswith("event: ") and data.startswith("data: ") and "\n" not in data
            out.append((ev.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_chat_endpoint_streams_sse(api):
    app, c = api
    body = {"messages": _user("출장 다녀온 지 10일 지났는데 증빙 안 냈어요"), "scope": KASI}
    with c.stream("POST", "/api/v1/chat", json=body) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        frames = _frames(r.read().decode())
    assert frames[0][0] == "status" and frames[-1][0] == "done" and frames[-1][1]["qa_id"]
    assert {"results", "answer", "citations", "followups"} <= {f[0] for f in frames}
    assert app.state.qa_slots._value == 3          # 슬롯을 돌려줬다


def test_chat_endpoint_non_stream_json(api):
    _, c = api
    r = c.post("/api/v1/chat?stream=false", json={"messages": _user("천문연 여비규정 27조")})
    ev = r.json()
    assert r.status_code == 200 and ev[0]["event"] == "status" and ev[-1]["event"] == "done"
    assert ev[0]["data"]["intent"] == "lookup"


def test_chat_endpoint_validates_and_respects_slots(api):
    app, c = api
    assert c.post("/api/v1/chat", json={"messages": []}).status_code == 422
    assert c.post("/api/v1/chat", json={"messages": _user("x") * 13}).status_code == 422
    for _ in range(app.state.qa_slots._value):
        app.state.qa_slots.acquire()
    assert c.post("/api/v1/chat", json={"messages": _user("천문연 여비규정 27조")}).status_code == 429


def test_qa_endpoint_unchanged(api):
    _, c = api
    r = c.post("/api/v1/qa", json={"question": "천문연 출장 다녀온 지 10일 지났는데 증빙서를 안 냈어요"}).json()
    assert r["status"] == "answered" and r["evidence"][0]["path"] == "a27"
    assert set(r) >= {"id", "status", "institution", "as_of", "question_type", "evidence", "answer", "verification",
                      "verdict_source", "release_id", "note", "retrieved"}

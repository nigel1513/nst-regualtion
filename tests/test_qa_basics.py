import pytest

from reg.qa.institutions import load_aliases, resolve_mention
from reg.qa.mask import mask_pii


@pytest.fixture
def aliases(conn):
    """기관 약칭은 설정(config/sources/alio.yaml) → regulation.institution.aliases → qa가 DB에서 읽는다."""
    from reg.sources.alio.config import INSTITUTIONS_YAML
    from reg.sources.alio.sync import load_institutions

    load_institutions(conn, INSTITUTIONS_YAML)
    return load_aliases(conn)


def test_resolve_mention(aliases):
    assert resolve_mention("천문연 소속인데 출장 다녀온 지 10일", aliases) == "KASI"
    assert resolve_mention("한국천문연구원 여비규정", aliases) == "KASI"
    assert resolve_mention("NST 여비 정산", aliases) == "NST"
    assert resolve_mention("출장 정산 기한", aliases) is None
    assert resolve_mention("천문연과 ETRI 비교", aliases) is None


def test_mask_pii():
    s = mask_pii("저는 900101-1234567, 010-1234-5678, a.b@x.kr 입니다")
    assert "1234567" not in s and "5678" not in s and "@" not in s and s.count("[개인정보]") == 3


def test_qa_log_table(conn):
    conn.execute("INSERT INTO ops.qa_log (question, status) VALUES ('q', 'answered')")


def test_mention_needs_a_word_boundary(aliases):
    assert resolve_mention("KISTI 출장 규정", aliases) is None
    assert resolve_mention("한국과학기술정보연구원 출장", aliases) is None
    assert resolve_mention("학술연구회 회의", aliases) is None
    assert resolve_mention("KIST 출장비", aliases) == "KIST" and resolve_mention("키스트에서 출장", aliases) == "KIST"
    assert resolve_mention("연구회 규정", aliases) == "NST"


def test_aliases_come_from_db_active_institutions(conn, aliases):
    assert aliases["KASI"][0] == "한국천문연구원" and {"천문연", "KASI"} <= set(aliases["KASI"])
    assert "KISTI" not in aliases   # 비활성 기관은 질문에서 찾지 않는다 (검색할 규정이 없다)
    conn.execute("UPDATE regulation.institution SET aliases = '{}' WHERE code = 'KASI'")
    conn.execute("UPDATE regulation.institution SET active = true WHERE code = 'KISTI'")
    conn.commit()
    now = load_aliases(conn)
    assert resolve_mention("천문연 출장", now) is None and resolve_mention("한국천문연구원 출장", now) == "KASI"
    assert resolve_mention("키스티 출장", now) == "KISTI" and resolve_mention("KIST 출장", now) == "KIST"
    assert resolve_mention("천문연 출장", {}) is None

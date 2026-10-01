from reg.qa.institutions import resolve_mention
from reg.qa.mask import mask_pii


def test_resolve_mention():
    assert resolve_mention("천문연 소속인데 출장 다녀온 지 10일") == "KASI"
    assert resolve_mention("한국천문연구원 여비규정") == "KASI"
    assert resolve_mention("NST 여비 정산") == "NST"
    assert resolve_mention("출장 정산 기한") is None
    assert resolve_mention("천문연과 ETRI 비교") is None


def test_mask_pii():
    s = mask_pii("저는 900101-1234567, 010-1234-5678, a.b@x.kr 입니다")
    assert "1234567" not in s and "5678" not in s and "@" not in s and s.count("[개인정보]") == 3


def test_qa_log_table(conn):
    conn.execute("INSERT INTO regulation.qa_log (question, status) VALUES ('q', 'answered')")

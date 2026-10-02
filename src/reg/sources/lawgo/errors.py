"""law.go.kr 수집 오류. 메시지만 보고 원인을 알 수 있게 쓴다 (spec §1A.6 canary)."""


class LawGoError(Exception):
    """lawgo 모듈 오류의 공통 부모."""


class KeyNotApproved(LawGoError):
    """OC 키가 그 목록·본문에 대해 아직 승인되지 않았다 (HTML '미신청된 목록/본문에 대한 접근')."""


class KeyRejected(LawGoError):
    """law.go.kr가 요청을 거부했다: 키·IP 검증 실패, 필수값 누락 (<Response><result>…)."""


class NotFound(LawGoError):
    """MST·ID에 해당하는 본문이 없다 (<Law>일치하는 … 없습니다)."""


class ResponseChanged(LawGoError):
    """응답 구조가 기대와 다르다. 수집을 멈추고 README 점검표를 본다."""

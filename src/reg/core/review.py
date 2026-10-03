"""검수 작업: 화면용 문장(문제·할 일)·위치 라벨·원문 발췌와 사람의 처리 (서비스 UI 스펙 §6).

사람의 처리(담당·해결·문제 없음·보류)는 `review_task`와 `review_decision`에 함께 쓴다. `review_decision`은
재적재(TRUNCATE)에도 남고, 다시 만든 작업에 트리거가 되살린다 (마이그레이션 0013).
"""
import json
import re
from datetime import UTC, datetime

KIND_LABEL = {
    "REFERENCE": "참조 미연결", "REF_LAW_AMBIGUOUS": "법령명 모호", "REF_LAW_GONE": "인용 법령 폐지·삭제",
    "PARSE": "구조 파싱", "EFFECTIVE_DATE": "시행일 불확실", "CONFLICT": "시행일 충돌", "LOW_TEXT": "텍스트 부족",
    "ABOLISHED": "폐지 후보",
}
REF_KINDS = ("REFERENCE", "REF_LAW_AMBIGUOUS", "REF_LAW_GONE")
VERSION_KINDS = ("PARSE", "EFFECTIVE_DATE", "CONFLICT")
STATUSES = ("OPEN", "HOLD", "RESOLVED", "DISMISSED")
ACTIVE = ("OPEN", "HOLD")

# 법령 이름 참조(law.go.kr 적재 대기). docs/tech/02-data-loading.md §5.2의 "법령형" = 법·법률·시행령·시행규칙·영으로 끝남.
# 약칭 정의 없는 맨 이름(core.refs.BARE_LAW)은 적재돼도 이을 수 없어 사람 몫으로 남긴다.
BARE_LAW = ("법", "영", "법률", "시행령", "시행규칙")
LAW_NAME_RE = r"(법|법률|령|시행규칙)$"
LAW_PENDING_SQL = ("(t.kind = 'REFERENCE' AND NOT coalesce(t.detail->>'name' = ANY(ARRAY['법','영','법률','시행령','시행규칙']),"
                   " true) AND regexp_replace(t.detail->>'name', '\\s', '', 'g') ~ '(법|법률|령|시행규칙)$')")

# ALIO 상세의 jidtDptm은 기관 안 부서가 아니라 주무부처 코드다 (실DB: A1044 23개 기관, A1747 KARI·KASI).
MINISTRY = {"A1044": "과학기술정보통신부", "A1747": "우주항공청"}

BASIS_LABEL = {"api": "법령 API", "supplement": "부칙", "history": "개정 이력", "alio": "ALIO 개정일",
               "filename": "파일 이름", "none": "근거 없음"}


def is_law_pending(kind: str, detail: dict) -> bool:
    name = (detail or {}).get("name") or ""
    return kind == "REFERENCE" and name not in BARE_LAW and bool(re.search(LAW_NAME_RE, re.sub(r"\s", "", name)))


def department(code: str | None) -> dict | None:
    return {"code": code, "name": MINISTRY.get(code), "scope": "주무부처"} if code else None


# ---------- 위치 ----------

def _num(n: str, unit: str) -> str:
    """('10-2', '조') → '10조의2'."""
    base, _, sub = n.partition("-")
    return f"{base}{unit}" + (f"의{sub}" if sub else "")


_SEG = [
    (re.compile(r"^a(\d+(?:-\d+)?)$"), lambda m: f"제{_num(m[1], '조')}"),
    (re.compile(r"^p(\d+)$"), lambda m: f"제{m[1]}항"),
    (re.compile(r"^i(\d+(?:-\d+)?)$"), lambda m: f"제{_num(m[1], '호')}"),
    (re.compile(r"^s(.+)$"), lambda m: f"{m[1]}목"),
    (re.compile(r"^annex(\d+(?:-\d+)?)$"), lambda m: "별표 " + _num(m[1], "")),
    (re.compile(r"^form(\d+(?:-\d+)?)$"), lambda m: f"별지 제{_num(m[1], '호')} 서식"),
    (re.compile(r"^c(\d+)$"), lambda m: f"제{m[1]}장"),
    (re.compile(r"^c\d+-s(\d+)$"), lambda m: f"제{m[1]}절"),
]


def path_label(path: str | None) -> str:
    """조항 경로 → 사람이 읽는 위치. 'a13.p2' → '제13조 제2항', 'supp@…/a1' → '부칙 제1조'."""
    if not path:
        return "전체"
    out = []
    head, _, rest = path.partition("/") if path.startswith("supp") else ("", "", path)
    if head:
        out.append("부칙")
    for seg in (rest.split(".") if rest else []):
        seg = seg.split("~")[0]
        for rx, fmt in _SEG:
            if m := rx.match(seg):
                out.append(fmt(m))
                break
        else:
            return path
    return " ".join(out)


def article_of(path: str | None) -> str | None:
    """조문 보기의 선택 조(?a=)로 쓸 본칙 조 경로."""
    m = re.match(r"^(a\d+(?:-\d+)?)(?:[.~]|$)", path or "")
    return m[1] if m else None


def excerpt(text: str, start: int | None, evidence: str | None, window: int = 80) -> dict:
    """인용 위치 앞뒤 window자. highlight는 돌려주는 text 안의 [시작, 끝)."""
    s = e = None
    if evidence:
        if start is not None and text[start:start + len(evidence)] == evidence:
            s = start
        else:
            hits = [m.start() for m in re.finditer(re.escape(evidence), text)]
            if hits:
                s = min(hits, key=lambda h: abs(h - (start or 0)))
        if s is not None:
            e = s + len(evidence)
    if s is None:
        cut = text[:window * 2]
        return {"text": cut + ("…" if len(text) > len(cut) else ""), "highlight": None}
    a, b = max(s - window, 0), min(e + window, len(text))
    pre = "…" if a > 0 else ""
    return {"text": pre + text[a:b] + ("…" if b < len(text) else ""),
            "highlight": [s - a + len(pre), e - a + len(pre)]}


DATE_RE = re.compile(r"\d{4}\s*[.년]\s*\d{1,2}\s*[.월]\s*\d{1,2}\s*일?|공포한 날|발령한 날|승인한 날")


def date_excerpt(text: str, window: int = 80) -> dict:
    """부칙 시행일 조항 발췌: 첫 날짜 표현을 강조한다."""
    m = DATE_RE.search(text)
    return excerpt(text, m.start() if m else None, m[0] if m else None, window)


# ---------- 문제·할 일 ----------

def path_labels(paths: list[str], n: int = 3) -> str:
    labels = [path_label(p) for p in paths[:n]]
    return "·".join(labels) + (f" 외 {len(paths) - n}곳" if len(paths) > n else "")


def _cite(d: dict) -> str:
    """인용 표시: 근거 글에 이름이 있으면 근거 글만, 없으면 「이름」 근거 글."""
    name, ev = d.get("name") or "", (d.get("evidence") or "").strip()
    if ev and name and name in ev:
        return ev
    return f"「{name}」 {ev}".strip() if name else ev or "-"


def problem(kind: str, d: dict) -> str:
    """종류별 문제 문장. 이름 뒤 조사를 피하려고 '…: 인용' 꼴로 쓴다."""
    d = d or {}
    name = d.get("name") or ""
    if kind == "REFERENCE":
        if is_law_pending(kind, d):
            return f"인용한 법령이 아직 적재되지 않아 연결을 기다립니다: {_cite(d)}."
        return f"인용을 어느 규정·법령에도 연결하지 못했습니다: {_cite(d)}."
    if kind == "REF_LAW_AMBIGUOUS":
        n = len(d.get("candidates") or [])
        return f"법령 이름에 맞는 법령이 {n}개라 하나로 정하지 못했습니다: {_cite(d)}."
    if kind == "REF_LAW_GONE":
        tp = f"「{name}」 {path_label(d.get('target_path'))}" if d.get("target_path") else f"「{name}」"
        return {"law_abolished": f"인용한 법령이 폐지되었습니다: 「{name}」.",
                "article_deleted": f"인용한 조문이 삭제되었습니다: {tp}.",
                "article_missing": f"인용한 조문을 현행 법령에서 찾지 못했습니다: {tp}."}.get(
            d.get("reason"), f"인용한 법령을 현행에서 찾지 못했습니다: 「{name}」.")
    if kind == "PARSE":
        if d.get("check") == "toc":
            return f"목차와 본문의 조문이 다릅니다: {path_labels(d.get('diff') or [])}."
        miss = [f"a{n}" for n in d.get("missing") or []]
        return f"본문에서 빠진 조 번호가 있습니다(구조 파싱 누락 의심): {path_labels(miss)}."
    if kind == "EFFECTIVE_DATE":
        b = d.get("basis")
        if b in (None, "none"):
            return "시행일 근거를 찾지 못했습니다."
        return f"시행일을 하나의 근거로만 추정해 확실하지 않습니다(근거: {BASIS_LABEL.get(b, b)})."
    if kind == "CONFLICT":
        return f"시행일 근거끼리 충돌합니다(채택한 근거: {BASIS_LABEL.get(d.get('basis'), d.get('basis') or '-')})."
    if kind == "LOW_TEXT":
        if d.get("reason"):
            return f"본문을 조문으로 나누지 못했습니다: {d['reason']}."
        return f"본문 글자를 거의 뽑지 못했습니다(조문 {d.get('articles', 0)}개)."
    if kind == "ABOLISHED":
        return f"{d.get('missing_since') or '최근'}부터 ALIO 목록에서 사라졌습니다(폐지 후보)."
    return f"자동 검사에서 확인이 필요한 항목이 나왔습니다({kind})."


def todo(kind: str, d: dict) -> str:
    d = d or {}
    if kind == "REFERENCE":
        if is_law_pending(kind, d):
            return "법령 미러에 적재되면 자동으로 다시 연결합니다. 지금 할 일은 없습니다."
        return "인용한 규정·법령을 찾아 연결을 지정하거나, 연결할 대상이 없으면 '문제 없음'으로 닫으세요."
    if kind == "REF_LAW_AMBIGUOUS":
        return "후보 법령 중 맞는 것을 골라 연결을 지정하세요."
    if kind == "REF_LAW_GONE":
        return "규정을 개정해야 하는지 소관 부서에 확인하고, 확인이 끝나면 해결로 닫으세요."
    if kind == "PARSE":
        return "원문 PDF와 대조해 조문이 실제로 빠졌는지 확인하세요. 원문도 그렇다면 '문제 없음', 파싱 오류면 보류로 두고 재처리를 요청하세요."
    if kind in ("EFFECTIVE_DATE", "CONFLICT"):
        return "원문 부칙과 개정 이력을 대조해 맞는 시행일을 확정하세요."
    if kind == "LOW_TEXT":
        if d.get("ocr") == "pending":
            return "OCR이 진행 중입니다. 끝나면 자동으로 다시 처리합니다."
        if d.get("ocr") == "not_needed" or d.get("reason"):
            return "원문을 열어 조문 형식이 아닌 문서(목차형 기준·서식 등)인지 확인하고, 맞으면 '문제 없음'으로 닫으세요."
        return "원문이 스캔본인지 확인하고, 그렇다면 OCR 결과를 기다리거나 보류로 두세요."
    if kind == "ABOLISHED":
        return "기관에 폐지 여부를 확인해 폐지가 맞으면 해결(폐지 확정), 아니면 '문제 없음'(현행 유지)으로 닫으세요."
    return "내용을 확인하고 해결 또는 '문제 없음'으로 닫으세요."


# ---------- 처리 ----------

class ReviewError(Exception):
    """처리할 수 없는 상태. code: 404(없음) 또는 409(상태 충돌)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _lock(conn, task_id: int) -> dict:
    t = conn.execute("SELECT id, kind, target, work_id, detail, status, assignee, decision, resolved_at"
                     " FROM regulation.review_task WHERE id = %s FOR UPDATE", (task_id,)).fetchone()
    if t is None:
        raise ReviewError(404, "검수 작업을 찾을 수 없습니다")
    return t


def _save(conn, t: dict, status: str, assignee: str | None, decision: dict | None, closed: bool) -> None:
    dec = json.dumps(decision, ensure_ascii=False) if decision is not None else None
    conn.execute("UPDATE regulation.review_task SET status = %s, assignee = %s, decision = %s,"
                 " resolved_at = CASE WHEN %s THEN now() END WHERE id = %s",
                 (status, assignee, dec, closed, t["id"]))
    conn.execute(
        "INSERT INTO regulation.review_decision (kind, target, status, assignee, decision, detail, resolved_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)"
        " ON CONFLICT (kind, target) DO UPDATE SET status = EXCLUDED.status, assignee = EXCLUDED.assignee,"
        " decision = EXCLUDED.decision, detail = EXCLUDED.detail, resolved_at = EXCLUDED.resolved_at, updated_at = now()",
        (t["kind"], t["target"], status, assignee, dec, json.dumps(t["detail"], ensure_ascii=False), closed))


def _active(t: dict, verb: str) -> None:
    if t["status"] not in ACTIVE:
        raise ReviewError(409, f"이미 닫힌 작업이라 {verb}할 수 없습니다 (현재 {t['status']})")


def record_decision(action: str, by: str | None, **extra) -> dict:
    return {"action": action, "by": by, "at": _now(), **{k: v for k, v in extra.items() if v is not None}}


def assign(conn, task_id: int, assignee: str | None) -> dict:
    """담당 지정(None이면 해제). 닫힌 작업은 바꾸지 않는다. 커밋하지 않는다."""
    t = _lock(conn, task_id)
    _active(t, "담당을 바꿀")
    _save(conn, t, t["status"], assignee, t["decision"], False)
    return t


def resolve(conn, task_id: int, decision: dict, note: str | None, by: str | None) -> dict:
    t = _lock(conn, task_id)
    _active(t, "해결")
    _save(conn, t, "RESOLVED", t["assignee"],
          record_decision("resolve", by or t["assignee"], value=decision, note=note), True)
    return t


def dismiss(conn, task_id: int, reason: str, by: str | None) -> dict:
    t = _lock(conn, task_id)
    _active(t, "'문제 없음'으로 닫을")
    _save(conn, t, "DISMISSED", t["assignee"], record_decision("dismiss", by or t["assignee"], reason=reason), True)
    return t


def hold(conn, task_id: int, note: str | None, by: str | None) -> dict:
    t = _lock(conn, task_id)
    if t["status"] != "OPEN":
        raise ReviewError(409, f"열린 작업만 보류할 수 있습니다 (현재 {t['status']})")
    _save(conn, t, "HOLD", t["assignee"], record_decision("hold", by or t["assignee"], note=note), False)
    return t


def reopen(conn, task_id: int, note: str | None, by: str | None) -> dict:
    """보류·해결·문제 없음을 되돌린다. 자동으로 닫힌 작업(사람 결정 없음)은 문제가 사라진 것이라 되돌리지 않는다."""
    t = _lock(conn, task_id)
    if t["status"] == "OPEN":
        raise ReviewError(409, "이미 열린 작업입니다")
    if not (t["decision"] or {}).get("by") and not (t["decision"] or {}).get("action"):
        raise ReviewError(409, "자동으로 닫힌 작업(문제가 사라짐)은 다시 열 수 없습니다")
    _save(conn, t, "OPEN", t["assignee"], record_decision("reopen", by or t["assignee"], note=note), False)
    return t


def bulk_assign(conn, ids: list[int], assignee: str | None) -> dict:
    """열린·보류 작업만 담당을 바꾼다. 없는 id·닫힌 작업은 skipped로 돌려준다. 커밋하지 않는다."""
    rows = conn.execute("SELECT id, kind, target, detail, status, decision FROM regulation.review_task"
                        " WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (ids,)).fetchall()
    done = []
    for t in rows:
        if t["status"] in ACTIVE:
            _save(conn, t, t["status"], assignee, t["decision"], False)
            done.append(t["id"])
    return {"updated": done, "skipped": sorted(set(ids) - set(done))}

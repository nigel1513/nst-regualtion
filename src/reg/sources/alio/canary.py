"""ALIO 응답 구조 사전 점검 (spec 1A.6-3).

일 배치 첫 태스크(active_institutions)가 목록 1쪽 + 상세 1건을 받아, client·sync가 기대는 필드명·형식을 확인한다.
- 구조가 다르면 AlioSchemaChanged: 전체 수집을 시작하지 않고 원인이 보이는 메시지로 실패한다(사람이 client를 고칠 일).
- 점검 중·장애(JSON 아님, status≠success)는 AlioError: 구조 변경이 아니며 Airflow가 재시도한다.
"""
import re

from reg.sources.alio.client import FINGERPRINT_KEYS, AlioClient, AlioError, parse_bfiles

CANARY_WORD = "한국천문연구원"
CANARY_APBA_ID = "C0266"
CANARY_SEQ = "47852"   # 한국천문연구원 스쿨운영규정 (개정 파일 2개). 폐지되면 다른 seq로 대신 점검하고 경고를 남긴다
LIST_PATH = "/occasional/findRuleList.json"
DETAIL_PATH = "/occasional/findRuleDtl.json"
_DATE = re.compile(r"^\d{4}[./-]\d{1,2}[./-]\d{1,2}")


class AlioSchemaChanged(Exception):
    """ALIO 응답 구조가 client가 기대하는 것과 다르다."""


def _need(obj, key: str, types: tuple, where: str, problems: list[str], nullable: bool = False):
    if not isinstance(obj, dict) or key not in obj:
        problems.append(f"{where}.{key} 없음")
        return None
    v = obj[key]
    if v is None and nullable:
        return None
    if not isinstance(v, types):
        problems.append(f"{where}.{key} 형식 {'/'.join(t.__name__ for t in types)} 아님 ({type(v).__name__})")
        return None
    return v


def _date_ok(v, where: str, key: str, problems: list[str]) -> None:
    if isinstance(v, str) and v and not _DATE.match(v):
        problems.append(f"{where}.{key} 날짜 형식 아님 ({v!r})")


def _envelope(body: dict, name: str) -> None:
    if "status" not in body:
        raise AlioSchemaChanged(f"ALIO 응답 구조 변경: {name} status 없음 (키: {sorted(body)[:8]})")
    if body["status"] != "success":
        raise AlioError(f"{name}: status={body['status']} message={body.get('message')}")


def check_list(body: dict, apba_id: str) -> list[str]:
    p: list[str] = []
    w = "findRuleList data"
    data = _need(body, "data", (dict,), "findRuleList", p)
    if data is None:
        return p
    rows = _need(data, "result", (list,), w, p)
    page = _need(data, "page", (dict,), w, p)
    if page is not None:
        tp = _need(page, "totalPage", (int, str), f"{w}.page", p)
        if tp is not None and not str(tp).isdigit():
            p.append(f"{w}.page.totalPage 숫자 아님 ({tp!r})")
    if rows is None:
        return p
    if not rows:
        p.append(f"{w}.result 비어 있음 (검색어 {CANARY_WORD})")
        return p
    for i, row in enumerate(rows[:3]):
        where = f"{w}.result[{i}]"
        _need(row, "seq", (str, int), where, p)
        _need(row, "title", (str,), where, p)
        _need(row, "apbaId", (str,), where, p)
        _need(row, "insdRuleDivis", (str,), where, p, nullable=True)
        for k in FINGERPRINT_KEYS:
            _need(row, k, (str, int), where, p, nullable=True)
        for k in ("ruleStDa", "idate"):
            _date_ok(row.get(k) if isinstance(row, dict) else None, where, k, p)
    if not any(isinstance(r, dict) and r.get("apbaId") == apba_id for r in rows):
        p.append(f"{w}.result에 apbaId={apba_id} 행 없음 (기관 필터 필드 변경 의심)")
    return p


def check_detail(body: dict, seq: str) -> list[str]:
    p: list[str] = []
    name = f"findRuleDtl(seq={seq})"
    w = f"{name} data"
    d = _need(body, "data", (dict,), name, p)
    if d is None:
        return p
    _need(d, "title", (str,), w, p)
    _need(d, "insdRuleDivis", (str,), w, p, nullable=True)
    for k in ("retryRvsnYmd", "idate"):
        _date_ok(_need(d, k, (str,), w, p, nullable=True), w, k, p)
    bf = _need(d, "bFiles", (str,), w, p)
    if bf is not None:
        files = parse_bfiles(bf)
        if not files:
            p.append(f"{w}.bFiles 파일 목록을 읽지 못함 ({bf[:60]!r})")
        elif not all(no.isdigit() for no, _ in files):
            p.append(f"{w}.bFiles fileNo가 숫자 아님 ({files[0][0]!r})")
    return p


def _fail(problems: list[str]) -> None:
    if problems:
        raise AlioSchemaChanged("ALIO 응답 구조 변경: " + "; ".join(problems))


def run_canary(alio: AlioClient, seq: str = CANARY_SEQ) -> dict:
    lst = alio.raw(LIST_PATH, {"type": "apbaNa", "word": CANARY_WORD, "pageNo": 1})
    _envelope(lst, "findRuleList")
    _fail(check_list(lst, CANARY_APBA_ID))
    rows = lst["data"]["result"]
    warning = None
    det = alio.raw(DETAIL_PATH, {"seq": seq})
    if det.get("status") != "success":
        other = next((str(r["seq"]) for r in rows if r.get("apbaId") == CANARY_APBA_ID and str(r["seq"]) != seq), None)
        if other is None:
            _envelope(det, f"findRuleDtl(seq={seq})")
        warning = (f"점검용 seq {seq} 상세 조회 실패(status={det.get('status')}) — {other}로 대신 점검함."
                   " canary.CANARY_SEQ를 바꾸세요")
        seq = other
        det = alio.raw(DETAIL_PATH, {"seq": seq})
    _envelope(det, f"findRuleDtl(seq={seq})")
    _fail(check_detail(det, seq))
    return {"ok": True, "seq": seq, "rows": len(rows), "files": len(parse_bfiles(det["data"]["bFiles"])),
            "warning": warning}

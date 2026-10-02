"""lawgo 테스트 도우미: 실제 응답과 같은 모양의 합성 XML, 가짜 DRF 클라이언트, 미러·내부규정 적재.

합성 XML의 태그는 fixtures/의 실제 응답(2026-10-02)과 같다. 사이트 구조가 바뀌면 fixture와 함께 여기도 고친다.
"""
from datetime import date

from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.model import ParsedDoc
from reg.core.refs import resolve_and_store
from reg.platform.archive import store
from reg.platform.sniff import FileKind
from reg.sources.lawgo.mirror import VersionHeader, apply_version
from reg.sources.lawgo.xml import parse_admrul_xml, parse_law_xml

XML = FileKind("application/xml", "xml")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def _c(s: str) -> str:
    return f"<![CDATA[{s}]]>"


def ymd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def law_list(rows: list[dict], total: int | None = None, page: int = 1) -> bytes:
    """rows: {mst, law_id, name, date(YYYYMMDD), [abbr, kind, no, status, ministry]}"""
    items = "".join(
        f'<law id="{i}"><법령일련번호>{r["mst"]}</법령일련번호><현행연혁코드>{r.get("status", "현행")}</현행연혁코드>'
        f'<법령명한글>{_c(r["name"])}</법령명한글><법령약칭명>{_c(r.get("abbr", ""))}</법령약칭명><법령ID>{r["law_id"]}</법령ID>'
        f'<공포일자>{r["date"]}</공포일자><공포번호>{r.get("no", "100")}</공포번호><제개정구분명>일부개정</제개정구분명>'
        f'<소관부처명>{r.get("ministry", "인사혁신처")}</소관부처명><법령구분명>{r.get("kind", "대통령령")}</법령구분명>'
        f'<시행일자>{r["date"]}</시행일자></law>' for i, r in enumerate(rows, 1))
    return (f'<?xml version="1.0" encoding="UTF-8"?><LawSearch><target>law</target>'
            f'<totalCnt>{len(rows) if total is None else total}</totalCnt><page>{page}</page>{items}</LawSearch>').encode()


def admrul_list(rows: list[dict], total: int | None = None, page: int = 1) -> bytes:
    """rows: {seq, admrul_id, name, date, [kind, no, status, ministry]}"""
    items = "".join(
        f'<admrul id="{i}"><행정규칙일련번호>{r["seq"]}</행정규칙일련번호><행정규칙명>{_c(r["name"])}</행정규칙명>'
        f'<행정규칙종류>{r.get("kind", "고시")}</행정규칙종류><발령일자>{r["date"]}</발령일자>'
        f'<발령번호>{r.get("no", "2026-1")}</발령번호><소관부처명>{r.get("ministry", "과학기술정보통신부")}</소관부처명>'
        f'<현행연혁구분>{r.get("status", "현행")}</현행연혁구분><제개정구분명>일부개정</제개정구분명>'
        f'<행정규칙ID>{r["admrul_id"]}</행정규칙ID><시행일자>{r["date"]}</시행일자></admrul>' for i, r in enumerate(rows, 1))
    return (f'<?xml version="1.0" encoding="UTF-8"?><AdmRulSearch><target>admrul</target>'
            f'<totalCnt>{len(rows) if total is None else total}</totalCnt><page>{page}</page>{items}</AdmRulSearch>'
            ).encode()


def licbyl_list(rows: list[dict], total: int | None = None, page: int = 1) -> bytes:
    """rows: {seq, mst, law_id, title, [owner, number, kind, date]} — 파일링크는 flSeq={seq}1, PDF는 {seq}2"""
    items = "".join(
        f'<licbyl id="{i}"><별표일련번호>{r["seq"]}</별표일련번호><관련법령일련번호>{r["mst"]}</관련법령일련번호>'
        f'<관련법령ID>{r["law_id"]}</관련법령ID><별표명>{_c(r["title"])}</별표명><관련법령명>{_c(r.get("owner", ""))}</관련법령명>'
        f'<별표번호>{r.get("number", "000100")}</별표번호><별표종류>{r.get("kind", "별표")}</별표종류>'
        f'<공포일자>{r.get("date", "20260630")}</공포일자><별표서식파일링크>/LSW/flDownload.do?flSeq={r["seq"]}1</별표서식파일링크>'
        f'<별표서식PDF파일링크>/LSW/flDownload.do?flSeq={r["seq"]}2</별표서식PDF파일링크></licbyl>'
        for i, r in enumerate(rows, 1))
    return (f'<?xml version="1.0" encoding="UTF-8"?><licBylSearch><target>licbyl</target>'
            f'<totalCnt>{len(rows) if total is None else total}</totalCnt><page>{page}</page>{items}</licBylSearch>').encode()


def admbyl_list(rows: list[dict], total: int | None = None, page: int = 1) -> bytes:
    """rows: {seq, mst, admrul_id, title, [owner, number, kind, date]} — PDF 링크 없음 (실제와 같음)"""
    items = "".join(
        f'<admrulbyl id="{i}"><별표일련번호>{r["seq"]}</별표일련번호><관련행정규칙일련번호>{r["mst"]}</관련행정규칙일련번호>'
        f'<별표명>{_c(r["title"])}</별표명><관련행정규칙명>{_c(r.get("owner", ""))}</관련행정규칙명>'
        f'<별표번호>{r.get("number", "000100")}</별표번호><별표종류>{r.get("kind", "별지")}</별표종류>'
        f'<발령일자>{r.get("date", "20260506")}</발령일자><관련법령ID>{r["admrul_id"]}</관련법령ID>'
        f'<별표서식파일링크>/LSW/flDownload.do?flSeq={r["seq"]}1</별표서식파일링크></admrulbyl>'
        for i, r in enumerate(rows, 1))
    return (f'<?xml version="1.0" encoding="UTF-8"?><admRulBylSearch><target>admbyl</target>'
            f'<totalCnt>{len(rows) if total is None else total}</totalCnt><page>{page}</page>{items}</admRulBylSearch>'
            ).encode()


def law_body(law_id: str, name: str, articles: dict, on: str = "20260630", no: str = "100",
             kind: str = "대통령령") -> bytes:
    """articles: {조번호 또는 "11-2": (제목, 본문) 또는 (제목, 본문, [항 본문, …])}"""
    units = []
    for key, spec in articles.items():
        title, text = spec[0], spec[1]
        paras = spec[2] if len(spec) > 2 else []
        n, _, b = str(key).partition("-")
        label = f"제{n}조" + (f"의{b}" if b else "")
        hang = "".join(f"<항><항번호>{CIRCLED[k]}</항번호><항내용>{_c(f'{CIRCLED[k]} {t}')}</항내용></항>"
                       for k, t in enumerate(paras))
        units.append(f'<조문단위><조문번호>{n}</조문번호><조문가지번호>{b}</조문가지번호><조문여부>조문</조문여부>'
                     f'<조문제목>{_c(title)}</조문제목><조문내용>{_c(f"{label}({title}) {text}")}</조문내용>{hang}</조문단위>')
    return (f'<?xml version="1.0" encoding="UTF-8"?><법령><기본정보><법령ID>{law_id}</법령ID><공포일자>{on}</공포일자>'
            f'<공포번호>{no}</공포번호><법종구분>{kind}</법종구분><법령명_한글>{_c(name)}</법령명_한글>'
            f'<시행일자>{on}</시행일자><제개정구분>일부개정</제개정구분></기본정보><조문>{"".join(units)}</조문></법령>'
            ).encode()


def admrul_body(admrul_id: str, name: str, articles: dict, on: str = "20260506", no: str = "2026-38",
                kind: str = "고시", ministry: str = "과학기술정보통신부") -> bytes:
    arts = "".join(f"<조문내용>{_c(f'제{k}조({t}) {x}')}</조문내용>" for k, (t, x) in articles.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?><AdmRulService><행정규칙기본정보><행정규칙명>{_c(name)}</행정규칙명>'
            f'<행정규칙종류>{kind}</행정규칙종류><발령일자>{on}</발령일자><발령번호>{no}</발령번호>'
            f'<제개정구분명>일부개정</제개정구분명><행정규칙ID>{admrul_id}</행정규칙ID><소관부처명>{ministry}</소관부처명>'
            f'<시행일자>{on}</시행일자></행정규칙기본정보>{arts}</AdmRulService>').encode()


EMPTY = {"law": lambda: law_list([]), "admrul": lambda: admrul_list([]), "licbyl": lambda: licbyl_list([]),
         "admbyl": lambda: admbyl_list([])}


class FakeClient:
    """LawGoClient와 같은 메서드. lists[(target, page, query)]와 bodies[(target, key)]에 응답을 넣는다."""

    def __init__(self):
        self.lists: dict[tuple, bytes] = {}
        self.bodies: dict[tuple, bytes] = {}
        self.calls: list[tuple] = []

    def search(self, target, *, page=1, display=100, sort=None, query=None, search=None) -> bytes:
        self.calls.append(("search", target, page, query))
        return self.lists.get((target, page, query)) or EMPTY[target]()

    def service(self, target, key) -> bytes:
        self.calls.append(("service", target, key))
        return self.bodies[(target, key)]

    def annex_html(self, target, seq) -> bytes:
        self.calls.append(("annex", target, seq))
        return f"<html><body><script>alert(1)</script>별표 {seq}</body></html>".encode()

    def file(self, path) -> bytes:
        self.calls.append(("file", path))
        return b"%PDF-1.4 fake"

    def close(self) -> None:
        pass


def mirror_law(conn, blob, law_id: str, name: str, articles: dict, mst: str, *, abbr: str | None = None,
               kind: str = "대통령령", on: str = "20260630", no: str = "100", run_id: int | None = None) -> dict:
    data = law_body(law_id, name, articles, on=on, no=no, kind=kind) + f"<!-- {mst} -->".encode()
    sd = store(conn, blob, source="lawgo", url=f"test:law:{mst}", content=data, kind=XML, meta={"mst": mst})
    d = ymd(on)
    h = VersionHeader("law", law_id, name, abbr, kind, "인사혁신처", mst, d, no, d, "일부개정")
    return apply_version(conn, h, parse_law_xml(data), sd.id, run_id)


def mirror_admrul(conn, blob, data: bytes, seq: str, run_id: int | None = None) -> dict:
    doc = parse_admrul_xml(data)
    m = doc.meta
    sd = store(conn, blob, source="lawgo", url=f"test:admrul:{seq}", content=data, kind=XML, meta={"mst": seq})
    h = VersionHeader("admrul", m["admrul_id"], doc.title, None, m["kind"], m["ministry"], seq,
                      date.fromisoformat(m["promulgated_on"]), m["promulgation_no"],
                      date.fromisoformat(m["effective_on"]), m["amendment_kind"])
    return apply_version(conn, h, doc, sd.id, run_id)


def load_reg(conn, blob, wid: str, title: str, provs: list, inst: str = "KASI") -> None:
    """내부규정 한 판본을 core로 적재하고 참조까지 만든다 (현행 버전)."""
    iid = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES (%s, %s, 'GRI')"
                       " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING id", (inst, inst)).fetchone()["id"]
    upsert_work(conn, wid, "INTERNAL_REG", title, iid, {})
    sid = store(conn, blob, source="alio", url="u", content=b"%PDF" + wid.encode(),
                kind=FileKind("application/pdf", "pdf"), meta={}).id
    add_version(conn, wid, sid, ParsedDoc(title, None, [], provs), Effective(date(2024, 1, 1), "api", "CONFIRMED", None))
    rebuild_work(conn, wid, date(2026, 10, 2))
    resolve_and_store(conn, wid)

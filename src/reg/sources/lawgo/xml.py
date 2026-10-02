"""law.go.kr lawService XML → ParsedDoc. 조문·항·호·목·부칙이 태그로 나뉘어 있어 그대로 옮긴다."""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from reg.core.model import ParsedDoc, Prov
from reg.core.text import clean, parse_dot_date, split_notes
from reg.sources.lawgo.errors import ResponseChanged

RE_HEAD = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:\([^()]*\))?\s*")
RE_CH = re.compile(r"제\s*(\d+)\s*(장|절)\s*(.*)")


def _t(e, tag: str) -> str:
    return clean(e.findtext(tag) or "")


def _o(e, tag: str) -> str | None:
    return _t(e, tag) or None


def _d(e, tag: str) -> date | None:
    s = _t(e, tag)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])) if len(s) == 8 and s.isdigit() else None


@dataclass
class LawRow:
    mst: str
    law_id: str
    name: str
    abbr: str | None
    kind: str | None
    ministry: str | None
    promulgated_on: date | None
    promulgation_no: str | None
    effective_on: date | None
    revision_kind: str | None
    status: str
    ministry_code: str | None = None

    @property
    def master_id(self) -> str:
        return self.law_id


@dataclass
class AdmrulRow:
    seq: str
    admrul_id: str
    name: str
    kind: str | None
    ministry: str | None
    issued_on: date | None
    issue_no: str | None
    effective_on: date | None
    revision_kind: str | None
    status: str
    ministry_code: str | None = None  # admrul 목록에는 없다. 본문(ministry_of)에서 채운다

    @property
    def master_id(self) -> str:
        return f"admrul:{self.admrul_id}"


@dataclass
class AnnexRow:
    seq: str
    family: str             # law | admrul
    owner_key: str          # 관련법령일련번호 / 관련행정규칙일련번호
    owner_source_id: str    # 관련법령ID (admbyl에서도 태그 이름은 같고 값은 행정규칙ID)
    owner_name: str
    number: str | None      # 6자리: 앞 4자리 번호 + 뒤 2자리 가지번호
    kind: str | None        # 별표 | 서식 | 별지 …
    title: str
    promulgated_on: date | None
    file_path: str | None
    pdf_path: str | None

    @property
    def master_id(self) -> str:
        return self.owner_source_id if self.family == "law" else f"admrul:{self.owner_source_id}"


@dataclass
class ListPage:
    target: str
    total: int
    page: int
    rows: list


def _law_row(e) -> LawRow:
    return LawRow(_t(e, "법령일련번호"), _t(e, "법령ID"), _t(e, "법령명한글"), _o(e, "법령약칭명"), _o(e, "법령구분명"),
                  _o(e, "소관부처명"), _d(e, "공포일자"), _o(e, "공포번호"), _d(e, "시행일자"), _o(e, "제개정구분명"),
                  _t(e, "현행연혁코드"), _o(e, "소관부처코드"))


def _admrul_row(e) -> AdmrulRow:
    return AdmrulRow(_t(e, "행정규칙일련번호"), _t(e, "행정규칙ID"), _t(e, "행정규칙명"), _o(e, "행정규칙종류"),
                     _o(e, "소관부처명"), _d(e, "발령일자"), _o(e, "발령번호"), _d(e, "시행일자"), _o(e, "제개정구분명"),
                     _t(e, "현행연혁구분"), _o(e, "소관부처코드"))


def _licbyl_row(e) -> AnnexRow:
    return AnnexRow(_t(e, "별표일련번호"), "law", _t(e, "관련법령일련번호"), _t(e, "관련법령ID"), _t(e, "관련법령명"),
                    _o(e, "별표번호"), _o(e, "별표종류"), _t(e, "별표명"), _d(e, "공포일자"), _o(e, "별표서식파일링크"),
                    _o(e, "별표서식PDF파일링크"))


def _admbyl_row(e) -> AnnexRow:
    return AnnexRow(_t(e, "별표일련번호"), "admrul", _t(e, "관련행정규칙일련번호"), _t(e, "관련법령ID"),
                    _t(e, "관련행정규칙명"), _o(e, "별표번호"), _o(e, "별표종류"), _t(e, "별표명"), _d(e, "발령일자"),
                    _o(e, "별표서식파일링크"), None)


LIST_SPEC = {  # target: (최상위 태그, 행 태그, 필수 태그, 행 생성)
    "law": ("LawSearch", "law", ("법령일련번호", "법령ID", "법령명한글", "공포일자", "현행연혁코드"), _law_row),
    "admrul": ("AdmRulSearch", "admrul", ("행정규칙일련번호", "행정규칙ID", "행정규칙명", "발령일자", "현행연혁구분"),
               _admrul_row),
    "licbyl": ("licBylSearch", "licbyl", ("별표일련번호", "관련법령일련번호", "관련법령ID", "별표명"), _licbyl_row),
    "admbyl": ("admRulBylSearch", "admrulbyl", ("별표일련번호", "관련행정규칙일련번호", "관련법령ID", "별표명"),
               _admbyl_row),
}


def parse_list(target: str, data: bytes) -> ListPage:
    root_tag, row_tag, required, make = LIST_SPEC[target]
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ResponseChanged(f"{target} 목록: XML 해석 실패 ({e})") from e
    if root.tag != root_tag:
        raise ResponseChanged(f"{target} 목록 응답 구조 변경: 최상위 <{root.tag}> (기대 <{root_tag}>)")
    total = (root.findtext("totalCnt") or "").strip()
    if not total.isdigit():
        raise ResponseChanged(f"{target} 목록 응답 구조 변경: <totalCnt> 없음")
    rows = []
    for e in root.findall(row_tag):
        for tag in required:
            if e.find(tag) is None:
                raise ResponseChanged(f"{target} 목록 응답 구조 변경: <{row_tag}>에 <{tag}> 없음")
        rows.append(make(e))
    page = (root.findtext("page") or "1").strip()
    return ListPage(target, int(total), int(page) if page.isdigit() else 1, rows)


def ministry_of(data: bytes) -> tuple[str | None, str | None]:
    """본문 XML의 소관부처 (이름, 코드). 법령은 <기본정보><소관부처 소관부처코드=…>, 행정규칙은 <행정규칙기본정보>."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None, None
    info = root.find("기본정보")
    if info is not None:
        e = info.find("소관부처")
        name = _o(info, "소관부처명") or (clean(e.text or "") or None if e is not None else None)
        code = _o(info, "소관부처코드") or (e.get("소관부처코드") if e is not None else None)
        return name, code or None
    info = root.find("행정규칙기본정보")
    if info is not None:
        return _o(info, "소관부처명"), _o(info, "소관부처코드")
    return None, None


def row_date(r) -> date | None:
    return r.promulgated_on if isinstance(r, LawRow) else r.issued_on


def _txt(e, tag: str) -> str:
    return clean(e.findtext(tag) or "")


def _iso(s: str) -> str | None:
    d = parse_dot_date(s)
    return d.isoformat() if d else None


def _strip_marker(s: str, marker: str) -> str:
    return s[len(marker):].strip() if marker and s.startswith(marker) else s


def parse_law_xml(data: bytes) -> ParsedDoc:
    root = ET.fromstring(data)
    info = root.find("기본정보")
    if info is None:
        raise ResponseChanged("law 본문 응답 구조 변경: <기본정보> 없음")
    eff = _iso(_txt(info, "시행일자"))
    meta = {"law_id": _txt(info, "법령ID"), "promulgated_on": _iso(_txt(info, "공포일자")), "effective_on": eff,
            "amendment_kind": _txt(info, "제개정구분") or None, "kind": _txt(info, "법종구분") or None,
            "promulgation_no": _txt(info, "공포번호") or None}
    provs: list[Prov] = []
    chapter = None

    def add(p: Prov, raw: str) -> Prov:
        p.text, notes = split_notes(raw)
        p.annotations += notes
        if p.text in ("삭제", "삭제."):
            p.deleted = True
        provs.append(p)
        return p

    for u in root.iter("조문단위"):
        if _txt(u, "조문여부") == "전문":
            m = RE_CH.search(_txt(u, "조문내용"))
            if m and m[2] == "장":
                chapter = f"c{int(m[1])}"
                provs.append(Prov(chapter, "chapter", f"제{int(m[1])}장", heading=clean(m[3]) or None))
            elif m and chapter:
                provs.append(Prov(f"{chapter}-s{int(m[1])}", "section", f"제{int(m[1])}절",
                                  heading=clean(m[3]) or None, parent=chapter))
            continue
        no, branch = _txt(u, "조문번호"), _txt(u, "조문가지번호")
        key = f"a{int(no)}" + (f"-{int(branch)}" if branch and branch != "0" else "")
        label = f"제{int(no)}조" + (f"의{int(branch)}" if branch and branch != "0" else "")
        lead = RE_HEAD.sub("", _txt(u, "조문내용"), count=1)
        art = add(Prov(key, "article", label, heading=_txt(u, "조문제목") or None, parent=chapter), lead)
        ae = _iso(_txt(u, "조문시행일자"))
        if ae and ae != eff:
            art.effective_override = parse_dot_date(ae)
        for h in u.findall("항"):
            hno = _txt(h, "항번호")
            parent = key
            if hno:
                parent = f"{key}.p{'①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'.index(hno[0]) + 1}"
                add(Prov(parent, "paragraph", hno[0], parent=key), _strip_marker(_txt(h, "항내용"), hno))
            for ho in h.findall("호"):
                body = _txt(ho, "호내용")
                head = re.match(r"(\d+)(?:의(\d+))?\.", body)  # 가지호(5의2)는 호번호가 아니라 본문 머리에만 있다
                hono = head[0] if head else _txt(ho, "호번호")
                m = re.match(r"(\d+)(?:의(\d+))?", hono)
                ikey = f"{parent}.i{int(m[1])}" + (f"-{int(m[2])}" if m and m[2] else "") if m else f"{parent}.i?"
                add(Prov(ikey, "item", hono, parent=parent), _strip_marker(body, hono))
                for mo in ho.findall("목"):
                    mono = _txt(mo, "목번호")
                    add(Prov(f"{ikey}.s{mono[:1]}", "subitem", mono, parent=ikey),
                        _strip_marker(_txt(mo, "목내용"), mono))
    seen: dict[str, int] = {}
    for s in root.iter("부칙단위"):
        d = _iso(_txt(s, "부칙공포일자"))
        base = f"supp@{d}" if d else f"supp#{len(seen) + 1}"
        seen[base] = seen.get(base, 0) + 1
        path = base if seen[base] == 1 else f"{base}~{seen[base]}"
        provs.append(Prov(path, "supplement", "부칙", text=clean(s.findtext("부칙내용") or ""),
                          meta={"date": d, "number": _txt(s, "부칙공포번호") or None}))
    return ParsedDoc(clean(info.findtext("법령명_한글") or ""), None, [], provs, meta)


CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_ADM_ART = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(([^()]*)\))?\s*")
RE_ADM_CH = re.compile(r"^제\s*(\d+)\s*(장|절)\s*(.*)$")
RE_ADM_PARA = re.compile(r"(?:^|\n)\s*([①-⑳])\s*")


def parse_admrul_xml(data: bytes) -> ParsedDoc:
    """lawService target=admrul XML → ParsedDoc. <조문내용>에 조 전체가 문자열로 있다: 조·항까지만 나눈다 (판정 R14)."""
    root = ET.fromstring(data)
    info = root.find("행정규칙기본정보")
    if info is None:
        raise ResponseChanged("admrul 본문 응답 구조 변경: <행정규칙기본정보> 없음")
    meta = {"admrul_id": _txt(info, "행정규칙ID"), "promulgated_on": _iso(_txt(info, "발령일자")),
            "effective_on": _iso(_txt(info, "시행일자")), "amendment_kind": _txt(info, "제개정구분명") or None,
            "kind": _txt(info, "행정규칙종류") or None, "promulgation_no": _txt(info, "발령번호") or None,
            "ministry": _txt(info, "소관부처명") or None}
    provs: list[Prov] = []
    chapter = None

    def add(p: Prov, raw: str) -> None:
        p.text, notes = split_notes(raw)
        p.annotations += notes
        if p.text in ("삭제", "삭제."):
            p.deleted = True
        provs.append(p)

    for i, e in enumerate(root.findall("조문내용"), 1):
        body = (e.text or "").strip()
        if not body:
            continue
        m = RE_ADM_ART.match(body)
        ch = RE_ADM_CH.match(body.splitlines()[0].strip())
        if ch and not m:
            if ch[2] == "장":
                chapter = f"c{int(ch[1])}"
                provs.append(Prov(chapter, "chapter", f"제{int(ch[1])}장", heading=clean(ch[3]) or None))
            elif chapter:
                provs.append(Prov(f"{chapter}-s{int(ch[1])}", "section", f"제{int(ch[1])}절",
                                  heading=clean(ch[3]) or None, parent=chapter))
            continue
        if not m:
            add(Prov(f"body{i}", "article", "본문", parent=chapter), body)
            continue
        key = f"a{int(m[1])}" + (f"-{int(m[2])}" if m[2] else "")
        label = f"제{int(m[1])}조" + (f"의{int(m[2])}" if m[2] else "")
        parts = RE_ADM_PARA.split(body[m.end():])
        add(Prov(key, "article", label, heading=clean(m[3] or "") or None, parent=chapter), parts[0])
        for j in range(1, len(parts) - 1, 2):
            add(Prov(f"{key}.p{CIRCLED.index(parts[j]) + 1}", "paragraph", parts[j], parent=key), parts[j + 1])
    sup = root.find("부칙")
    if sup is not None:
        seen: dict[str, int] = {}
        cur: dict[str, str] = {}
        for c in sup:  # <부칙공포일자><부칙공포번호><부칙내용>이 형제로 반복된다
            cur[c.tag] = c.text or ""
            if c.tag != "부칙내용":
                continue
            d = _iso(clean(cur.get("부칙공포일자", "")))
            base = f"supp@{d}" if d else f"supp#{len(seen) + 1}"
            seen[base] = seen.get(base, 0) + 1
            provs.append(Prov(base if seen[base] == 1 else f"{base}~{seen[base]}", "supplement", "부칙",
                              text=clean(cur["부칙내용"]),
                              meta={"date": d, "number": clean(cur.get("부칙공포번호", "")) or None}))
            cur = {}
    return ParsedDoc(_txt(info, "행정규칙명"), None, [], provs, meta)

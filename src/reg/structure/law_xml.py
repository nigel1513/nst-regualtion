"""law.go.kr lawService XML → ParsedDoc. 조문·항·호·목·부칙이 태그로 나뉘어 있어 그대로 옮긴다."""
import re
import xml.etree.ElementTree as ET

from reg.structure.model import ParsedDoc, Prov
from reg.structure.text import clean, parse_dot_date, split_notes

RE_HEAD = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:\([^()]*\))?\s*")
RE_CH = re.compile(r"제\s*(\d+)\s*(장|절)\s*(.*)")


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
                hono = _txt(ho, "호번호")
                m = re.match(r"(\d+)(?:의(\d+))?", hono)
                ikey = f"{parent}.i{int(m[1])}" + (f"-{int(m[2])}" if m and m[2] else "") if m else f"{parent}.i?"
                add(Prov(ikey, "item", hono, parent=parent), _strip_marker(_txt(ho, "호내용"), hono))
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

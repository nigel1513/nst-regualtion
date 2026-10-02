"""프로토타입 웹용 규정 데이터 생성.

data/samples 의 실제 ALIO 원본(HWP 5.0 / 텍스트 PDF)을 조·항 단위로 나누어
apps/web/src/data/regs/*.json 으로 저장한다. M2 정식 파서가 나오기 전까지 쓰는 임시 도구다.

실행: uv run --with olefile python tools/proto/build_data.py
"""
from __future__ import annotations

import json
import re
import struct
import subprocess
import zlib
from pathlib import Path

import olefile

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
OUT = ROOT / "apps" / "web" / "src" / "data" / "regs"

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_CHAPTER = re.compile(r"^제\s*(\d+)\s*장\s*(.*)$")
RE_ARTICLE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(([^)]*)\))?\s*(.*)$")
RE_SUPPL = re.compile(r"^부\s*칙\s*(?:<([^>]*)>)?")
RE_NOTE = re.compile(r"(<(?:개정|신설|본조신설|전문개정|제목개정)[^>]*>|\[(?:본조신설|제목개정|전문개정|본조개정|종전)[^\]]*\]|\[[^\]]*(?:신설|개정)[^\]]*\])")
LEADER = re.compile(r"·\s*·|^[·\s]+$")
RE_DATE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")


# ---------------------------------------------------------------- extraction

def hwp_paragraphs(path: Path) -> list[str]:
    ole = olefile.OleFileIO(str(path))
    compressed = ole.openstream("FileHeader").read()[36] & 1
    sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"), key=lambda e: int(e[1][7:]))
    out: list[str] = []
    for sec in sections:
        data = ole.openstream(sec).read()
        if compressed:
            data = zlib.decompress(data, -15)
        i = 0
        while i < len(data):
            header = struct.unpack_from("<I", data, i)[0]
            tag, size = header & 0x3FF, (header >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", data, i)[0]
                i += 4
            if tag == 67:  # HWPTAG_PARA_TEXT
                raw = data[i:i + size].decode("utf-16le", "ignore")
                text = "".join(c for c in raw if ord(c) >= 32).strip()
                if text:
                    out.append(text)
            i += size
    return out


def pdf_pages(path: Path) -> list[list[str]]:
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout).group(1))
    pages = []
    for p in range(1, n + 1):
        txt = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), str(path), "-"], capture_output=True, text=True).stdout
        pages.append(txt.splitlines())
    return pages


def is_boundary(line: str) -> bool:
    s = line.strip()
    return bool(RE_CHAPTER.match(s) or RE_ARTICLE.match(s) or RE_SUPPL.match(s)
                or (s and s[0] in CIRCLED) or re.match(r"^\d+\.\s", s) or re.match(r"^[가-하]\.\s", s)
                or s.startswith("[본조신설") or s.startswith("[제목개정"))


def pdf_paragraphs(path: Path, title: str) -> tuple[list[tuple[str, int]], list[str]]:
    """PDF 줄을 문단으로 합친다. (문단, 쪽) 목록과 본문 앞 머리부 줄을 돌려준다."""
    pages = pdf_pages(path)
    lines: list[tuple[str, int]] = []
    for pno, page in enumerate(pages, 1):
        for ln in page:
            s = ln.strip()
            if not s or re.fullmatch(r"-\s*\d+\s*-", s) or re.fullmatch(rf"{re.escape(title)}\s*\d*", s) or s in {"·", "··"}:
                continue
            lines.append((s, pno))
    # 목차(점선 리더) 이후 첫 '제1조(' 줄이 본문 시작
    start = next(i for i, (s, _) in enumerate(lines)
                 if re.match(r"^제\s*1\s*조\s*\(", s) and i > 0
                 and not any(LEADER.search(t) for t, _ in lines[i:i + 3]))
    # 본문 직전의 장 제목 포함
    while start > 0 and RE_CHAPTER.match(lines[start - 1][0]):
        start -= 1
    head = [s for s, _ in lines[:start]]
    body = lines[start:]

    vocab = set()
    for s, _ in body:
        words = s.split()
        for w in words[1:-1]:
            vocab.add(w.strip("(),.「」『』<>[]"))

    paras: list[tuple[str, int]] = []
    for s, pno in body:
        if not paras or is_boundary(s):
            paras.append((s, pno))
            continue
        prev, ppage = paras[-1]
        a = prev.split()[-1].strip("(),.「」<>[]") if prev.split() else ""
        b = s.split()[0].strip("(),.「」<>[]")
        joined_word = a + b
        if prev.endswith((".", ">", "]")) or a == "" or (a in vocab and b in vocab and joined_word not in vocab):
            sep = " "
        else:
            sep = ""
        paras.append((prev + sep + s, ppage))
        paras.pop(-2)
    return paras, head


# ---------------------------------------------------------------- structure

def split_notes(text: str) -> tuple[str, list[str]]:
    notes = [m.group(0) for m in RE_NOTE.finditer(text)]
    body = RE_NOTE.sub("", text).strip()
    return re.sub(r"\s{2,}", " ", body), notes


def split_items(text: str) -> list[str]:
    """문단 안에 붙어 있는 ①②… 를 항으로 나눈다."""
    parts = re.split(f"(?=[{CIRCLED}])", text)
    return [p.strip() for p in parts if p.strip()]


def article_key(no: str, sub: str | None) -> str:
    return f"a{no}" + (f"-{sub}" if sub else "")


def structure(paras: list[tuple[str, int]]) -> dict:
    chapters: list[dict] = []
    articles: list[dict] = []
    supplements: list[dict] = []
    cur_art = None
    cur_supp = None
    for text, page in paras:
        s = text.strip()
        if cur_supp is None and (m := RE_SUPPL.match(s)):
            cur_supp = {"label": "부칙" + (f" <{m.group(1).strip()}>" if m.group(1) else ""), "text": s[m.end():].strip(), "page": page}
            supplements.append(cur_supp)
            cur_art = None
            continue
        if cur_supp is not None:
            if (m := RE_SUPPL.match(s)):
                cur_supp = {"label": "부칙" + (f" <{m.group(1).strip()}>" if m.group(1) else ""), "text": s[m.end():].strip(), "page": page}
                supplements.append(cur_supp)
            else:
                cur_supp["text"] = (cur_supp["text"] + "\n" + s).strip()
            continue
        if (m := RE_CHAPTER.match(s)) and len(s) < 40:
            title = re.sub(r"\s+", " ", RE_NOTE.sub("", m.group(2))).strip()
            title = re.sub(r"(?<=[가-힣]) (?=[가-힣](?: |$))", "", title)  # '총 칙' → '총칙'
            chapters.append({"no": int(m.group(1)), "title": title, "articles": []})
            continue
        if (m := RE_ARTICLE.match(s)) and (m.group(3) is not None or "삭제" in s[:20]):
            no, sub, title, rest = m.group(1), m.group(2), (m.group(3) or "").strip(), m.group(4)
            key = article_key(no, sub)
            cur_art = {
                "key": key,
                "label": f"제{no}조" + (f"의{sub}" if sub else ""),
                "title": re.sub(r"\s+", "", title) if title else "",
                "chapter": chapters[-1]["no"] if chapters else None,
                "page": page,
                "deleted": rest.strip().startswith("삭제") and len(rest.strip()) < 30,
                "raw": [rest],
            }
            articles.append(cur_art)
            if chapters:
                chapters[-1]["articles"].append(key)
            continue
        if cur_art is not None:
            cur_art["raw"].append(s)

    for art in articles:
        joined = " ".join(r for r in art.pop("raw") if r)
        body, art_notes = "", []
        trailing = re.findall(r"\[(?:본조신설|제목개정|전문개정|본조개정)[^\]]*\]\s*$", joined)
        if trailing:
            joined = joined[: joined.rfind(trailing[-1])]
            art_notes = [t.strip() for t in trailing]
        paragraphs = []
        for idx, item in enumerate(split_items(joined)):
            no = CIRCLED.index(item[0]) + 1 if item[0] in CIRCLED else None
            text = item[1:].strip() if no else item
            text, notes = split_notes(text)
            # 호(1. 2.)는 줄바꿈으로 구분해 둔다
            text = re.sub(r"\s(?=\d{1,2}\.\s)", "\n", text)
            paragraphs.append({"no": no, "text": text, "notes": notes})
        art["paragraphs"] = paragraphs
        art["notes"] = art_notes
    return {"chapters": chapters, "articles": articles, "supplements": supplements}


# ---------------------------------------------------------------- references

KNOWN_EXTERNAL = {"공무원여비규정": "공무원 여비규정", "공무원 여비규정": "공무원 여비규정"}


def find_refs(reg: dict) -> None:
    keys = {a["key"] for a in reg["articles"]}
    for art in reg["articles"]:
        refs = []
        for p in art["paragraphs"]:
            t = p["text"]
            for m in re.finditer(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?", t):
                tgt = article_key(m.group(1), m.group(2))
                if tgt == art["key"] or tgt not in keys:
                    continue
                refs.append({"type": rel_type(t, m.end()), "target": tgt, "para": m.group(3) and int(m.group(3)),
                             "evidence": m.group(0), "from": p["no"]})
            for m in re.finditer(r"(?<!제\d)(?<!조)제\s*(\d+)\s*항(?:에도 불구하고|에 따른|의)", t):
                refs.append({"type": rel_type(t, m.end()), "target": art["key"], "para": int(m.group(1)),
                             "evidence": m.group(0), "from": p["no"]})
            for m in re.finditer(r"「([^」]+)」", t):
                refs.append({"type": rel_type(t, m.end()), "external": m.group(1).strip(), "evidence": m.group(0), "from": p["no"]})
            for name, canon in KNOWN_EXTERNAL.items():
                if name in t and f"「{name}」" not in t and not any(r.get("external") == canon for r in refs):
                    refs.append({"type": rel_type(t, t.find(name) + len(name)), "external": canon, "evidence": name, "from": p["no"]})
            for m in re.finditer(r"별(표|지)\s*(?:제\s*)?(\d+)(?:호)?(?:의(\d+))?(?:\s*서식)?", t):
                refs.append({"type": "CITATION", "annex": m.group(0).replace(" ", ""), "evidence": m.group(0), "from": p["no"]})
        seen, uniq = set(), []
        for r in refs:
            k = (r["type"], r.get("target"), r.get("para"), r.get("external"), r.get("annex"))
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        art["refs"] = uniq
    incoming: dict[str, list] = {}
    for art in reg["articles"]:
        for r in art["refs"]:
            if r.get("target") and r["target"] != art["key"]:
                incoming.setdefault(r["target"], []).append({"type": r["type"], "source": art["key"], "evidence": r["evidence"]})
    for art in reg["articles"]:
        art["incoming"] = incoming.get(art["key"], [])


def rel_type(text: str, pos: int) -> str:
    tail = text[pos:pos + 30]
    if "불구하고" in tail:
        return "EXCEPTION"
    if "준용" in tail:
        return "MUTATIS"
    if re.match(r"\s*(?:에\s*따라|에\s*의하여|에\s*근거)", tail):
        return "BASIS"
    return "CITATION"


# ---------------------------------------------------------------- versions / diff

def history_from_head(lines: list[str]) -> list[dict]:
    hist = []
    for s in lines:
        m = re.search(r"(제\s*정|전부\s*개정|개\s*정)\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*(규\s*제\s*\d+\s*호)?", s)
        if m:
            hist.append({"kind": re.sub(r"\s", "", m.group(1)), "date": f"{m.group(2)}-{int(m.group(3)):02d}-{int(m.group(4)):02d}",
                         "no": re.sub(r"\s", "", m.group(5)) if m.group(5) else None})
    return hist


def norm(art: dict) -> str:
    return re.sub(r"\s+", "", " ".join(p["text"] for p in art["paragraphs"]))


def diff(prev: dict, cur: dict) -> list[dict]:
    pa = {a["key"]: a for a in prev["articles"]}
    ca = {a["key"]: a for a in cur["articles"]}
    out = []
    for key in list(dict.fromkeys(list(ca) + list(pa))):
        a, b = pa.get(key), ca.get(key)
        if a and not b:
            out.append({"key": key, "kind": "DELETED", "old": a, "new": None})
        elif b and not a:
            out.append({"key": key, "kind": "ADDED", "old": None, "new": b})
        elif norm(a) != norm(b) or a["deleted"] != b["deleted"]:
            out.append({"key": key, "kind": "MODIFIED", "old": a, "new": b})
        elif [p["notes"] for p in a["paragraphs"]] != [p["notes"] for p in b["paragraphs"]] or a["title"] != b["title"]:
            out.append({"key": key, "kind": "ANNOTATION_ONLY" if a["title"] == b["title"] else "MODIFIED", "old": a, "new": b})
    order = {a["key"]: i for i, a in enumerate(cur["articles"])}
    out.sort(key=lambda d: order.get(d["key"], 10_000))
    return [{"key": d["key"], "kind": d["kind"],
             "old": d["old"] and {"label": d["old"]["label"], "title": d["old"]["title"], "paragraphs": d["old"]["paragraphs"]},
             "new": d["new"] and {"label": d["new"]["label"], "title": d["new"]["title"], "paragraphs": d["new"]["paragraphs"]}}
            for d in out]


# ---------------------------------------------------------------- build

def parse_hwp(path: Path) -> tuple[dict, list[str]]:
    paras = hwp_paragraphs(path)
    start = next(i for i, p in enumerate(paras) if RE_CHAPTER.match(p) or re.match(r"^제\s*1\s*조\s*\(", p))
    head, body = paras[:start], paras[start:]
    return structure([(p, None) for p in body]), head


def parse_pdf(path: Path, title: str) -> tuple[dict, list[str]]:
    paras, head = pdf_paragraphs(path, title)
    return structure(paras), head


def effective_from_supplements(supps: list[dict]) -> str | None:
    """마지막 부칙의 시행일. '○○부터 시행'이 없고 '결재/공포한 날부터'면 부칙 날짜를 쓴다."""
    if not supps:
        return None
    last = supps[-1]
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일부터\s*시행", last["text"])
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    d = RE_DATE.search(last["label"])
    if d and re.search(r"(결재를 받은|공포한|제정한|개정한)\s*날부터\s*시행", last["text"]):
        return f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"
    return None


def build(spec: dict) -> dict:
    parse = (lambda p: parse_pdf(p, spec["title"])) if spec["format"] == "pdf" else parse_hwp
    cur, head = parse(SAMPLES / spec["current"]["file"])
    prev, _ = parse(SAMPLES / spec["previous"]["file"])
    find_refs(cur)
    history = history_from_head(head)
    effective = effective_from_supplements(cur["supplements"]) or (history[-1]["date"] if history else None)
    return {
        "id": f"kr/reg/{spec['inst']}/{spec['title']}",
        "inst": spec["inst"],
        "slug": spec["slug"],
        "title": spec["title"],
        "classCode": spec.get("classCode"),
        "format": spec["format"],
        "effective": effective,
        "effectiveBasis": "부칙" if effective_from_supplements(cur["supplements"]) else "개정이력",
        "amendNo": history[-1]["no"] if history else None,
        "source": {"alioSeq": spec["alioSeq"], "posted": spec["posted"], "fileName": spec["current"]["name"],
                   "file": spec["current"].get("public"), "fileNo": spec["current"]["fileNo"]},
        "history": list(reversed(history)),
        "previous": {"effective": spec["previous"]["effective"], "fileName": spec["previous"]["name"]},
        **cur,
        "diff": diff(prev, cur),
    }


SPECS = [
    {
        "inst": "KASI", "slug": "yeobi", "title": "여비규정", "classCode": "2120", "format": "pdf",
        "alioSeq": "10512", "posted": "2024-01-17",
        "current": {"file": "kasi-yeobi-339.pdf", "name": "여비규정(2024년도 1월 개정).pdf", "fileNo": "186618", "public": "/files/kasi-yeobi-339.pdf"},
        "previous": {"file": "kasi-yeobi-326.pdf", "name": "여비규정(2023년도 4월 개정).pdf", "effective": "2023-04-18"},
    },
    {
        "inst": "NST", "slug": "yeobi", "title": "여비규정", "format": "hwp",
        "alioSeq": "1122", "posted": "2023-12-21",
        "current": {"file": "nst-yeobi-18.hwp", "name": "5-3 여비규정(제18차 개정).hwp", "fileNo": "184766"},
        "previous": {"file": "nst-yeobi-17.hwp", "name": "05-03. 여비규정 230601(17차 개정).hwp", "effective": "2023-06-01"},
    },
]

INSTITUTIONS = [
    {"code": "NST", "name": "국가과학기술연구회", "short": "NST"},
    {"code": "KASI", "name": "한국천문연구원", "short": "천문연"},
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for spec in SPECS:
        reg = build(spec)
        (OUT / f"{reg['inst'].lower()}-{reg['slug']}.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1))
        index.append({k: reg[k] for k in ("id", "inst", "slug", "title", "classCode", "effective", "amendNo", "format")}
                     | {"articleCount": len([a for a in reg["articles"] if not a["deleted"]]), "changes": len(reg["diff"]),
                        "posted": reg["source"]["posted"]})
        print(f"{reg['id']}: chapters={len(reg['chapters'])} articles={len(reg['articles'])} "
              f"supplements={len(reg['supplements'])} effective={reg['effective']} diff={[(d['key'], d['kind']) for d in reg['diff']]}")
    (OUT.parent / "index.json").write_text(json.dumps({"institutions": INSTITUTIONS, "regulations": index}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

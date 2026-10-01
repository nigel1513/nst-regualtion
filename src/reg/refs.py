"""조문 본문의 참조 추출(규칙 기반)과 대상 해석 (spec 6.4)."""
import re
from dataclasses import dataclass

from reg.load.loader import norm_title
from reg.structure.model import Prov

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_NAME = re.compile(r"「\s*([^」]{2,80}?)\s*」")
RE_ART = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+)(?!\d))?(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*(\d+)\s*호)?"
                    r"(?:\s*([가-하])\s*목)?")
RE_PARA_ONLY = re.compile(r"(?<![조\d])\s?제\s*(\d+)\s*항|전\s*항|같은\s*조|이\s*조")
RE_ANNEX = re.compile(r"(별\s*표|별\s*지)\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?")
RE_DELEG = re.compile(r"(?:따로|별도로)\s*정한다|(?:으)?로\s*정하는\s*바에\s*따른다")
LAW_TAIL = re.compile(r"(법|법률|령|규칙|규정|예규|훈령|고시|지침|기준)$")


@dataclass
class RefCandidate:
    path: str
    start: int
    end: int
    evidence: str
    rel_type: str
    kind: str
    name: str | None
    target_path: str | None


def looks_like_law(name: str) -> bool:
    return bool(LAW_TAIL.search(norm_title(name)))


def _art_path(m) -> str:
    p = f"a{int(m[1])}" + (f"-{int(m[2])}" if m[2] else "")
    if m[3]:
        p += f".p{int(m[3])}"
    if m[4]:
        p += f".i{int(m[4])}"
    if m[5]:
        p += f".s{m[5]}"
    return p


def _rel(text: str, end: int, external: bool) -> str:
    after = text[end:end + 30]
    if re.match(r"\s*(?:의\s*규정)?\s*에도\s*불구하고", after):
        return "EXCEPTION"
    if "준용" in after.split("다.")[0]:
        return "MUTATIS"
    if external and re.match(r"\s*(?:의\s*규정)?\s*에\s*(?:따라|따른|의하여|의한|근거하여|근거한)", after):
        return "BASIS"
    return "CITATION"


def _article_of(path: str) -> str:
    return path.split(".")[0].split("/")[-1] if "/" not in path else path.split(".")[0]


def extract_refs(p: Prov) -> list[RefCandidate]:
    text, out, taken = p.text or "", [], []

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    for m in RE_NAME.finditer(text):
        end = m.end()
        art = RE_ART.match(text, end) or RE_ART.match(text, end + 1)
        if art and art.start() - end <= 1:
            end = art.end()
        out.append(RefCandidate(p.path, m.start(), end, text[m.start():end], _rel(text, end, True), "external",
                                m[1].strip(), _art_path(art) if art and art.start() - m.end() <= 1 else None))
        taken.append((m.start(), end))
    for m in RE_ART.finditer(text):
        if not free(m.start(), m.end()):
            continue
        out.append(RefCandidate(p.path, m.start(), m.end(), m[0], _rel(text, m.end(), False), "internal", None,
                                _art_path(m)))
        taken.append((m.start(), m.end()))
    art = _article_of(p.path)
    for m in RE_PARA_ONLY.finditer(text):
        s = m.start() + (1 if m[0][:1].isspace() else 0)
        if not free(s, m.end()):
            continue
        tok = m[0].strip()
        if m[1]:
            target = f"{art}.p{int(m[1])}"
        elif tok.startswith("전"):
            cur = re.search(r"\.p(\d+)", p.path)
            if not cur or int(cur[1]) < 2:
                continue
            target = f"{art}.p{int(cur[1]) - 1}"
        else:
            target = art
        out.append(RefCandidate(p.path, s, m.end(), tok, _rel(text, m.end(), False), "internal", None, target))
        taken.append((s, m.end()))
    for m in RE_ANNEX.finditer(text):
        if not free(m.start(), m.end()):
            continue
        kind = "annex" if "표" in m[1] else "form"
        target = f"{kind}{int(m[2])}" + (f"-{int(m[3])}" if m[3] else "")
        out.append(RefCandidate(p.path, m.start(), m.end(), m[0], "CITATION", "annex", None, target))
        taken.append((m.start(), m.end()))
    for m in RE_DELEG.finditer(text):
        out.append(RefCandidate(p.path, m.start(), m.end(), m[0], "DELEGATION", "delegation", None, None))
    return sorted(out, key=lambda r: r.start)


def resolve_and_store(conn, work_id: str) -> dict:
    conn.execute("DELETE FROM regulation.reference WHERE work_id = %s", (work_id,))
    work = conn.execute("SELECT * FROM regulation.work WHERE id = %s", (work_id,)).fetchone()
    titles = {}
    for w in conn.execute("SELECT id, title FROM regulation.work WHERE id LIKE 'kr/law/%%' OR institution_id = %s",
                          (work["institution_id"],)).fetchall():
        titles.setdefault(norm_title(w["title"]), []).append(w["id"])
    pvs = conn.execute(
        "SELECT DISTINCT pv.* FROM regulation.provision_version pv JOIN regulation.provision p ON p.id = pv.provision_id"
        " WHERE p.work_id = %s", (work_id,)).fetchall()
    paths = {pv["path"] for pv in pvs}
    st = {"refs": 0, "resolved": 0, "unresolved": 0, "seeds": 0}
    for pv in pvs:
        prov = Prov(pv["path"], pv["unit"], pv["number_label"], pv["heading"], pv["text"], pv["parent_path"])
        for r in extract_refs(prov):
            tw, tpath, kind, res = None, r.target_path, "NONE", "RESOLVED"
            if r.kind == "internal":
                tw, kind = work_id, "PROVISION"
                res = "RESOLVED" if tpath in paths or tpath.split(".")[0] in paths else "UNRESOLVED"
            elif r.kind == "annex":
                tw, kind = work_id, "ANNEX"
                res = "RESOLVED" if tpath in paths else "UNRESOLVED"
            elif r.kind == "external":
                hits = titles.get(norm_title(r.name), [])
                if len(hits) == 1:
                    tw, kind = hits[0], "PROVISION" if tpath else "WORK"
                elif len(hits) > 1:
                    kind, res = "EXTERNAL_UNRESOLVED", "AMBIGUOUS"
                else:
                    kind, res = "EXTERNAL_UNRESOLVED", "UNRESOLVED"
                    if looks_like_law(r.name):
                        cur = conn.execute("INSERT INTO regulation.law_seed (name, origin, first_seen_work_id)"
                                           " VALUES (%s, 'reference', %s) ON CONFLICT DO NOTHING", (r.name, work_id))
                        st["seeds"] += cur.rowcount
            conn.execute(
                "INSERT INTO regulation.reference (work_id, source_pv_id, evidence_text, span_start, span_end, rel_type,"
                " target_kind, target_work_id, target_path, target_name, resolution) VALUES"
                " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (work_id, pv["id"], r.evidence, r.start, r.end, r.rel_type, kind, tw, tpath, r.name, res))
            st["refs"] += 1
            st["resolved" if res == "RESOLVED" else "unresolved"] += 1
    return st

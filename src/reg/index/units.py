"""조·항·호·목 단위 색인 문서 (M7 spec §2.1).

문서 1개 = 조항 판본 1개(provision_version)를 그 판본(work_version)에서 본 것. 장·절은 breadcrumb 문맥으로만 쓴다.
긴 단위(본문 > MAX_CHARS)는 같은 머리말로 `#n` 창을 나눈다 (M6 창 분할 규칙).
벡터는 현행 판본의 조·항·별표(창)에만 넣는다. 임베딩 입력은 M6 청크와 같은 형식이라 ops.embedding_cache를 그대로 쓴다.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlencode

MAX_CHARS = 1200
VECTOR_UNITS = {"article", "paragraph", "annex"}
VECTOR_STATES = {"CURRENT"}
CONTEXT_ONLY = {"chapter", "section"}
SUB = {"paragraph", "item", "subitem"}
RE_ART = re.compile(r"a(\d+)(?:-(\d+))?(?:~\d+)?")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


@dataclass
class UnitDoc:
    doc: dict
    embed_text: str | None


def article_path(path: str) -> str:
    """소속 조(최상위 단위)의 경로: a27.p1.i3 → a27, supp@…/a2.p1 → supp@…/a2, supp#3/a2 → supp#3/a2.
    창 접미사(#n)가 붙지 않은 조항 경로(base_path)를 받는다: 'supp#3'처럼 경로 자체에 #이 있을 수 있다."""
    return path.split(".", 1)[0]


def numbers(path: str) -> dict:
    """번호 직접 조회용 정수 필드. 부칙 안의 조문은 본칙 번호 조회에 섞이지 않도록 비운다."""
    p = path.split("#")[0]
    if m := re.fullmatch(r"(?:annex|form)(\d+)(?:-(\d+))?(?:~\d+)?", p):
        return {"annex_no": int(m[1]), "annex_branch": int(m[2] or 0)}
    if p.startswith("supp"):
        return {}
    head, *rest = p.split(".")
    if not (m := RE_ART.fullmatch(head)):
        return {}
    out = {"article_no": int(m[1]), "article_branch": int(m[2] or 0)}
    for seg in rest:
        if m := re.fullmatch(r"p(\d+)(?:~\d+)?", seg):
            out["paragraph_no"] = int(m[1])
        elif m := re.fullmatch(r"i(\d+)(?:-(\d+))?(?:~\d+)?", seg):
            out |= {"item_no": int(m[1]), "item_branch": int(m[2] or 0)}
        elif m := re.fullmatch(r"s([가-힣])(?:~\d+)?", seg):
            out["subitem"] = m[1]
    return out


def _supp_date(path: str) -> str:
    d = path.split("@")[1][:10] if "@" in path else ""
    try:
        return ". ".join(str(int(x)) for x in d.split("-")) + "." if d else ""
    except ValueError:
        return ""


def _head(p: dict) -> str:
    """M6 청크 머리말과 같다 (임베딩 캐시 재사용)."""
    if p["unit"] == "supplement":
        d = _supp_date(p["path"])
        return "부칙" + (" " + d if d else "")
    return p["label"] + (f"({p['heading']})" if p.get("heading") else "")


def _line(p: dict) -> str:
    if p["unit"] in SUB:
        return f"{p['label']} {p['text']}".strip()
    if p["unit"] == "supp_article":
        return f"{_head(p)} {p['text']}".strip()
    return p["text"]


def _formal(p: dict, nums: dict) -> str:
    """정식 라벨: 제27조 / 제1항 / 제3호 / 가목 / 별표 제1호 / 부칙(2024. 1. 17.)."""
    u = p["unit"]
    if u == "paragraph" and "paragraph_no" in nums:
        return f"제{nums['paragraph_no']}항"
    if u == "paragraph":
        m = re.search(r"\.p(\d+)", p["path"])
        return f"제{int(m[1])}항" if m else p["label"]
    if u == "item":
        m = re.search(r"\.i(\d+)(?:-(\d+))?", p["path"])
        return (f"제{int(m[1])}호" + (f"의{int(m[2])}" if m[2] else "")) if m else p["label"]
    if u == "subitem":
        m = re.search(r"\.s([가-힣])", p["path"])
        return f"{m[1]}목" if m else p["label"]
    if u == "supplement":
        d = _supp_date(p["path"])
        return f"부칙({d})" if d else "부칙"
    return p["label"]


def _family(work_id: str) -> str:
    return "law" if work_id.startswith("kr/law/") else "admrul" if work_id.startswith("kr/admrul/") else "reg"


def unit_docs(v: dict, provisions: list[dict]) -> list[UnitDoc]:
    """v: 판본 행(id, work_id, title, institution*, kind, state, effective_from/to — 폐지 반영 후).
    provisions: 그 판본의 조항(id, path, unit, label, heading, text, parent) 문서 순서."""
    by_path = {p["path"]: p for p in provisions}
    kids: dict[str, list[dict]] = {}
    for p in provisions:
        kids.setdefault(p.get("parent") or "", []).append(p)

    def subtree(path: str) -> list[dict]:
        return [x for k in kids.get(path, []) for x in (k, *subtree(k["path"]))]

    def ancestors(p: dict) -> list[dict]:
        out, cur = [], by_path.get(p.get("parent") or "")
        while cur is not None:
            out.append(cur)
            cur = by_path.get(cur.get("parent") or "")
        return out[::-1]

    title = v["title"]
    vector_ok = v["state"] in VECTOR_STATES
    base = {"release_id": v.get("release_id"), "work_id": v["work_id"], "version_id": v["id"], "title": title,
            "title_suggest": title, "institution": v.get("institution"), "institution_name": v.get("institution_name"),
            "institution_aliases": list(v.get("institution_aliases") or []), "family": _family(v["work_id"]),
            "work_kind": v.get("kind"), "version_state": v["state"], "embedding_model": v.get("embedding_model"),
            "effective_from": _iso(v.get("effective_from")), "effective_to": _iso(v.get("effective_to"))}
    out: list[UnitDoc] = []
    for ord_, p in enumerate(provisions):
        if p["unit"] in CONTEXT_ONLY:
            continue
        nums = numbers(p["path"])
        anc = ancestors(p)
        ap = article_path(p["path"])
        line = anc + [p]
        at = next((i for i, a in enumerate(line) if a["path"] == ap), len(line) - 1)
        chain = line[at:]
        top = chain[0]
        unit = "form" if p["unit"] == "annex" and p["path"].startswith("form") else p["unit"]
        formal = _formal(p, nums)
        formal_chain = [_formal(a, numbers(a["path"])) for a in chain]
        if top["unit"] == "supp_article":       # 부칙 조문: 부칙(날짜) 제1조 …
            sup = next((a for a in line[:at] if a["unit"] == "supplement"), None)
            if sup is not None:
                formal_chain = [_formal(sup, {})] + formal_chain
        crumbs = [x for x in (v.get("institution_name"), title) if x]
        for a in anc:
            if a["unit"] in CONTEXT_ONLY:
                crumbs.append(f"{a['label']} {a['heading']}".strip() if a.get("heading") else a["label"])
            elif a["unit"] in ("article", "annex", "supp_article"):
                crumbs.append(_head(a))
            else:
                crumbs.append(_formal(a, numbers(a["path"])))
        crumbs.append(_head(p) if p["unit"] in ("article", "annex", "supp_article", "supplement") else formal)
        top_head = _head(top)
        heading = top.get("heading") if top["unit"] in ("article", "annex", "supp_article") else None
        parents = [a for a in chain[1:-1]]                         # 조와 자기 사이 (항, 호)
        context = " ".join([top_head] + [_line(x) for x in ([top] if top["text"] and top is not p else [])]
                           + [_line(x) for x in parents]) if p is not top else ""
        doc = {**base, **nums, "pv_id": p.get("id"), "path": p["path"], "base_path": p["path"], "parent_path": p.get("parent"),
               "article_path": top["path"], "article_key": f"{v['id']}|{top['path']}", "unit": unit, "ord": ord_,
               "label": formal, "marker": p["label"], "full_label": " ".join([title] + formal_chain),
               "heading": heading, "breadcrumb": " > ".join(crumbs), "text": p["text"] or "", "context": context,
               "window": 0}
        if unit in ("annex", "form"):
            doc["annex_image"] = "/api/v1/annex?" + urlencode({"version": v["id"], "path": p["path"]})
        is_top = p is top
        body_lines = [p["text"]] + [_line(s) for s in subtree(p["path"])] if is_top else []
        article_text = None
        if is_top:
            body = "\n".join(b for b in body_lines if b)
            article_text = f"{top_head}\n{body}" if body else top_head
        # 임베딩 입력: 조·별표 = 조 전체(M6 청크 형식), 항 = 조 머리 + 항 + 그 아래 호·목
        embed = None
        if vector_ok and p["unit"] in VECTOR_UNITS and unit != "form":
            if is_top:
                embed = article_text
            else:
                lines = [_line(p)] + [_line(s) for s in subtree(p["path"])]
                embed = top_head + "\n" + "\n".join(x for x in lines if x)
        text = doc["text"]
        head = top_head if is_top else _head(top)
        if len(head) + 1 + len(text) <= MAX_CHARS:
            if article_text is not None:
                doc["article_text"] = article_text
            out.append(UnitDoc(doc, embed))
            continue
        size = MAX_CHARS - len(head) - 1                         # 긴 단위: 같은 머리말로 창을 나눈다
        for n, i in enumerate(range(0, len(text), size), 1):
            piece = text[i:i + size]
            w = {**doc, "doc_id": f"{v['id']}|{p['path']}#{n}", "path": f"{p['path']}#{n}", "text": piece, "window": n}
            if n == 1 and article_text is not None:
                w["article_text"] = article_text
            out.append(UnitDoc(w, f"{head}\n{piece}" if embed is not None else None))
    for d in out:
        d.doc.setdefault("doc_id", f"{v['id']}|{d.doc['path']}")
    return out


def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else d

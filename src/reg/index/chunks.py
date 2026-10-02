"""검색 청크 생성 (spec 5.4): 조 단위, 길면 항 단위, 조 머리·장 제목을 문맥으로."""
from dataclasses import dataclass

MAX_CHARS = 1200
TOP = {"article", "supplement", "annex"}


@dataclass
class Chunk:
    chunk_id: str
    version_id: str
    work_id: str
    path: str
    path_label: str
    text: str
    context_text: str


def _head(p: dict) -> str:
    if p["unit"] == "supplement":
        d = p["path"].split("@")[1][:10] if "@" in p["path"] else ""
        return "부칙" + (" " + ". ".join(str(int(x)) for x in d.split("-")) + "." if d else "")
    return p["label"] + (f"({p['heading']})" if p.get("heading") else "")


def _line(p: dict) -> str:
    if p["unit"] in ("paragraph", "item", "subitem"):
        return f"{p['label']} {p['text']}".strip()
    if p["unit"] == "supp_article":
        return f"{_head(p)} {p['text']}".strip()
    return p["text"]


def chunk_version(version_id: str, work_id: str, title: str, provisions: list[dict]) -> list[Chunk]:
    kids: dict[str, list[dict]] = {}
    for p in provisions:
        kids.setdefault(p.get("parent") or "", []).append(p)

    def subtree(path: str) -> list[dict]:
        return [x for k in kids.get(path, []) for x in (k, *subtree(k["path"]))]

    chapter = None
    out: list[Chunk] = []

    def emit(path: str, label: str, head: str, body_lines: list[str]) -> None:
        ctx = " > ".join(x for x in (title, chapter, head) if x)
        text = "\n".join([head] + [b for b in body_lines if b])
        out.append(Chunk(f"{version_id}|{path}", version_id, work_id, path, label, text, ctx))

    for p in provisions:
        if p["unit"] == "chapter":
            chapter = _head(p) if not p.get("heading") else f"{p['label']} {p['heading']}"
            continue
        if p["unit"] not in TOP:
            continue
        head = _head(p)
        sub = subtree(p["path"])
        lines = [p["text"]] + [_line(s) for s in sub]
        full = "\n".join([head] + [x for x in lines if x])
        if len(full) <= MAX_CHARS:
            emit(p["path"], head, head, lines)
            continue
        paras = [s for s in kids.get(p["path"], []) if s["unit"] == "paragraph"]
        if paras:
            for i, para in enumerate(paras):  # 조 본문(항 앞 문장)은 첫 항 청크에 붙인다
                body = ([p["text"]] if i == 0 else []) + [_line(para)] + [_line(s) for s in subtree(para["path"])]
                emit(para["path"], f"{head} {para['label']}", head, body)
            continue
        body = "\n".join(x for x in lines if x)
        size = MAX_CHARS - len(head) - 1
        for n, i in enumerate(range(0, len(body), size), 1):
            emit(f"{p['path']}#{n}", head, head, [body[i:i + size]])
    return out

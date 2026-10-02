# src/reg/core/quality_report.py
"""추출·파싱·참조 품질 지표 (M6-6). 모든 추출 변경은 이 지표를 낮추거나 같게 유지해야 한다.

두 가지 입력
- report(conn): DB에 적재된 판본(work_version.parsed)과 참조·검수 작업을 읽는다. 쓰지 않는다.
- offline(conn, blob): 보관소 원본을 지금 코드로 다시 추출·파싱한다(DB에 쓰지 않음). 재처리 전후 비교용.
"""
import gzip
import json
import re
from collections import Counter
from itertools import pairwise

from reg.core.model import ParsedDoc
from reg.core.text import lexicon

BODY = {"article", "paragraph", "item", "subitem", "supp_article", "chapter", "section"}
TEXT_DEFECTS = {
    "spaced": re.compile(r"(?<![가-힣])(?:[가-힣] ){4,}[가-힣](?![가-힣])"),
    "page_number": re.compile(r"(?:^|\s)[-–]\s?\d{1,3}\s?[-–](?=\s|$)"),
    "pua": re.compile(r"[\U0000e000-\U0000f8ff\U0000fffd\U000f0000-\U0010ffff]"),
    "jamo": re.compile(r"(?<![ㄱ-ㅣ])[ㄱ-ㅆㅈ-ㅎㅏ-ㅣ](?![ㄱ-ㅣ])"),  # 'ㅇ'은 글머리표로 흔히 써서 뺀다
    "ctrl": re.compile(r"[\x00-\x08\x0b-\x1f\x7f]"),
}
BODY_DEFECTS = {
    "missed_article": re.compile(r"(?:다\.|>|\])\s*제\s?\d+\s?조(?:의\s?\d+)?\s?\([^)]{1,20}\)"),
    "missed_paragraph": re.compile(r"다\.\s*[②-⑳]"),
}
ORDER = ["versions", "provisions", "chars", "articles_zero", "article_rate_lt95", "article_rate_mean",
         "body:spaced", "body:page_number", "body:pua", "body:jamo", "body:ctrl", "body:missed_article",
         "body:missed_paragraph", "body:glued", "body:split", "body:dup_chunk", "annex:spaced", "annex:page_number",
         "annex:pua", "annex:jamo", "annexes", "annexes_anchored", "issue:PARSE:gap", "issue:PARSE:toc",
         "issue:LOW_TEXT:"]
HIGHER_IS_BETTER = {"versions", "provisions", "chars", "annexes", "annexes_anchored", "article_rate_mean"}
# 앞 조각이 조사·어미로 끝나야 '붙은 두 어절'로 센다 (복합명사 '내자구매요령'은 세지 않는다)
_ENDING = re.compile(r"(?:하여|하고|하며|으로|에서|에게|하는|되는|부터|까지|[다고며를을는은의에와과])$")


def _word(t: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", t)


def glued_words(text: str, lex: dict[str, int]) -> int:
    """'관하여필요한'처럼 두 어절이 붙은 것: 사전에 없는 4글자 이상 한글 어절이 (어미로 끝나는 어절 + 어절)로 나뉜다."""
    n = 0
    for t in text.split():
        w = _word(t)
        if len(w) < 4 or lex.get(w, 0) or not re.fullmatch(r"[가-힣]+", w):
            continue
        if any(lex.get(w[:k], 0) >= 5 and lex.get(w[k:], 0) >= 5 and _ENDING.search(w[:k])
               for k in range(2, len(w) - 1)):
            n += 1
    return n


def split_words(text: str, lex: dict[str, int]) -> int:
    """'개인정 보보호법'처럼 한 어절이 갈라진 것: 붙이면 흔한 어절인데 앞 조각은 사전에 거의 없다."""
    ws = [_word(t) for t in text.split()]
    return sum(1 for a, b in pairwise(ws) if a and b and lex.get(a + b, 0) >= 30 and lex.get(a, 0) <= 1)


def dup_chunk(text: str) -> int:
    seen: dict[str, int] = {}
    for i in range(0, max(0, len(text) - 40), 10):
        w = text[i:i + 40]
        if w in seen and i - seen[w] >= 40:
            return 1
        seen.setdefault(w, i)
    return 0


def doc_metrics(doc: ParsedDoc | dict) -> Counter:
    from reg.core.effective import Effective
    from reg.core.quality import check

    d = doc.to_json() if isinstance(doc, ParsedDoc) else doc
    lex = lexicon()
    c = Counter(versions=1)
    arts = []
    for p in d["provisions"]:
        t = p["text"] or ""
        c["provisions"] += 1
        c["chars"] += len(t)
        g = "annex" if p["unit"] == "annex" else "body" if p["unit"] in BODY else "supp"
        for k, rx in TEXT_DEFECTS.items():
            c[f"{g}:{k}"] += len(rx.findall(t))
        if g == "body":
            for k, rx in BODY_DEFECTS.items():
                c[f"body:{k}"] += len(rx.findall(t))
            c["body:glued"] += glued_words(t, lex)
            c["body:split"] += split_words(t, lex)
            c["body:dup_chunk"] += dup_chunk(t)
        if p["unit"] == "annex":
            c["annexes"] += 1
            c["annexes_anchored"] += bool(p.get("anchor"))
        if p["unit"] == "article" and (m := re.fullmatch(r"a(\d+)(?:-\d+)?(?:~\d+)?", p["path"])):
            arts.append(int(m[1]))
    rate = len(set(arts)) / max(arts) if arts else 0.0
    c["articles_zero"] += not arts
    c["article_rate_lt95"] += rate < 0.95
    c["article_rate_sum"] += rate
    for i in check(ParsedDoc.from_json(d), Effective(None, "none", "CONFIRMED", None)):
        c[f"issue:{i.kind}:{i.detail.get('check', '')}"] += 1
    return c


def _finish(total: Counter) -> dict:
    out = {k: total.get(k, 0) for k in ORDER}
    out["article_rate_mean"] = round(total["article_rate_sum"] / max(1, total["versions"]), 4)
    return out


def _where(scope: str) -> str:
    return "v.version_state = 'CURRENT'" if scope == "current" else "true"


def report(conn, scope: str = "current") -> dict:
    """인자 없는 질의라 LIKE의 %는 그대로 쓴다 (psycopg는 인자가 없으면 자리표시자를 해석하지 않는다)."""
    total, by_inst = Counter(), {}
    for r in conn.execute("SELECT v.parsed, coalesce(i.code, 'LAW') AS inst FROM regulation.work_version v"
                          " JOIN regulation.work w ON w.id = v.work_id"
                          " LEFT JOIN regulation.institution i ON i.id = w.institution_id"
                          f" WHERE {_where(scope)} AND v.work_id LIKE 'kr/reg/%'"):
        m = doc_metrics(r["parsed"])
        total.update(m)
        by_inst.setdefault(r["inst"], Counter()).update(m)
    tasks = {f"{r['kind']}:{r['cause']}": r["n"] for r in conn.execute(
        "SELECT kind, coalesce(detail->>'check', detail->>'basis', CASE WHEN target LIKE 'source:%' THEN 'source'"
        " ELSE 'version' END) AS cause, count(*) AS n FROM regulation.review_task WHERE status = 'OPEN'"
        " AND kind IN ('PARSE','LOW_TEXT','EFFECTIVE_DATE','CONFLICT','REFERENCE') GROUP BY 1, 2")}
    refs = {f"{r['rel_type']}:{r['t']}": r["n"] for r in conn.execute(
        "SELECT r.rel_type, CASE WHEN r.target_work_id = r.work_id THEN 'self' WHEN r.target_work_id LIKE 'kr/law/%'"
        " THEN 'law' WHEN r.target_work_id IS NOT NULL THEN 'other' WHEN r.target_kind = 'NONE' THEN 'none'"
        " ELSE 'unresolved' END AS t, count(DISTINCT r.id) AS n FROM regulation.reference r"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = r.source_pv_id"
        f" JOIN regulation.work_version v ON v.id = vp.work_version_id AND {_where(scope)}"
        " WHERE r.work_id LIKE 'kr/reg/%' GROUP BY 1, 2")}
    return {"scope": scope, "mode": "db", "text": _finish(total),
            "by_institution": {k: _finish(v) for k, v in by_inst.items()}, "review_tasks": tasks, "references": refs}


def reparse(blob, sd: dict) -> ParsedDoc:
    """원본 하나를 지금 코드로 다시 추출·파싱하고 보기용 PDF로 위치를 찾는다 (DB에 쓰지 않음)."""
    from reg.core.anchor import locate
    from reg.core.extract import extract
    from reg.core.extract.pdf import extract_pdf
    from reg.core.parse import parse_blocks

    doc = parse_blocks(extract(blob.get(sd.get("ocr_blob_key") or sd["blob_key"]), sd["mime"], "x"))
    if sd["mime"] != "application/pdf" and sd.get("view_blob_key"):
        locate(doc, extract_pdf(blob.get(sd["view_blob_key"])))
    return doc


def offline(conn, blob, scope: str = "current", limit: int | None = None) -> dict:
    """원본을 지금 코드로 다시 파싱해서 잰다. 단일 프로세스다(실서버 부하 원칙: nice -n 19로 돌린다)."""
    rows = conn.execute(  # 인자를 넘기므로 LIKE의 %는 %%로 쓴다 (psycopg 자리표시자)
        "SELECT v.id, coalesce(i.code, 'LAW') AS inst, sd.* FROM regulation.work_version v"
        " JOIN regulation.work w ON w.id = v.work_id LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " JOIN regulation.source_document sd ON sd.id = v.source_document_id"
        f" WHERE {_where(scope)} AND v.work_id LIKE 'kr/reg/%%' AND sd.mime <> 'application/xml' ORDER BY v.id"
        " LIMIT %s", (limit or 1_000_000,)).fetchall()
    total, by_inst, failed = Counter(), {}, []
    for r in rows:
        try:
            m = doc_metrics(reparse(blob, r))
        except Exception as e:  # 한 파일 실패가 보고서를 멈추지 않게
            failed.append({"version": r["id"], "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        total.update(m)
        by_inst.setdefault(r["inst"], Counter()).update(m)
    return {"scope": scope, "mode": "offline", "text": _finish(total),
            "by_institution": {k: _finish(v) for k, v in by_inst.items()}, "failed": failed}


def compare(before: dict, after: dict) -> list[tuple[str, float, float]]:
    """나빠진 지표 목록. 결함 지표는 늘면, 인식률·별표 위치 비율은 줄면 나빠진 것이다. 비어 있어야 통과."""
    worse = []
    for k in ORDER:
        if k in HIGHER_IS_BETTER:
            continue
        b, a = before["text"].get(k, 0), after["text"].get(k, 0)
        if a > b:
            worse.append((k, b, a))
    if after["text"].get("article_rate_mean", 0) < before["text"].get("article_rate_mean", 0):
        worse.append(("article_rate_mean", before["text"]["article_rate_mean"], after["text"]["article_rate_mean"]))
    return worse


def to_markdown(before: dict | None, after: dict) -> str:
    rows = ["| 지표 | 전 | 후 |", "|---|---:|---:|"]
    for k in ORDER:
        rows.append(f"| {k} | {before['text'].get(k, '') if before else ''} | {after['text'].get(k, '')} |")
    return "\n".join(rows) + "\n"


def dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)


def build_lexicon(conn, min_count: int = 3) -> bytes:
    """HWP 원문(띄어쓰기가 정확함) 본문 어절 빈도 → lexicon.tsv.gz 바이트. 같은 입력이면 같은 바이트."""
    lex = Counter()
    for r in conn.execute("SELECT v.parsed FROM regulation.work_version v JOIN regulation.source_document sd"
                          " ON sd.id = v.source_document_id WHERE sd.mime IN ('application/x-hwp', 'application/hwp+zip')"):
        for p in r["parsed"]["provisions"]:
            if p["unit"] != "annex":
                lex.update(w for w in (_word(t) for t in (p["text"] or "").split()) if re.search(r"[가-힣]", w))
    items = sorted((w, n) for w, n in lex.items() if n >= min_count)
    return gzip.compress("".join(f"{w}\t{n}\n" for w, n in items).encode("utf-8"), mtime=0)


def refs_sample(conn, n: int = 100, seed: float = 0.42) -> list[dict]:
    """현행 판본 참조 무작위 표본 (사람이 정밀도를 판정할 목록). 같은 seed면 같은 표본."""
    conn.execute("SELECT setseed(%s)", (seed,))
    return conn.execute(
        "SELECT r.id, r.work_id, pv.path, r.rel_type, r.target_kind, r.target_work_id, r.target_path, r.target_name,"
        " r.resolution, r.extractor, r.evidence_text, substr(pv.text, greatest(1, r.span_start - 34),"
        " r.span_end - greatest(1, r.span_start - 34) + 13) AS context FROM regulation.reference r"
        " JOIN regulation.provision_version pv ON pv.id = r.source_pv_id"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = pv.id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.version_state = 'CURRENT'"
        " WHERE r.work_id LIKE 'kr/reg/%%' ORDER BY random() LIMIT %s", (n,)).fetchall()

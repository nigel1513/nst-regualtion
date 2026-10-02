"""질의응답 평가 (spec 12): 상태·인용·결론·되묻기·지연."""
import time

from reg.qa.service import ask


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def run_eval(conn, deps: dict, cases: list[dict]) -> dict:
    rows, lat = [], []
    for c in cases:
        t0 = time.monotonic()
        r = ask(conn, deps, c["question"], user_institution=c.get("user_institution"))
        lat.append((time.monotonic() - t0) * 1000)
        e = c["expect"]
        want = e["status"] if isinstance(e["status"], list) else [e["status"]]
        status_ok = r["status"] in want
        cite_ok = retr_ok = None
        if "article" in e:
            evs = [{**x, "id": x.get("id") or f"E{i + 1}"} for i, x in enumerate(r.get("evidence") or [])]

            def hit(x):
                return x["path"].split(".")[0] == e["article"] and e.get("work_contains", "") in x["work_id"]

            retr_ok = any(hit(x) for x in evs[:2])  # 검색: 상위 근거 2개 안에 정답 조문
            if r.get("answer"):  # 인용 정확도 (spec 12): 답변이 실제로 인용한 근거가 정답 조문인가
                cited = {c["id"] for c in r["answer"].get("근거") or []}
                cite_ok = any(hit(x) for x in evs if x["id"] in cited)
            elif "verdict" not in e:
                cite_ok = retr_ok
            else:
                cite_ok = False
        ver = r.get("verification") or {}
        numbers_ok = ver.get("numbers_match") if r.get("answer") else None
        consistent_ok = ver.get("consistent") if r.get("answer") else None
        verdict_ok = None if "verdict" not in e or r["status"] == "not_found" else \
            bool(r.get("answer")) and r["answer"]["결론"] == e["verdict"]
        rows.append({"id": c["id"], "status": r["status"], "status_ok": status_ok, "citation_ok": cite_ok,
                     "retrieval_ok": retr_ok, "verdict_ok": verdict_ok, "numbers_ok": numbers_ok,
                     "consistent_ok": consistent_ok, "qa_id": r.get("id")})

    def rate(key, pred=lambda x: True):
        xs = [x[key] for x in rows if x[key] is not None and pred(x)]
        return round(sum(xs) / len(xs), 3) if xs else None

    ni = [x for x, c in zip(rows, cases) if c["expect"]["status"] == "need_institution"]  # 되묻기 문항만
    return {"n": len(rows), "status_acc": rate("status_ok"), "citation_hit": rate("citation_ok"),
            "retrieval_hit": rate("retrieval_ok"), "verdict_acc": rate("verdict_ok"),
            "numbers_rate": rate("numbers_ok"), "consistency_rate": rate("consistent_ok"),
            "need_institution_acc": round(sum(x["status_ok"] for x in ni) / len(ni), 3) if ni else None,
            "p95_latency_ms": round(_p95(lat)), "cases": rows}

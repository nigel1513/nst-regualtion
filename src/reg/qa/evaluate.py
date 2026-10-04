"""질의응답 평가 (spec 12): 상태·인용·결론·되묻기·지연."""
import time

from reg.qa.service import ask


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def run_eval(conn, deps: dict, cases: list[dict], log: bool = True) -> dict:
    """log=False: 질의 기록(ops.qa_log)을 남기지 않는다 (읽기 전용 평가)."""
    rows, lat = [], []
    for c in cases:
        t0 = time.monotonic()
        r = ask(conn, deps, c["question"], user_institution=c.get("user_institution"), log=log)
        lat.append((time.monotonic() - t0) * 1000)
        e = c["expect"]
        want = e["status"] if isinstance(e["status"], list) else [e["status"]]
        status_ok = r["status"] in want
        cite_ok = retr_ok = None
        if "article" in e:
            evs = [{**x, "id": x.get("id") or f"E{i + 1}"} for i, x in enumerate(r.get("evidence") or [])]

            # alt: 같은 문장이 다른 규정에도 그대로 있으면 그 조도 정답 (예: NST 복무규정 제26조 = 취업규칙 제33조)
            want_arts = [(e["article"], e.get("work_contains", ""))] + [(x["article"], x.get("work_contains", ""))
                                                                        for x in e.get("alt") or []]

            def hit(x):
                return any(x["path"].split(".")[0] == art and w in x["work_id"] for art, w in want_arts)

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
        # verdict: null = 일반 답변 문항 (결론 없이 답해야 한다). 판정 문항과 따로 센다
        general = "verdict" in e and e["verdict"] is None
        verdict_ok = None if "verdict" not in e or general or r["status"] == "not_found" else \
            bool(r.get("answer")) and r["answer"]["결론"] == e["verdict"]
        general_ok = None if not general or r["status"] == "not_found" else \
            bool(r.get("answer")) and r["answer"].get("결론") is None
        top = (r.get("retrieved") or [{}])[0]
        rows.append({"id": c["id"], "status": r["status"], "status_ok": status_ok, "citation_ok": cite_ok,
                     "retrieval_ok": retr_ok, "verdict_ok": verdict_ok, "general_ok": general_ok, "numbers_ok": numbers_ok,
                     "consistent_ok": consistent_ok, "qa_id": r.get("id"),
                     "verdict": (r.get("answer") or {}).get("결론"),
                     "top": f"{top['version_id']} {top['path']}" if top else ""})

    def rate(key, pred=lambda x: True):
        xs = [x[key] for x in rows if x[key] is not None and pred(x)]
        return round(sum(xs) / len(xs), 3) if xs else None

    ni = [x for x, c in zip(rows, cases) if c["expect"]["status"] == "need_institution"]  # 되묻기 문항만
    return {"n": len(rows), "status_acc": rate("status_ok"), "citation_hit": rate("citation_ok"),
            "retrieval_hit": rate("retrieval_ok"), "verdict_acc": rate("verdict_ok"),
            "general_acc": rate("general_ok"),
            "numbers_rate": rate("numbers_ok"), "consistency_rate": rate("consistent_ok"),
            "need_institution_acc": round(sum(x["status_ok"] for x in ni) / len(ni), 3) if ni else None,
            "p95_latency_ms": round(_p95(lat)), "cases": rows}

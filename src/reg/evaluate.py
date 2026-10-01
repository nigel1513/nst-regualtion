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
        cite_ok = None
        if "article" in e:
            evs = r.get("evidence") or []
            cite_ok = any(x["path"].split(".")[0] == e["article"] and e.get("work_contains", "") in x["work_id"]
                          for x in evs[:2])
        verdict_ok = None if "verdict" not in e or r["status"] == "not_found" else \
            bool(r.get("answer")) and r["answer"]["결론"] == e["verdict"]
        rows.append({"id": c["id"], "status": r["status"], "status_ok": status_ok, "citation_ok": cite_ok,
                     "verdict_ok": verdict_ok, "qa_id": r.get("id")})

    def rate(key, pred=lambda x: True):
        xs = [x[key] for x in rows if x[key] is not None and pred(x)]
        return round(sum(xs) / len(xs), 3) if xs else None

    ni = [x for x, c in zip(rows, cases) if c["expect"]["status"] == "need_institution"]  # 되묻기 문항만
    return {"n": len(rows), "status_acc": rate("status_ok"), "citation_hit": rate("citation_ok"),
            "verdict_acc": rate("verdict_ok"),
            "need_institution_acc": round(sum(x["status_ok"] for x in ni) / len(ni), 3) if ni else None,
            "p95_latency_ms": round(_p95(lat)), "cases": rows}

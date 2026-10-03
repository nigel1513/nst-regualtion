"""참조 팝업용 조문 조회 (사용자 요청 2026-10-03).

본문의 참조를 누르면 페이지를 옮기지 않고 팝업으로 보여준다: 참조된 조 전체(문맥)와 실제로 가리키는 항·호(target)를 함께 돌려준다."""
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
UNITS_SHOWN = ("article", "paragraph", "item", "subitem", "supplement", "supp_article", "annex")


def _version(c, work_id: str, as_of: date | None) -> dict | None:
    if as_of is None:
        q, a = "SELECT id, effective_from FROM regulation.work_version WHERE work_id = %s AND version_state = 'CURRENT'", (work_id,)
    else:
        q = ("SELECT id, effective_from FROM regulation.work_version WHERE work_id = %s AND effective_from <= %s"
             " ORDER BY effective_from DESC, id DESC LIMIT 1")
        a = (work_id, as_of)
    return c.execute(q, a).fetchone()


@router.get("/api/v1/provision")
def provision(request: Request, work: str, path: str = Query(..., min_length=1, max_length=120),
              as_of: date | None = None):
    article = path.split(".")[0]
    with request.app.state.pool.connection() as c:
        w = c.execute("SELECT w.id, w.title, i.code, i.name FROM regulation.work w"
                      " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE w.id = %s", (work,)).fetchone()
        if not w:
            raise HTTPException(404, "규범문서를 찾을 수 없습니다")
        v = _version(c, work, as_of)
        if not v:
            raise HTTPException(404, "해당 시점의 버전이 없습니다")
        rows = c.execute(
            "SELECT pv.path, pv.unit, pv.number_label, pv.heading, pv.text FROM regulation.version_provision vp"
            " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
            " WHERE vp.work_version_id = %s AND (pv.path = %s OR pv.path LIKE %s) ORDER BY vp.ord",
            (v["id"], article, article + ".%")).fetchall()
    rows = [r for r in rows if r["unit"] in UNITS_SHOWN]
    if not rows:
        raise HTTPException(404, "조문을 찾을 수 없습니다")
    head = rows[0]
    hit = path if any(r["path"] == path for r in rows) else article  # 항이 없어졌으면 조 전체를 표시
    lines = [{"path": r["path"], "label": r["number_label"], "text": r["text"],
              "target": r["path"] == hit or r["path"].startswith(hit + ".")} for r in rows]
    href = "/regulations/" + "/".join(quote(s, safe="") for s in work.split("/")) + f"?a={article}#{path}"
    return {"work_id": w["id"], "title": w["title"], "institution": w["code"], "institution_name": w["name"],
            "version_id": v["id"], "effective_from": v["effective_from"].isoformat() if v["effective_from"] else None,
            "article": {"path": head["path"], "label": head["number_label"], "heading": head["heading"]},
            "lines": lines, "href": href}

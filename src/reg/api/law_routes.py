"""법령 미러 API (/api/v1/law/…). 엔드포인트는 이 파일에 두고 app.py는 include_router만 한다 (overview §3)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import Response

from reg.sources.lawgo import api as L

router = APIRouter(prefix="/api/v1/law", tags=["law"])
Digits = Annotated[str, Path(pattern=r"^\d{1,20}$")]
ANNEX_CSP = ("sandbox; default-src 'none'; style-src 'unsafe-inline' https://www.law.go.kr;"
             " img-src data: https://www.law.go.kr; frame-src https://www.law.go.kr")


def _conn(request: Request):
    with request.app.state.pool.connection() as c:
        yield c


def _found(d, msg: str):
    if d is None:
        raise HTTPException(404, msg)
    return d


@router.get("/citations")
def citations(version: str, c=Depends(_conn)):
    return L.citations(c, version)


@router.get("/article/{article_id}")
def article(article_id: int, c=Depends(_conn)):
    return _found(L.article_detail(c, article_id), "조문을 찾을 수 없습니다")


@router.get("/annex/{seq}")
def annex(seq: Digits, c=Depends(_conn)):
    return _found(L.annex(c, seq), "별표를 찾을 수 없습니다")


@router.get("/annex/{seq}/html")
def annex_html(seq: Digits, request: Request, c=Depends(_conn)):
    k = L.annex_keys(c, seq)
    if not k or not k["html_key"]:
        raise HTTPException(404, "별표 본문이 아직 저장되지 않았습니다. law.go.kr 링크를 이용하세요")
    return Response(L.sanitize_html(request.app.state.blob.get(k["html_key"])), media_type="text/html; charset=utf-8",
                    headers={"Content-Security-Policy": ANNEX_CSP, "X-Content-Type-Options": "nosniff",
                             "Referrer-Policy": "no-referrer", "Cache-Control": "private, max-age=3600"})


@router.get("/annex/{seq}/pdf")
def annex_pdf(seq: Digits, request: Request, c=Depends(_conn)):
    k = L.annex_keys(c, seq)
    if not k or not k["pdf_key"]:
        raise HTTPException(404, "별표 PDF가 저장되지 않았습니다. law.go.kr 링크를 이용하세요")
    return Response(request.app.state.blob.get(k["pdf_key"]), media_type="application/pdf",
                    headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff",
                             "Cache-Control": "private, max-age=3600"})


@router.get("/version/{mst}/xml")
def version_xml(mst: Digits, request: Request, c=Depends(_conn)):
    key = _found(L.version_blob_key(c, mst), "보관 원본이 없습니다")
    return Response(request.app.state.blob.get(key), media_type="application/xml",
                    headers={"Content-Disposition": f'inline; filename="{mst}.xml"'})


@router.get("/{law_id}")
def law(law_id: str, c=Depends(_conn)):
    return _found(L.law_summary(c, law_id), "법령을 찾을 수 없습니다")


@router.get("/{law_id}/articles")
def law_articles(law_id: str, c=Depends(_conn)):
    return _found(L.articles(c, law_id), "법령을 찾을 수 없습니다")


@router.get("/{law_id}/annexes")
def law_annexes(law_id: str, c=Depends(_conn)):
    return L.annexes(c, law_id)

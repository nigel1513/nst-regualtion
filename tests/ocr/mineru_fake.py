"""MinerU 4.0 V1 API 가짜 응답. **실서버에서 녹화한 것이 아니다.**

모양은 MinerU 저장소(2026-10-02 클론)의 계약을 따른다.
- mineru/parser/api_server.py 의 pydantic 모델: HealthResponse, UploadResponse, FileObjectModel, JobAsyncResponse,
  JobFileResult, OutputFiles, ErrorResponse
- docs/en/reference/output_files.md 의 MiddleJson 2.0 (schema "docvortex.middle")
- docs/next/middle-json/current-medium.md 의 블록 규칙: PDF 최상위 블록은 0~1 정규화 bbox 필수,
  표는 table 부모 + table_body(HTML) 자식, 문단은 InlineSpan 목록
실서버가 뜨면 tests/ocr/test_mineru_live.py (mineru_live)로 실제 모양을 확인한다.
"""
import hashlib
import json

import httpx

BASE = "http://mineru.test"
KEY = "test-key"
HEALTH = {"status": "ok", "version": "4.0.0",
          "features": {"webhook": False, "output_formats": ["markdown", "middle_json", "structured_content", "zip"],
                       "sources": ["file_id", "url", "inline"]}}
MIDDLE = {
    "schema": "docvortex.middle", "schema_version": "2.0", "is_full_document": True,
    "metadata": {"file_suffix": "pdf", "producer": {"name": "mineru", "version": "4.0.0"}},
    "extensions": {"mineru": {"tier": "standard", "parse_mode": "ocr"},
                   "docvortex_layout": {"version": 1, "pages": [{"page_idx": 0, "width_pt": 595, "height_pt": 842}]}},
    "pages": [{"page_idx": 0, "blocks": [
        {"type": "header", "index": 0, "bbox": [0.6, 0.02, 0.9, 0.04],
         "content": [{"type": "text", "content": "방사선재해보상기준 기 6"}]},
        {"type": "doc_title", "index": 1, "level": 1, "bbox": [0.3, 0.1, 0.7, 0.15],
         "content": [{"type": "text", "content": "방사선 재해보상기준"}]},
        {"type": "text", "index": 2, "bbox": [0.1, 0.2, 0.9, 0.3],
         "content": [{"type": "text", "content": "제1조(목적) 이 기준은 원자력법 제109조에 따라\n종사자의 보호에 기여함을 목적으로 한다."}]},
        {"type": "text", "index": 3, "bbox": [0.1, 0.3, 0.9, 0.35],
         "content": [{"type": "text", "content": "제2조(정의) 이 기준에서 "},
                     {"type": "text", "content": "종사자", "styles": ["bold"]},
                     {"type": "text", "content": "라 함은 상근 임직원을 말한다."}]},
        {"type": "table", "index": 4, "bbox": [0.1, 0.4, 0.9, 0.5],
         "content": [{"type": "table_body", "index": 4, "bbox": [0.1, 0.4, 0.9, 0.5],
                      "content": "<table><tr><th>구분</th><th>금액</th></tr><tr><td>사망</td><td>1,000<br>만원</td></tr></table>"}]},
        {"type": "page_number", "index": 5, "bbox": [0.45, 0.95, 0.55, 0.97],
         "content": [{"type": "text", "content": "- 3 -"}]},
    ]}],
}
MARKDOWN = "# 방사선 재해보상기준\n\n제1조(목적) 이 기준은 …\n"
OUTPUTS = {"middle_json": {"file_id": "file_mj", "bytes": 1}, "markdown": {"file_id": "file_md", "bytes": 1}}


def _file(fid: str, n: int, sha: str | None = None) -> dict:
    return {"id": fid, "object": "file", "bytes": n, "created_at": 0, "expires_at": None, "filename": "source.pdf",
            "purpose": "parse", "sha256sum": sha}


def upload_pending(n: int, sha: str, url: str = f"{BASE}/v1/uploads/upload_1/content") -> dict:
    return {"id": "upload_1", "object": "upload", "bytes": n, "created_at": 0, "expires_at": 3600,
            "filename": "source.pdf", "purpose": "parse", "mime_type": "application/pdf", "sha256sum": sha,
            "status": "pending", "upload_url": url, "upload_method": "PUT", "upload_headers": {}, "file": None}


def upload_completed(n: int, sha: str) -> dict:
    return {**upload_pending(n, sha), "status": "completed", "upload_url": None, "upload_method": None,
            "upload_headers": None, "file": _file("file_1", n, sha)}


def job(status: str, file_status: str | None = None, outputs: dict | None = None, error: dict | None = None) -> dict:
    f = {"file_id": "file_1", "name": "source.pdf", "page_range": "all", "status": file_status or status,
         "parse": {"model_used": None, "duration_ms": 1200, "parser_version": "4.0.0"} if outputs else None,
         "output_files": outputs, "error": error}
    return {"job_id": "job_1", "status": status, "created_at": "2026-10-02T00:00:00Z", "started_at": None,
            "finished_at": None, "tier": "standard", "output_formats": ["middle_json", "markdown"],
            "access_level": "registered", "progress": {"completed": 0, "failed": 0, "total": 1},
            "files": [f], "links": {"self": "/v1/parse/jobs/job_1", "cancel": "/v1/parse/jobs/job_1"}}


def mock_cycle(m, data: bytes, *, dedup: bool = False, final: str = "completed", middle: dict = MIDDLE) -> dict:
    """respx 라우터 m에 V1 전체 주기를 건다: 상태 → 업로드 → (PUT·complete) → 작업 → 폴링 2회 → 내려받기.

    테스트가 한 단계를 바꾸려면 돌려받은 Route의 return_value/side_effect를 바꾼다(같은 경로를 또 등록하지 않는다).
    """
    sha = hashlib.sha256(data).hexdigest()
    done = job(final, outputs=OUTPUTS if final == "completed" else None,
               error=None if final == "completed" else {"type": "engine_error", "code": "parse_failed",
                                                         "message": "가짜 실패"})
    return {
        "health": m.get(f"{BASE}/v1/health").respond(json=HEALTH),
        "create": m.post(f"{BASE}/v1/uploads").respond(
            json=upload_completed(len(data), sha) if dedup else upload_pending(len(data), sha)),
        "put": m.put(f"{BASE}/v1/uploads/upload_1/content").respond(200),
        "complete": m.post(f"{BASE}/v1/uploads/upload_1/complete").respond(json=upload_completed(len(data), sha)),
        "submit": m.post(f"{BASE}/v1/parse/jobs").respond(json=job("queued")),
        "poll": m.get(f"{BASE}/v1/parse/jobs/job_1").mock(
            side_effect=[httpx.Response(200, json=job("running")), httpx.Response(200, json=done)]),
        "mj": m.get(f"{BASE}/v1/files/file_mj/content").respond(content=json.dumps(middle, ensure_ascii=False).encode()),
        "md": m.get(f"{BASE}/v1/files/file_md/content").respond(content=MARKDOWN.encode()),
    }

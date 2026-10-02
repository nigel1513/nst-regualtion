# scripts/m66_cut_fixtures.py
"""M6-6 테스트 픽스처: 실데이터 PDF에서 필요한 쪽만 잘라 tests/core/fixtures/pdf에 둔다 (읽기 전용).

uv run python scripts/m66_cut_fixtures.py
"""
from pathlib import Path

import pypdfium2 as pdfium

from reg.platform.runs import open_conn
from reg.platform.storage.blob import blob_store

OUT = Path(__file__).resolve().parents[1] / "tests" / "core" / "fixtures" / "pdf"
# (판본 id, 0부터 쪽 번호들, 파일 이름) — 2026-10-02 실서버 기준
CUTS = [
    ("kr/reg/ETRI/연구관리요령@2023-02-01", [1, 2], "etri_twoup_research_mgmt_p2-3.pdf"),      # 가로 용지 두 쪽 모아찍기
    ("kr/reg/ETRI/보안업무요령@2022-03-29.4", [2], "etri_footer_security_p3.pdf"),            # 꼬리글 '- 3 - 보안업무요령'
    ("kr/reg/KASI/내자구매요령@2023-12-29", [47, 48], "kasi_form4_p48-49.pdf"),               # 별지 제4호·제5호 서식
    ("kr/reg/KIST/비유동자산관리요령@2016-11-29", [8], "kist_pua_quotes_p9.pdf"),              # U+F000 따옴표
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    blob = blob_store()
    with open_conn() as conn:
        for vid, pages, name in CUTS:
            sd = conn.execute("SELECT sd.blob_key FROM regulation.work_version v JOIN regulation.source_document sd"
                              " ON sd.id = v.source_document_id WHERE v.id = %s", (vid,)).fetchone()
            src = pdfium.PdfDocument(blob.get(sd["blob_key"]))
            new = pdfium.PdfDocument.new()
            new.import_pages(src, pages)
            new.save(OUT / name)
            print(name, (OUT / name).stat().st_size)


if __name__ == "__main__":
    main()

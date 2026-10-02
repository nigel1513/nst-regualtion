"""통합(R16): 행정규칙(kr/admrul/…)도 법령처럼 제목으로 인용을 해석한다."""
from datetime import date

from reg.core.ingest.loader import rebuild_work, upsert_work
from reg.core.model import Prov
from reg.core.refs import resolve_and_store
from reg.platform.storage.blob import LocalBlobStore
from tests.test_impact import T, _ver


def test_admin_rule_titles_resolve_like_laws(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/admrul/1", "고시", "국가연구개발사업 연구개발비 사용 기준", None, {})
    _ver(conn, blob, "kr/admrul/1", "국가연구개발사업 연구개발비 사용 기준",
         [Prov("a5", "article", "제5조", None, "본문")], date(2024, 1, 1), b"A1")
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI')"
                        " RETURNING id").fetchone()["id"]
    upsert_work(conn, "kr/reg/KASI/연구비", "INTERNAL_REG", "연구비관리규정", inst, {})
    _ver(conn, blob, "kr/reg/KASI/연구비", "연구비관리규정",
         [Prov("a1", "article", "제1조", None, "「국가연구개발사업 연구개발비 사용 기준」 제5조에 따른다.")],
         date(2024, 1, 1), b"R1")
    for w in ("kr/admrul/1", "kr/reg/KASI/연구비"):
        rebuild_work(conn, w, T)
    resolve_and_store(conn, "kr/reg/KASI/연구비")
    r = conn.execute("SELECT target_work_id, target_path FROM regulation.reference WHERE work_id = 'kr/reg/KASI/연구비'"
                     " AND target_work_id IS NOT NULL").fetchall()
    assert ("kr/admrul/1", "a5") in {(x["target_work_id"], x["target_path"]) for x in r}

import json
from datetime import date
from pathlib import Path

from reg.core.ingest.process import process_once
from reg.core.model import Prov
from reg.platform.archive import store
from reg.platform.sniff import FileKind
from reg.sources.lawgo.config import LawgoConfig
from reg.sources.lawgo.link import link_all
from reg.sources.lawgo.promote import promote_all
from tests.sources.lawgo.helpers import load_reg, mirror_admrul, mirror_law

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 2)
YEOBI = {1: ("목적", "이 영은 여비를 정한다."), 10: ("국내 여비", "국내 여비는 다음과 같다.", ["철도운임", "선박운임"])}


def test_cited_law_is_promoted_once_and_loaded_by_core(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", YEOBI, "1001")
    load_reg(lconn, blob, "kr/reg/KASI/여비규정", "여비규정",
             [Prov("a1", "article", "제1조", "목적", "「공무원 여비 규정」 제10조에 따른다.")])
    link_all(lconn)
    lconn.commit()
    st = promote_all(lconn, LawgoConfig())
    assert (st["targets"], st["emitted"]) == (1, 1)
    ev = lconn.execute("SELECT payload FROM ops.outbox WHERE topic = 'regulation.law_fetched'").fetchone()["payload"]
    assert ev["law_id"] == "009402" and ev["mst"] == "1001" and set(ev) == {"law_id", "mst", "source_document_id"}
    assert promote_all(lconn, LawgoConfig())["pending"] == 1  # 처리 전에는 다시 내지 않는다
    assert process_once(lconn, blob, today=TODAY)["ok"] == 1
    w = lconn.execute("SELECT kind, title FROM regulation.work WHERE id = 'kr/law/009402'").fetchone()
    assert (w["kind"], w["title"]) == ("대통령령", "공무원 여비 규정")
    st3 = promote_all(lconn, LawgoConfig())
    assert (st3["emitted"], st3["up_to_date"]) == (0, 1)
    assert lconn.execute("SELECT law_id FROM regulation.work WHERE id = 'kr/law/009402'").fetchone()["law_id"] == "009402"
    assert lconn.execute("SELECT law_mst FROM regulation.work_version WHERE work_id = 'kr/law/009402'"
                         ).fetchone()["law_mst"] == "1001"


def test_new_current_version_is_emitted_again(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", YEOBI, "1001")
    cfg = LawgoConfig(promote_laws=["공무원 여비 규정"])
    promote_all(lconn, cfg)
    process_once(lconn, blob, today=TODAY)
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", {**YEOBI, 2: ("정의", "새 조문")}, "1002", on="20261001")
    assert promote_all(lconn, cfg)["emitted"] == 1
    process_once(lconn, blob, today=TODAY)
    assert lconn.execute("SELECT count(*) AS n FROM regulation.work_version WHERE work_id = 'kr/law/009402'"
                         ).fetchone()["n"] == 2


def test_config_admrul_promoted_as_kr_admrul(lconn, blob):
    mirror_admrul(lconn, blob, (FX / "admrul_2100000285346.xml").read_bytes(), "2100000285346")
    st = promote_all(lconn, LawgoConfig(promote_admruls=["영장심의위원회 운영세칙"], promote_laws=["없는 법률"]))
    assert st["emitted"] == 1 and st["missing_config"] == ["없는 법률"]
    process_once(lconn, blob, today=TODAY)
    w = lconn.execute("SELECT kind, law_id FROM regulation.work WHERE id = 'kr/admrul/75610'").fetchone()
    assert w["kind"] == "훈령"
    v = lconn.execute("SELECT effective_from FROM regulation.work_version WHERE work_id = 'kr/admrul/75610'").fetchone()
    assert v["effective_from"] == date(2026, 10, 2)


def test_abolished_law_is_not_promoted(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", YEOBI, "1001")
    lconn.execute("UPDATE law.law_master SET status = '폐지'")
    assert promote_all(lconn, LawgoConfig(promote_laws=["공무원 여비 규정"]))["emitted"] == 0


def test_legacy_event_without_mirror_row_is_still_processed(lconn, blob):
    sd = store(lconn, blob, source="lawgo", url="u", content=(FX / "law_287535.xml").read_bytes(),
               kind=FileKind("application/xml", "xml"), meta={})
    lconn.execute("INSERT INTO ops.outbox (topic, payload) VALUES ('regulation.law_fetched', %s)",
                  (json.dumps({"law_id": "009402", "mst": "287535", "name": "공무원 여비 규정",
                               "source_document_id": sd.id}),))
    lconn.commit()
    assert process_once(lconn, blob, today=TODAY)["ok"] == 1
    assert lconn.execute("SELECT title FROM regulation.work WHERE id = 'kr/law/009402'").fetchone()["title"] == "공무원 여비 규정"

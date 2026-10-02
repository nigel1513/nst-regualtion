import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PILOTS = {
    "NST": ("C0909", "국가과학기술연구회"), "KASI": ("C0266", "한국천문연구원"),
    "KIST": ("C0159", "한국과학기술연구원"), "ETRI": ("C0251", "한국전자통신연구원"),
}


def test_alio_yaml_lists_nst_and_25_institutes():
    rows = yaml.safe_load((ROOT / "config/sources/alio.yaml").read_text(encoding="utf-8"))
    codes = [r["code"] for r in rows]
    assert len(rows) == 26 and len(set(codes)) == 26
    # 사용자 결정 2026-10-02: ALIO id가 있는 25곳 모두 수집 (NSR은 ALIO 미공시)
    assert sorted(r["code"] for r in rows if r.get("active", True)) == sorted(r["code"] for r in rows if r["alio_apba_id"])
    for code, (apba, name) in PILOTS.items():
        r = next(x for x in rows if x["code"] == code)
        assert (r["alio_apba_id"], r["alio_name"], r["name"]) == (apba, name, name)
    ids = [r["alio_apba_id"] for r in rows if r["alio_apba_id"]]
    assert len(ids) == len(set(ids)) == 25 and all(re.fullmatch(r"C\d{4}", x) for x in ids)
    assert {r["kind"] for r in rows} == {"NST", "GRI"}
    nsr = next(r for r in rows if r["code"] == "NSR")
    assert nsr["alio_apba_id"] is None and nsr["active"] is False


def test_alio_yaml_aliases():
    """overview §2.8: 약칭은 설정에 두고 regulation.institution.aliases로 간다 (qa·검색이 DB에서 읽는다)."""
    rows = {r["code"]: r for r in yaml.safe_load((ROOT / "config/sources/alio.yaml").read_text(encoding="utf-8"))}
    assert {"천문연", "천문연구원"} <= set(rows["KASI"]["aliases"]) and "키스트" in rows["KIST"]["aliases"]
    assert {"에트리", "전자통신연구원"} <= set(rows["ETRI"]["aliases"]) and {"연구회", "과기연구회"} <= set(rows["NST"]["aliases"])
    every = [(c, a) for c, r in rows.items() for a in r.get("aliases", [])]
    assert all(isinstance(a, str) and a and a != rows[c]["name"] for c, a in every)
    assert len({a for _, a in every}) == len(every)   # 한 약칭이 두 기관을 가리키지 않는다

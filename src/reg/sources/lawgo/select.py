"""행정규칙 선별 (D-9): 내부규정이 인용한 이름 + 설정 지정분을 카탈로그와 정규화 이름으로 맞춘다."""
from reg.core.ingest.loader import norm_title
from reg.sources.lawgo.config import LawgoConfig


def cited_names(conn) -> set[str]:
    rows = conn.execute("SELECT DISTINCT target_name AS n FROM regulation.reference WHERE target_name IS NOT NULL"
                        " UNION SELECT name FROM regulation.law_seed").fetchall()
    return {r["n"] for r in rows if r["n"]}


def selected_admruls(conn, cfg: LawgoConfig) -> dict[str, str]:
    """{행정규칙ID: 이름}. 카탈로그에서 현행인 것만."""
    names = cited_names(conn) | set(cfg.admrul_include) | set(cfg.promote_admruls)
    norms = sorted({norm_title(n) for n in names})
    rows = conn.execute("SELECT admrul_id, name FROM law.admrul_catalog WHERE status = '현행' AND name_norm = ANY(%s)",
                        (norms,)).fetchall()
    return {r["admrul_id"]: r["name"] for r in rows}

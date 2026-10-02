import psycopg
import pytest


def test_law_tables_and_version_table(lconn):
    names = {r["table_name"] for r in lconn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'law'").fetchall()}
    assert {"law_master", "law_version", "article", "annex", "admrul_catalog", "sync_run", "change_log",
            "alembic_version"} <= names
    assert lconn.execute("SELECT version_num FROM law.alembic_version").fetchone()["version_num"] == "law_0001"


def test_regulation_fk_columns(lconn):
    cols = {(r["table_name"], r["column_name"]) for r in lconn.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'regulation'"
        " AND column_name IN ('target_law_id', 'target_law_article_id', 'law_id', 'law_mst')").fetchall()}
    assert {("reference", "target_law_id"), ("reference", "target_law_article_id"), ("work", "law_id"),
            ("work_version", "law_mst")} <= cols
    fks = {r["conname"] for r in lconn.execute(
        "SELECT conname FROM pg_constraint WHERE contype = 'f' AND conname LIKE '%%law%%'").fetchall()}
    assert {"reference_target_law_fk", "reference_target_law_article_fk", "work_law_fk",
            "work_version_law_mst_fk"} <= fks


def test_review_task_kinds_extended_not_replaced(lconn):
    for k in ("REF_LAW_AMBIGUOUS", "REF_LAW_GONE", "PARSE", "LOW_TEXT", "REFERENCE"):
        lconn.execute("INSERT INTO regulation.review_task (kind, target) VALUES (%s, %s)", (k, f"t:{k}"))
    with pytest.raises(psycopg.errors.CheckViolation):
        lconn.execute("INSERT INTO regulation.review_task (kind, target) VALUES ('NOPE', 'x')")


def test_one_current_version_per_law(lconn):
    lconn.execute("INSERT INTO law.law_master (law_id, family, source_id, name, name_norm, url)"
                  " VALUES ('1', 'law', '1', '가법', '가법', 'u')")
    lconn.execute("INSERT INTO law.law_version (mst, law_id, is_current, xml_url, html_url) VALUES ('10', '1', true, 'x', 'h')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        lconn.execute("INSERT INTO law.law_version (mst, law_id, is_current, xml_url, html_url)"
                      " VALUES ('11', '1', true, 'x', 'h')")

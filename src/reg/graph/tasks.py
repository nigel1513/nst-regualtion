"""Airflow·CLI 진입점 (overview §2.6)."""
from reg.platform.runs import open_conn, task_run


def sync() -> dict:
    """PostgreSQL → Neo4j 증분: 지문이 바뀐 규범문서만 (그래프가 비었으면 전체 재투영), 그래프 잠금 안에서."""
    from reg.graph.sync import graph_lock, sync_changed
    from reg.platform.neo4j import neo4j_driver

    with open_conn() as conn, task_run("graph.sync", conn) as st, neo4j_driver() as drv, graph_lock(conn):
        st.update(sync_changed(conn, drv))
        return dict(st)

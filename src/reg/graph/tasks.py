"""Airflow·CLI 진입점 (overview §2.6)."""
from reg.platform.runs import open_conn, task_run


def sync() -> dict:
    """PostgreSQL 현행 → Neo4j 재투영 (그래프 잠금 안에서)."""
    from reg.graph.sync import graph_lock, sync_graph
    from reg.platform.neo4j import neo4j_driver

    with open_conn() as conn, task_run("graph.sync", conn) as st, neo4j_driver() as drv, graph_lock(conn):
        st.update(sync_graph(conn, drv))
        return dict(st)

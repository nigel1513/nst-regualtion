"""Neo4j 드라이버 (설정에서)."""


def neo4j_driver(s=None):
    from neo4j import GraphDatabase

    from reg.platform.settings import get_settings

    s = s or get_settings()
    return GraphDatabase.driver(s.neo4j_url, auth=(s.neo4j_user, s.neo4j_password))

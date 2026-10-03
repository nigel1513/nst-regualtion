import pytest


@pytest.fixture
def topic_table(migrated):
    """기관 비교 작업이 만들 regulation.work_topic 대역 (마이그레이터 권한으로 만들고 지운다)."""
    from reg.platform.db.conn import connect

    m = connect(migrated[1])
    m.execute("CREATE TABLE regulation.work_topic (work_id text NOT NULL, topic text NOT NULL)")
    m.execute("GRANT SELECT ON regulation.work_topic TO reg_app")
    m.commit()

    def put(rows):
        for w, t in rows:
            m.execute("INSERT INTO regulation.work_topic VALUES (%s, %s)", (w, t))
        m.commit()

    yield put
    m.execute("DROP TABLE regulation.work_topic")
    m.commit()
    m.close()

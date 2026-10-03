import pytest


@pytest.fixture
def topic_table(migrated):
    """regulation.work_topic(마이그레이션 0011)에 분류 행을 넣는다 (reg topics classify 대역). 끝나면 지운다."""
    from reg.platform.db.conn import connect

    m = connect(migrated[1])

    def put(rows):
        for rank, (w, t) in enumerate(rows):
            m.execute("INSERT INTO regulation.work_topic (work_id, topic, score, method, rank) VALUES (%s, %s, 1.0, 'title', 1)"
                      " ON CONFLICT DO NOTHING", (w, t))
        m.commit()

    yield put
    m.execute("DELETE FROM regulation.work_topic")
    m.commit()
    m.close()

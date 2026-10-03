"""work_topic·compare_cell 읽기·쓰기 (마이그레이션 0011). 둘 다 다시 만들 수 있는 파생 데이터다."""
from reg.compare.classify import WorkText

# 현행 판본이 있는 내부규정 (폐지 제외). 첫 조(대개 제1조 목적)를 함께 읽는다
WORK_TEXTS = """
SELECT w.id AS work_id, w.title, i.code AS institution,
       (SELECT pv.number_label || COALESCE('(' || pv.heading || ')', '') || ' ' || pv.text
          FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id
         WHERE vp.work_version_id = v.id AND pv.unit = 'article' ORDER BY vp.ord LIMIT 1) AS first_text
FROM regulation.work w
JOIN regulation.institution i ON i.id = w.institution_id
JOIN regulation.work_version v ON v.work_id = w.id AND v.version_state = 'CURRENT'
WHERE w.status <> 'ABOLISHED' {extra}
ORDER BY w.id
"""


def work_texts(conn, work_ids: list[str] | None = None, unclassified: bool = False) -> list[WorkText]:
    extra, args = "", ()
    if work_ids:
        extra, args = "AND w.id = ANY(%s)", (list(work_ids),)
    elif unclassified:
        extra = "AND NOT EXISTS (SELECT 1 FROM regulation.work_topic t WHERE t.work_id = w.id)"
    return [WorkText(r["work_id"], r["title"], r["first_text"] or "")
            for r in conn.execute(WORK_TEXTS.format(extra=extra), args).fetchall()]


def save_topics(conn, result: dict[str, list[tuple[str, float, str]]], replace_all: bool = False) -> int:
    """분류 결과를 쓴다. 사람이 고친 행(method='manual')이 있는 규정은 건드리지 않는다. replace_all이면 결과에 없는
    규정의 자동 분류 행도 지운다(없어진 규정 정리)."""
    manual = {r["work_id"] for r in conn.execute("SELECT DISTINCT work_id FROM regulation.work_topic WHERE method = 'manual'")}
    if replace_all:
        conn.execute("DELETE FROM regulation.work_topic WHERE method <> 'manual'")
    else:
        conn.execute("DELETE FROM regulation.work_topic WHERE method <> 'manual' AND work_id = ANY(%s)", (list(result),))
    rows = [(wid, t, s, m, rank) for wid, got in result.items() if wid not in manual
            for rank, (t, s, m) in enumerate(got, 1)]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO regulation.work_topic (work_id, topic, score, method, rank) VALUES (%s,%s,%s,%s,%s)"
                        " ON CONFLICT (work_id, topic) DO NOTHING", rows)
    conn.commit()
    return len(rows)


def topic_works(conn, topic: str, institution: str | None = None) -> dict[str, list[str]]:
    """{기관 코드: [work_id]} — 그 주제로 분류된 현행 내부규정."""
    rows = conn.execute(
        "SELECT i.code, w.id FROM regulation.work_topic t JOIN regulation.work w ON w.id = t.work_id"
        " JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE t.topic = %s AND w.status <> 'ABOLISHED' AND (%s::text IS NULL OR i.code = %s)"
        " AND EXISTS (SELECT 1 FROM regulation.work_version v WHERE v.work_id = w.id AND v.version_state = 'CURRENT')"
        " ORDER BY i.code, w.id", (topic, institution, institution)).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["code"], []).append(r["id"])
    return out


def institutions(conn) -> list[dict]:
    return conn.execute("SELECT code, name FROM regulation.institution WHERE active ORDER BY id").fetchall()


def save_cells(conn, cells) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO regulation.compare_cell (topic, item, institution_code, work_id, version_id, pv_id, path, value,"
            " value_norm, quote, method, confidence) VALUES (%(topic)s, %(item)s, %(institution_code)s, %(work_id)s,"
            " %(version_id)s, %(pv_id)s, %(path)s, %(value)s, %(value_norm)s, %(quote)s, %(method)s, %(confidence)s)"
            " ON CONFLICT (topic, item, institution_code) DO UPDATE SET work_id = EXCLUDED.work_id,"
            " version_id = EXCLUDED.version_id, pv_id = EXCLUDED.pv_id, path = EXCLUDED.path, value = EXCLUDED.value,"
            " value_norm = EXCLUDED.value_norm, quote = EXCLUDED.quote, method = EXCLUDED.method,"
            " confidence = EXCLUDED.confidence, extracted_at = now()"
            " WHERE regulation.compare_cell.method <> 'manual'", [c.row() for c in cells])
    conn.commit()
    return len(cells)


def changed_institutions(conn) -> list[str]:
    """비교값을 만든 뒤 새 판본이 들어온 기관 (또는 아직 비교값이 없는 기관). 처리 DAG 뒤에 이 기관만 다시 만든다."""
    rows = conn.execute(
        "SELECT i.code FROM regulation.institution i WHERE i.active AND ("
        " NOT EXISTS (SELECT 1 FROM regulation.compare_cell c WHERE c.institution_code = i.code) OR"
        " (SELECT max(v.created_at) FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id"
        "   WHERE w.institution_id = i.id) >"
        " (SELECT min(c.extracted_at) FROM regulation.compare_cell c WHERE c.institution_code = i.code)) ORDER BY i.id"
    ).fetchall()
    return [r["code"] for r in rows]

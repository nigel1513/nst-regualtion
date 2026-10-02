import json


def write(conn, topic: str, payload: dict) -> int:
    row = conn.execute("INSERT INTO ops.outbox (topic, payload) VALUES (%s, %s) RETURNING id",
                       (topic, json.dumps(payload, ensure_ascii=False))).fetchone()
    return row["id"]

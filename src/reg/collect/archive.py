"""원본 보관: 내용 주소(SHA-256) 방식. 같은 내용은 blob 1개, source_document 1행."""
import hashlib
import json
from dataclasses import dataclass

from reg.collect.sniff import FileKind
from reg.storage.blob import BlobStore, blob_key


@dataclass
class StoredDoc:
    id: int
    sha256: str
    blob_key: str
    is_new: bool


def store(conn, blob: BlobStore, *, source: str, url: str, content: bytes, kind: FileKind,
          meta: dict) -> StoredDoc:
    sha = hashlib.sha256(content).hexdigest()
    row = conn.execute("SELECT id, blob_key FROM regulation.source_document WHERE source = %s AND sha256 = %s",
                       (source, sha)).fetchone()
    if row:
        return StoredDoc(row["id"], sha, row["blob_key"], False)
    key = blob_key(source, sha, kind.ext)
    if not blob.exists(key):
        blob.put(key, content, kind.mime)
    row = conn.execute(
        "INSERT INTO regulation.source_document (source, sha256, blob_key, mime, size_bytes, url, source_meta)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (source, sha, key, kind.mime, len(content), url, json.dumps(meta, ensure_ascii=False)),
    ).fetchone()
    return StoredDoc(row["id"], sha, key, True)

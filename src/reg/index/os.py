"""OpenSearch HTTP 클라이언트 (SDK 없이). 이 프로젝트 이름(nais-regulations*)만 다룬다."""
import json

import httpx

from reg.index.mapping import ALIAS, PIPELINE, PIPELINE_BODY, index_body


class OpenSearch:
    def __init__(self, url: str, timeout: float = 60.0):
        self.c = httpx.Client(base_url=url.rstrip("/"), timeout=timeout)

    def _ok(self, r: httpx.Response) -> dict:
        if r.status_code >= 300:
            raise RuntimeError(f"OpenSearch {r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def put_pipeline(self) -> None:
        self._ok(self.c.put(f"/_search/pipeline/{PIPELINE}", json=PIPELINE_BODY))

    def create_index(self, name: str, dim: int) -> None:
        assert name.startswith(ALIAS + "-")
        self._ok(self.c.put(f"/{name}", json=index_body(dim)))

    def delete_index(self, name: str) -> None:
        assert name.startswith(ALIAS + "-")
        r = self.c.delete(f"/{name}")
        if r.status_code not in (200, 404):
            self._ok(r)

    def bulk(self, name: str, docs: list[dict], id_field: str = "chunk_id") -> int:
        if not docs:
            return 0
        lines = []
        for d in docs:
            lines.append(json.dumps({"index": {"_index": name, "_id": d[id_field]}}))
            lines.append(json.dumps(d, ensure_ascii=False))
        r = self._ok(self.c.post("/_bulk", content="\n".join(lines) + "\n",
                                 headers={"Content-Type": "application/x-ndjson"}))
        if r.get("errors"):
            first = next(i["index"]["error"] for i in r["items"] if "error" in i["index"])
            raise RuntimeError(f"bulk 오류: {first}")
        return len(docs)

    def refresh(self, name: str) -> None:
        self._ok(self.c.post(f"/{name}/_refresh"))

    def count(self, name: str) -> int:
        return self._ok(self.c.get(f"/{name}/_count"))["count"]

    def indexes(self) -> list[str]:
        """이 프로젝트 색인(nais-regulations-*) 이름. 없으면 []."""
        rows = self._ok(self.c.get(f"/_cat/indices/{ALIAS}-*", params={"format": "json", "h": "index"}))
        return sorted(r["index"] for r in rows)

    def alias_target(self) -> str | None:
        r = self.c.get(f"/_alias/{ALIAS}")
        if r.status_code == 404:
            return None
        return next(iter(self._ok(r)), None)

    def swap_alias(self, new_index: str) -> str | None:
        old = self.alias_target()
        actions = [{"add": {"index": new_index, "alias": ALIAS}}]
        if old:
            actions.insert(0, {"remove": {"index": old, "alias": ALIAS}})
        self._ok(self.c.post("/_aliases", json={"actions": actions}))
        return old

    def search(self, body: dict, pipeline: str | None = None, index: str = ALIAS) -> dict:
        params = {"search_pipeline": pipeline} if pipeline else None
        return self._ok(self.c.post(f"/{index}/_search", json=body, params=params))

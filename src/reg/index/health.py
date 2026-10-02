"""임베딩 서버 확인 (spec 6.2 GPU 불가): 응답이 없으면 색인 태스크만 미룬다."""
import time

from reg.platform.llm import ProviderError


def embed_ok(embedder, limit: float = 5.0) -> bool:
    t = time.monotonic()
    try:
        vec = embedder.embed(["임베딩 서버 확인"])
    except ProviderError:
        return False
    return bool(vec and vec[0]) and time.monotonic() - t <= limit

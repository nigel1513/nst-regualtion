"""기관 비교 Airflow 진입점 (index.tasks와 같은 모양): 설정으로 연결하고, ops.pipeline_run에 남기고, dict를 돌려준다.

처리 DAG(reg_process) 뒤에 classify_topics() → build_compare(changed_only=True) 순서로 부른다."""
from reg.compare.build import build, cached_embed, classify_works
from reg.compare.config import load
from reg.compare.store import changed_institutions, work_texts
from reg.index.os import OpenSearch
from reg.platform.llm import EmbeddingProvider, LLMProvider, RerankProvider
from reg.platform.runs import open_conn, task_run
from reg.platform.settings import get_settings


def classify_topics(all_works: bool = False) -> dict:
    """아직 분류하지 않은 규정(새 규정)을 분류한다. all_works면 모두 다시."""
    s = get_settings()
    emb = EmbeddingProvider(s.embed_url, s.embed_model, batch=32)
    with task_run("compare.classify") as rec, open_conn() as conn:
        ws = work_texts(conn, unclassified=not all_works)
        pool = None if all_works or not ws else work_texts(conn)
        out = classify_works(conn, load(), cached_embed(conn, emb, s.embed_model), ws, replace_all=all_works,
                             exemplars=pool)
        out.pop("result")
        rec.update(out)
    return out


def build_compare(changed_only: bool = True, topics: list[str] | None = None) -> dict:
    """비교값을 만든다. changed_only면 새 판본이 들어온 기관(또는 아직 값이 없는 기관)만."""
    s = get_settings()
    deps = {"os": OpenSearch(s.os_url), "embedder": EmbeddingProvider(s.embed_url, s.embed_model, timeout=10),
            "reranker": RerankProvider(s.rerank_url, s.rerank_model), "llm": LLMProvider(s.llm_url, s.llm_model, timeout=90)}
    with task_run("compare.build") as rec, open_conn() as conn:
        insts = changed_institutions(conn) if changed_only else None
        if changed_only and not insts:
            out = {"skipped": True, "institutions": 0}
        else:
            out = build(conn, deps, load(), topics, insts)
        rec.update(out)
    return out

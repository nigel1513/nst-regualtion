"""reg topics … / reg compare … (서비스 UI 개편 spec §4). --dry-run은 DB를 읽기 전용으로 연다."""
import time
from pathlib import Path

import typer
import yaml

topics_app = typer.Typer(no_args_is_help=True, help="규정 ↔ 주제 분류 (기관 비교)")
compare_app = typer.Typer(no_args_is_help=True, help="주제·항목 × 기관 비교값")


def _conn(read_only: bool):
    from reg.platform.runs import open_conn

    c = open_conn()
    c.read_only = read_only
    return c


def _split(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


@topics_app.command("classify")
def classify_cmd(all_: bool = typer.Option(False, "--all", help="모든 현행 규정을 다시 분류 (기본: 아직 분류하지 않은 규정만)"),
                 works: str = typer.Option(None, "--works", help="이 규정만 (work id, 쉼표로)"),
                 dry_run: bool = typer.Option(False, "--dry-run", help="쓰지 않고 분포만 본다 (읽기 전용)")) -> None:
    from reg.compare.build import cached_embed, classify_works
    from reg.compare.config import load
    from reg.compare.store import work_texts
    from reg.platform.llm import EmbeddingProvider
    from reg.platform.settings import get_settings

    s = get_settings()
    emb = EmbeddingProvider(s.embed_url, s.embed_model, batch=32)
    t0 = time.monotonic()
    with _conn(dry_run) as conn:
        ws = work_texts(conn, _split(works), unclassified=not (all_ or works))
        embed = emb.embed if dry_run else cached_embed(conn, emb, s.embed_model)
        st = classify_works(conn, load(), embed, ws, replace_all=all_ and not works, dry_run=dry_run)
    st.pop("result")
    typer.echo({**st, "seconds": round(time.monotonic() - t0, 1)})


@topics_app.command("eval")
def eval_cmd(cases: Path = typer.Option(None, help="정답 표본 (기본 eval/topic_cases.yaml)"),
             sets: str = typer.Option(None, "--set", help="A,B,C 중 일부")) -> None:
    """수기 정답 표본으로 분류 정확도를 잰다 (읽기 전용). 맞음 = 예측 첫째 주제가 정답 목록 안에 있음."""
    from reg.compare.classify import classify
    from reg.compare.config import load
    from reg.compare.store import work_texts
    from reg.platform.llm import EmbeddingProvider
    from reg.platform.settings import ROOT, get_settings

    s = get_settings()
    data = yaml.safe_load((cases or ROOT / "eval/topic_cases.yaml").read_text(encoding="utf-8"))["cases"]
    want = set(_split(sets) or [])
    data = [c for c in data if not want or c["set"] in want]
    with _conn(True) as conn:
        ws = {w.work_id: w for w in work_texts(conn, [c["work_id"] for c in data])}
    got = classify(list(ws.values()), load().topics, EmbeddingProvider(s.embed_url, s.embed_model).embed)
    by_set: dict[str, list[int]] = {}
    for c in data:
        if c["work_id"] not in got:
            continue
        top = got[c["work_id"]][0][0]
        r = by_set.setdefault(c["set"], [0, 0, 0])
        r[0] += 1
        r[1] += top in c["gold"]
        r[2] += top == c["gold"][0]
        if top not in c["gold"]:
            typer.echo(f"  틀림 [{c['set']}] {c['title']} → {got[c['work_id']]} (정답 {c['gold']})")
    for k, (n, ok, strict) in sorted(by_set.items()):
        typer.echo(f"set {k}: {n}건 정확도 {ok / n:.3f} (strict {strict / n:.3f})")
    typer.echo(f"DB에 없는 표본: {sum(1 for c in data if c['work_id'] not in got)}건")


@compare_app.command("build")
def build_cmd(topic: str = typer.Option(None, "--topic", help="주제 id (쉼표로 여럿, 기본: 비교 항목이 있는 모든 주제)"),
              inst: str = typer.Option(None, "--inst", help="기관 코드 (쉼표로 여럿, 기본: 활성 기관 전부)"),
              changed: bool = typer.Option(False, "--changed", help="비교값을 만든 뒤 새 판본이 들어온 기관만"),
              dry_run: bool = typer.Option(False, "--dry-run", help="쓰지 않고 칸을 출력한다 (읽기 전용)")) -> None:
    from reg.compare.build import build
    from reg.compare.config import load
    from reg.compare.store import changed_institutions
    from reg.index.os import OpenSearch
    from reg.platform.llm import EmbeddingProvider, LLMProvider, RerankProvider
    from reg.platform.settings import get_settings

    s = get_settings()
    cfg = load()
    topics = _split(topic)
    if topics and (bad := [t for t in topics if t not in cfg.items]):
        raise typer.BadParameter(f"비교 항목이 없는 주제: {bad}")
    deps = {"os": OpenSearch(s.os_url), "embedder": EmbeddingProvider(s.embed_url, s.embed_model, timeout=10),
            "reranker": RerankProvider(s.rerank_url, s.rerank_model), "llm": LLMProvider(s.llm_url, s.llm_model, timeout=90)}

    def show(c) -> None:
        if dry_run:
            typer.echo(f"{c.topic}\t{c.item}\t{c.institution_code}\t{c.method}\t{c.value or ''}\t{c.value_norm or ''}\t"
                       f"{c.title or ''} {c.path or ''}\t{(c.quote or c.note or '')[:120]}")

    with _conn(dry_run) as conn:
        insts = _split(inst) or (changed_institutions(conn) if changed else None)
        if changed and not insts:
            typer.echo("바뀐 기관이 없습니다")
            return
        st = build(conn, deps, cfg, topics, insts, dry_run=dry_run, on_cell=show)
    typer.echo(st)

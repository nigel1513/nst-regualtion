from pathlib import Path
from urllib.parse import urlparse

import typer
import yaml

from reg.collect.alio import AlioClient
from reg.collect.alio_sync import load_institutions, sync_institution
from reg.collect.law_sync import sync_laws
from reg.collect.lawgo import LawGoClient
from reg.collect.polite import PoliteClient
from reg.collect.runs import db_logger, finish_run, open_log_conn, start_run
from reg.db.bootstrap import bootstrap
from reg.db.conn import connect
from reg.db.migrate import upgrade
from reg.process import process_once, rebuild_all
from reg.settings import get_settings
from reg.storage.blob import S3BlobStore
from reg.views.converter import DockerConverter

ROOT = Path(__file__).resolve().parents[2]
app = typer.Typer(no_args_is_help=True)
db = typer.Typer(no_args_is_help=True, help="DB 역할·스키마·마이그레이션")
bucket = typer.Typer(no_args_is_help=True, help="원본 보관 버킷")
collect = typer.Typer(no_args_is_help=True, help="ALIO·law.go.kr 수집")
app.add_typer(db, name="db")
app.add_typer(bucket, name="bucket")
app.add_typer(collect, name="collect")


def _blob() -> S3BlobStore:
    s = get_settings()
    return S3BlobStore(s.s3_endpoint, s.s3_bucket, s.s3_access_key, s.s3_secret_key)


@db.command("bootstrap")
def db_bootstrap(superuser_dsn: str = typer.Option(None, envvar="REG_SUPERUSER_URL")) -> None:
    s = get_settings()
    app_url, mig_url = urlparse(s.database_url), urlparse(s.migrator_url)
    bootstrap(superuser_dsn, app_url.path.lstrip("/"), mig_url.password, app_url.password)
    typer.echo("bootstrap 완료: reg_migrator, reg_app, schema regulation")


@db.command("upgrade")
def db_upgrade() -> None:
    upgrade(get_settings().migrator_url)
    typer.echo("migrate 완료")


@bucket.command("ensure")
def bucket_ensure() -> None:
    _blob().ensure_bucket()
    typer.echo(f"bucket 준비: {get_settings().s3_bucket}")


def _run(source: str, scope: str | None, body) -> None:
    dsn = get_settings().database_url
    conn, log_conn = connect(dsn), open_log_conn(dsn)
    run_id = start_run(conn, source, scope)
    try:
        stats = body(conn, db_logger(log_conn, run_id))
    except Exception as e:
        finish_run(conn, run_id, "failed", {}, f"{type(e).__name__}: {e}")
        typer.echo(f"실패 (run {run_id}): {e}", err=True)
        raise typer.Exit(1)
    except BaseException as e:  # Ctrl-C, SIGTERM: 실행 상태를 남기고 그대로 전파
        finish_run(conn, run_id, "failed", {}, type(e).__name__)
        raise
    else:
        finish_run(conn, run_id, "succeeded", stats)
        typer.echo(f"완료 (run {run_id}): {stats}")
    finally:
        log_conn.close()
        conn.close()


@collect.command("alio")
def collect_alio(institution: str = typer.Option(None, help="기관 코드 (예: KASI)"),
                 limit: int = typer.Option(None, help="기관당 규정 수 상한 (시험용)")) -> None:
    def body(conn, log):
        http = PoliteClient("alio", get_settings().alio_min_interval, log=log)
        alio, blob, total = AlioClient(http), _blob(), {}
        for inst in load_institutions(conn, ROOT / "config/institutions.yaml"):
            if institution and inst["code"] != institution:
                continue
            total[inst["code"]] = sync_institution(conn, alio, blob, inst, limit=limit)
        return total
    _run("alio", institution, body)


@collect.command("law")
def collect_law() -> None:
    def body(conn, log):
        s = get_settings()
        client = LawGoClient(PoliteClient("lawgo", s.lawgo_min_interval, log=log), oc=s.lawgo_oc)
        names = yaml.safe_load((ROOT / "config/laws.yaml").read_text(encoding="utf-8"))
        names += [r["name"] for r in conn.execute("SELECT name FROM regulation.law_seed ORDER BY name").fetchall()
                  if r["name"] not in names]  # 참조에서 발견된 법령 (spec 6.1)
        return sync_laws(conn, client, _blob(), names)
    _run("lawgo", None, body)


@app.command("process")
def process_cmd(limit: int = typer.Option(100, help="한 번에 처리할 이벤트 수"),
                all_: bool = typer.Option(False, "--all", help="남은 이벤트가 없을 때까지 반복"),
                rebuild: bool = typer.Option(False, "--rebuild", help="구조화 결과를 지우고 처음부터 다시 처리"),
                no_convert: bool = typer.Option(False, "--no-convert", help="HWP 보기용 PDF 변환 생략")) -> None:
    def body(conn, log):
        loop = all_ or rebuild
        if rebuild:
            rebuild_all(conn)
        converter = None if no_convert else DockerConverter()
        total = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
        while True:
            st = process_once(conn, _blob(), limit=limit, converter=converter)
            for k in total:
                total[k] += st[k]
            if not loop or st["claimed"] == 0 or st["ok"] == 0:
                return total
    _run("process", None, body)


@app.command("api")
def api_cmd(host: str = "0.0.0.0", port: int = 21061) -> None:
    import uvicorn

    from reg.api.app import create_app
    from reg.llm import EmbeddingProvider, LLMProvider, RerankProvider
    from reg.search.os import OpenSearch

    s = get_settings()
    deps = {"os": OpenSearch(s.os_url), "embedder": EmbeddingProvider(s.embed_url, s.embed_model),
            "reranker": RerankProvider(s.rerank_url, s.rerank_model),
            "llm": LLMProvider(s.llm_url, s.llm_model), "llm_model": s.llm_model}
    uvicorn.run(create_app(s.database_url, _blob(), deps), host=host, port=port, log_level="info")


index = typer.Typer(no_args_is_help=True, help="검색 색인(게시 버전)")
app.add_typer(index, name="index")


@index.command("build")
def index_build(no_publish: bool = typer.Option(False, "--no-publish")) -> None:
    from reg.llm import EmbeddingProvider
    from reg.search.indexer import build_release
    from reg.search.os import OpenSearch

    s = get_settings()
    conn = connect(s.database_url)
    st = build_release(conn, OpenSearch(s.os_url), EmbeddingProvider(s.embed_url, s.embed_model), s.embed_model,
                       publish=not no_publish)
    typer.echo(f"release {st}")


@index.command("status")
def index_status() -> None:
    from reg.search.os import OpenSearch

    s = get_settings()
    conn = connect(s.database_url)
    for r in conn.execute("SELECT id, state, os_index, stats, created_at FROM regulation.release ORDER BY id DESC LIMIT 5"):
        typer.echo(f"{r['id']} {r['state']} {r['os_index']} {r['stats']}")
    typer.echo(f"alias → {OpenSearch(s.os_url).alias_target()}")


evalc = typer.Typer(no_args_is_help=True, help="평가")
app.add_typer(evalc, name="eval")


@evalc.command("qa")
def eval_qa(limit: int = typer.Option(None, help="앞에서 N문항만"),
            out: Path = typer.Option(ROOT / "docs/reports/2026-10-02-qa-eval.md")) -> None:
    from datetime import datetime

    from reg.evaluate import run_eval
    from reg.llm import EmbeddingProvider, LLMProvider, RerankProvider
    from reg.search.os import OpenSearch

    s = get_settings()
    conn = connect(s.database_url)
    deps = {"os": OpenSearch(s.os_url), "embedder": EmbeddingProvider(s.embed_url, s.embed_model),
            "reranker": RerankProvider(s.rerank_url, s.rerank_model), "llm": LLMProvider(s.llm_url, s.llm_model),
            "llm_model": s.llm_model}
    cases = yaml.safe_load((ROOT / "eval/qa_cases.yaml").read_text(encoding="utf-8"))[:limit]
    r = run_eval(conn, deps, cases)
    detail = {row["qa_id"]: row for row in r["cases"]}
    logs = {x["id"]: x for x in conn.execute(
        "SELECT id, status, verdict, retrieved FROM regulation.qa_log WHERE id = ANY(%s)", (list(detail),)).fetchall()}
    lines = [f"# 질의응답 평가 ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"- 모델: {s.llm_model} · 임베딩 {s.embed_model} · 리랭커 {s.rerank_model} · 문항 {r['n']}개", "",
             "| 지표 | 값 | 목표 (spec 12) |", "|---|---|---|",
             f"| 상태 일치율 | {r['status_acc']} | - |", f"| 근거 적중률 (기대 조문이 근거 1·2위) | {r['citation_hit']} | ≥ 0.90 |",
             f"| 결론 정확도 | {r['verdict_acc']} | ≥ 0.85 |", f"| 기관 되묻기 정확도 | {r['need_institution_acc']} | 1.00 |",
             f"| p95 응답 시간(ms) | {r['p95_latency_ms']} | < 10000 |", "",
             "| 문항 | 기대 상태 | 실제 상태 | 근거 | 결론 | 근거 1위 |", "|---|---|---|---|---|---|"]
    for c, row in zip(cases, r["cases"]):
        lg = logs.get(row["qa_id"]) or {}
        top = (lg.get("retrieved") or [{}])[0]
        mark = lambda v: "-" if v is None else ("O" if v else "X")  # noqa: E731
        lines.append(f"| {c['id']} | {c['expect']['status']} | {row['status']} | {mark(row['citation_ok'])} | "
                     f"{mark(row['verdict_ok'])} {lg.get('verdict') or ''} | {top.get('version_id', '')} {top.get('path', '')} |")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo({k: v for k, v in r.items() if k != "cases"})
    typer.echo(f"보고서: {out}")

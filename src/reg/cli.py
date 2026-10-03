from pathlib import Path
from urllib.parse import urlparse

import typer
import yaml

from reg import wiring
from reg.platform.db.bootstrap import bootstrap
from reg.platform.db.conn import connect
from reg.platform.db.migrate import upgrade
from reg.platform.settings import ROOT, get_settings
from reg.platform.storage.blob import blob_store

app = typer.Typer(no_args_is_help=True)
db = typer.Typer(no_args_is_help=True, help="DB 역할·스키마·마이그레이션")
bucket = typer.Typer(no_args_is_help=True, help="원본 보관 버킷")
collect = typer.Typer(no_args_is_help=True, help="ALIO·law.go.kr 수집")
app.add_typer(db, name="db")
app.add_typer(bucket, name="bucket")
app.add_typer(collect, name="collect")
wiring.register_sources()
for _name, _sub in wiring.subcommands():
    app.add_typer(_sub, name=_name)
app.command("process")(wiring.process_command())


@db.command("bootstrap")
def db_bootstrap(superuser_dsn: str = typer.Option(None, envvar="REG_SUPERUSER_URL")) -> None:
    s = get_settings()
    app_url, mig_url = urlparse(s.database_url), urlparse(s.migrator_url)
    bootstrap(superuser_dsn, app_url.path.lstrip("/") or "nst_regulation", mig_url.password, app_url.password)
    typer.echo(f"bootstrap 완료: DB {app_url.path.lstrip('/')}, 역할 reg_migrator·reg_app, 스키마 regulation·law·ops")


@db.command("upgrade")
def db_upgrade() -> None:
    upgrade(get_settings().migrator_url, wiring.migration_locations())
    typer.echo("migrate 완료")


@bucket.command("ensure")
def bucket_ensure() -> None:
    blob_store().ensure_bucket()
    typer.echo(f"bucket 준비: {get_settings().s3_bucket}")


@collect.command("alio")
def collect_alio(institution: str = typer.Option(None, help="기관 코드 (예: KASI)"),
                 limit: int = typer.Option(None, help="기관당 규정 수 상한 (시험용)")) -> None:
    """`reg alio collect`의 별칭 (기존 명령 유지)."""
    from reg.sources.alio.cli import collect

    collect(institution=institution, limit=limit)


@collect.command("law")
def collect_law() -> None:
    """`reg law collect`의 별칭 (기존 명령 유지)."""
    from reg.sources.lawgo.cli import collect

    collect()


@app.command("api")
def api_cmd(host: str = "0.0.0.0", port: int = 21061) -> None:
    import uvicorn

    from reg.api.app import create_app
    from reg.index.os import OpenSearch
    from reg.platform.llm import EmbeddingProvider, LLMProvider, RerankProvider

    s = get_settings()
    # 질의 시점: 임베딩이 안 되면 바로 BM25로 넘어가도록 짧게, 답변 생성은 프록시 제한(60초) 안에서 끝나도록
    deps = {"os": OpenSearch(s.os_url), "embedder": EmbeddingProvider(s.embed_url, s.embed_model, timeout=5, tries=1),
            "reranker": RerankProvider(s.rerank_url, s.rerank_model, timeout=10),
            "llm": LLMProvider(s.llm_url, s.llm_model, timeout=25), "llm_model": s.llm_model}
    uvicorn.run(create_app(s.database_url, blob_store(), deps), host=host, port=port, log_level="info")


evalc = typer.Typer(no_args_is_help=True, help="평가")
app.add_typer(evalc, name="eval")


@evalc.command("qa")
def eval_qa(limit: int = typer.Option(None, help="앞에서 N문항만"),
            out: Path = typer.Option(ROOT / "docs/reports/2026-10-02-qa-eval.md"),
            no_log: bool = typer.Option(False, "--no-log", help="읽기 전용: 질의 기록을 남기지 않는다 (DB 연결을 read-only로)")) -> None:
    from datetime import datetime

    from reg.index.os import OpenSearch
    from reg.platform.llm import EmbeddingProvider, LLMProvider, RerankProvider
    from reg.qa.evaluate import run_eval

    s = get_settings()
    conn = connect(s.database_url)
    if no_log:
        conn.read_only = True
    deps = {"os": OpenSearch(s.os_url), "embedder": EmbeddingProvider(s.embed_url, s.embed_model),
            "reranker": RerankProvider(s.rerank_url, s.rerank_model), "llm": LLMProvider(s.llm_url, s.llm_model),
            "llm_model": s.llm_model}
    cases = yaml.safe_load((ROOT / "eval/qa_cases.yaml").read_text(encoding="utf-8"))[:limit]
    r = run_eval(conn, deps, cases, log=not no_log)
    target = deps["os"].alias_target()
    lines = [f"# 질의응답 평가 ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"- 모델: {s.llm_model} · 임베딩 {s.embed_model} · 리랭커 {s.rerank_model} · 문항 {r['n']}개"
             f" · 색인 {target}{' · 읽기 전용(기록 없음)' if no_log else ''}", "",
             "| 지표 | 값 | 목표 (spec 12) |", "|---|---|---|",
             f"| 상태 일치율 | {r['status_acc']} | - |", f"| 인용 정확도 (답변이 인용한 조문이 기대 조문) | {r['citation_hit']} | ≥ 0.90 |",
             f"| 검색 적중률 (기대 조문이 근거 1·2위) | {r['retrieval_hit']} | - |",
             f"| 숫자 일치율 | {r['numbers_rate']} | 1.00 |", f"| 결론-설명 일관성 | {r['consistency_rate']} | 1.00 |",
             f"| 결론 정확도 | {r['verdict_acc']} | ≥ 0.85 |", f"| 기관 되묻기 정확도 | {r['need_institution_acc']} | 1.00 |",
             f"| p95 응답 시간(ms) | {r['p95_latency_ms']} | < 10000 |", "",
             "| 문항 | 기대 상태 | 실제 상태 | 근거 | 결론 | 근거 1위 |", "|---|---|---|---|---|---|"]
    for c, row in zip(cases, r["cases"]):
        mark = lambda v: "-" if v is None else ("O" if v else "X")
        lines.append(f"| {c['id']} | {c['expect']['status']} | {row['status']} | {mark(row['citation_ok'])} | "
                     f"{mark(row['verdict_ok'])} {row.get('verdict') or ''} | {row.get('top') or ''} |")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo({k: v for k, v in r.items() if k != "cases"})
    typer.echo(f"보고서: {out}")

import os
from pathlib import Path
from urllib.parse import urlparse

import typer
import yaml

from reg.collect.alio import AlioClient
from reg.collect.alio_sync import load_institutions, sync_institution
from reg.collect.law_sync import sync_laws
from reg.collect.lawgo import LawGoClient
from reg.collect.polite import PoliteClient
from reg.collect.runs import db_logger, finish_run, start_run
from reg.db.bootstrap import bootstrap
from reg.db.conn import connect
from reg.db.migrate import upgrade
from reg.settings import get_settings
from reg.storage.blob import S3BlobStore

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
    conn = connect(get_settings().database_url)
    run_id = start_run(conn, source, scope)
    try:
        stats = body(conn, db_logger(conn, run_id))
    except Exception as e:
        finish_run(conn, run_id, "failed", {}, f"{type(e).__name__}: {e}")
        typer.echo(f"실패 (run {run_id}): {e}", err=True)
        raise typer.Exit(1)
    finish_run(conn, run_id, "succeeded", stats)
    typer.echo(f"완료 (run {run_id}): {stats}")


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
        return sync_laws(conn, client, _blob(), names)
    _run("lawgo", None, body)

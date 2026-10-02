"""reg alio … — ALIO 내부규정 수집."""
import typer

from reg.sources.alio.config import INSTITUTIONS_YAML

alio = typer.Typer(no_args_is_help=True, help="ALIO 내부규정 수집")


@alio.command("collect")
def collect(institution: str = typer.Option(None, help="기관 코드 (예: KASI)"),
            limit: int = typer.Option(None, help="기관당 규정 수 상한 (시험용)")) -> None:
    from reg.platform.http import PoliteClient
    from reg.platform.runs import run_logged
    from reg.platform.settings import get_settings
    from reg.platform.storage.blob import blob_store
    from reg.sources.alio.client import AlioClient
    from reg.sources.alio.sync import load_institutions, sync_institution

    def body(conn, log):
        http = PoliteClient("alio", get_settings().alio_min_interval, log=log)
        alio_c, blob, total = AlioClient(http), blob_store(), {}
        for inst in load_institutions(conn, INSTITUTIONS_YAML):
            if institution and inst["code"] != institution:
                continue
            total[inst["code"]] = sync_institution(conn, alio_c, blob, inst, limit=limit)
        return total
    run_id, stats = run_logged("alio", institution, body)
    typer.echo(f"완료 (run {run_id}): {stats}")

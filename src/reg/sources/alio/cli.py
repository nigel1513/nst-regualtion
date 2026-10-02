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


@alio.command("abolish")
def abolish_cmd(work_id: str = typer.Argument(..., help="규범문서 id (예: kr/reg/KASI/구출장여비지급요령)"),
                reject: bool = typer.Option(False, "--reject", help="폐지 아님: 현행으로 되돌리고 사라진 날을 지운다")) -> None:
    """폐지 후보를 확정하거나(기본) 반려한다(--reject)."""
    from reg.platform.runs import open_conn
    from reg.sources.alio.reconcile import AbolishError, decide

    with open_conn() as conn:
        try:
            r = decide(conn, work_id, confirm=not reject)
        except AbolishError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1)
    typer.echo(f"{r['work_id']}: {r['status']}" + (f" (폐지일 {r['abolished_on']})" if r["abolished_on"] else ""))


@alio.command("reconcile")
def reconcile_cmd() -> None:
    """원장(alio_rule)에서 work.status·폐지 검수 작업을 다시 맞춘다 (reg process --rebuild 뒤 실행)."""
    from reg.sources.alio import tasks

    typer.echo(tasks.reconcile([]))


@alio.command("backfill")
def backfill_cmd(institution: str = typer.Option(..., "--institution", help="기관 코드 (config/sources/alio.yaml)")) -> None:
    """새 기관 전체 수집(비활성이어도) → 대조."""
    from reg.sources.alio import tasks

    typer.echo(tasks.backfill(institution))
    typer.echo("다음: reg process --all  (일 배치에 넣으려면 config/sources/alio.yaml에서 active: true)")


@alio.command("canary")
def canary_cmd() -> None:
    """ALIO 응답 구조 점검: 목록 1쪽 + 상세 1건. 0 정상, 2 구조 변경, 1 점검·장애."""
    from reg.sources.alio import tasks
    from reg.sources.alio.canary import AlioSchemaChanged
    from reg.sources.alio.client import AlioError

    try:
        r = tasks.canary_check()
    except AlioSchemaChanged as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)
    except AlioError as e:
        typer.echo(f"ALIO 점검·장애 (구조 변경 아님): {e}", err=True)
        raise typer.Exit(1)
    typer.echo(r)

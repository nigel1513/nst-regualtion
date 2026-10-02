"""reg process — 수집 이벤트 처리 (추출·파싱·적재)."""
import typer


def process_cmd(limit: int = typer.Option(100, help="한 번에 처리할 이벤트 수"),
                all_: bool = typer.Option(False, "--all", help="남은 이벤트가 없을 때까지 반복"),
                rebuild: bool = typer.Option(False, "--rebuild", help="구조화 결과를 지우고 처음부터 다시 처리"),
                no_convert: bool = typer.Option(False, "--no-convert", help="HWP 보기용 PDF 변환 생략")) -> None:
    from reg.core.ingest.process import process_once, rebuild_all
    from reg.platform.convert import get_converter
    from reg.platform.runs import run_logged
    from reg.platform.storage.blob import blob_store

    def body(conn, log):
        loop = all_ or rebuild
        if rebuild:
            rebuild_all(conn)
        converter = None if no_convert else get_converter()
        total = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
        while True:
            st = process_once(conn, blob_store(), limit=limit, converter=converter)
            for k in total:
                total[k] += st[k]
            if not loop or st["claimed"] == 0 or st["ok"] == 0:
                return total
    run_id, stats = run_logged("process", None, body)
    typer.echo(f"완료 (run {run_id}): {stats}")

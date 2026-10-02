# src/reg/core/annex_cli.py
"""reg annex — 별표·별지 원문 이미지와 표 HTML (M6-6)."""
import json
from collections import Counter

import typer

annex = typer.Typer(no_args_is_help=True, help="별표·별지 원문 이미지·표")


@annex.command("render")
def render_cmd(version: str = typer.Option(None, help="이 판본만"),
               limit: int = typer.Option(500, help="현행 판본 수 상한")) -> None:
    """별표 영역을 PNG로 그려 보관소에 둔다 (실서버에서는 nice -n 19)."""
    if version:
        from reg.core.annex import ensure_rendered
        from reg.platform.runs import open_conn
        from reg.platform.storage.blob import blob_store

        with open_conn() as conn:
            man = ensure_rendered(conn, blob_store(), version)
        typer.echo(json.dumps({p: len(it["segments"]) for p, it in man["items"].items()}, ensure_ascii=False))
        return
    from reg.core.annex_tasks import render_current

    typer.echo(json.dumps(render_current(limit), ensure_ascii=False))


@annex.command("status")
def status_cmd(limit: int = typer.Option(2000)) -> None:
    """현행 판본 별표의 이미지·표 상태 요약 (매니페스트 기준)."""
    from reg.core.annex import load_manifest, version_order
    from reg.core.annex_tasks import current_versions
    from reg.platform.runs import open_conn
    from reg.platform.storage.blob import blob_store

    blob, c = blob_store(), Counter()
    with open_conn() as conn:
        for vid in current_versions(conn, limit):
            sd, _ = version_order(conn, vid)
            man = load_manifest(blob, sd["sha256"])
            c["versions"] += 1
            c["rendered_versions"] += man.get("digest") is not None
            for it in man.get("items", {}).values():
                c["annexes"] += 1
                c[f"table:{it.get('table', {}).get('status', 'none')}"] += 1
    typer.echo(json.dumps(dict(c), ensure_ascii=False))


@annex.command("tables")
def tables_cmd(version: str = typer.Option(None, help="이 판본만"),
               limit: int = typer.Option(50, help="이번 실행에서 처리할 판본 수")) -> None:
    """별표 표를 MinerU(GPU PC)로 HTML로 바꾼다. REG_MINERU_URL이 없으면 아무것도 하지 않는다."""
    if version:
        from reg.core.annex_mineru import mineru_source
        from reg.core.annex_tables import convert_version
        from reg.platform.runs import open_conn
        from reg.platform.storage.blob import blob_store

        source = mineru_source()
        if source is None:
            typer.echo("REG_MINERU_URL이 비어 있어 건너뜀")
            return
        with open_conn() as conn:
            typer.echo(json.dumps(convert_version(conn, blob_store(), version, source), ensure_ascii=False))
        return
    from reg.core.annex_tasks import convert_tables

    typer.echo(json.dumps(convert_tables(limit), ensure_ascii=False))

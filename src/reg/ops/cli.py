"""reg ops: Airflow 없이도 하루 요약·정리 작업을 손으로 돌린다 (spec §9 수동 실행)."""
import json

import typer

from reg.ops import tasks

app = typer.Typer(help="운영: 하루 요약, 정리 작업", no_args_is_help=True)


def _print(d: dict) -> None:
    typer.echo(json.dumps(d, ensure_ascii=False, indent=2, default=str))


@app.command("summary")
def summary(day: str = typer.Option(None, help="YYYY-MM-DD (기본: 오늘, KST)")) -> None:
    _print(tasks.daily_summary(day))


@app.command("maintenance")
def maintenance() -> None:
    _print(tasks.maintenance())

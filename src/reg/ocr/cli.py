"""reg ocr run | enqueue-low-text | status"""
import json

import typer

from reg.platform.mineru import mineru_available
from reg.platform.runs import open_conn

ocr = typer.Typer(no_args_is_help=True, help="OCR: 글자 층이 없거나 깨진 PDF를 GPU PC의 MinerU로 다시 읽는다")


def _echo(d: dict) -> None:
    typer.echo(json.dumps(d, ensure_ascii=False))


@ocr.command("run")
def run_cmd(limit: int = typer.Option(50, help="한 번에 처리할 OCR 요청 수"),
            all_: bool = typer.Option(False, "--all", help="대기 요청이 없거나 GPU PC가 꺼질 때까지 반복")) -> None:
    from reg.ocr.tasks import run_pending

    total: dict = {}
    tried: list[int] = []  # 반복 사이에도 한 이벤트는 한 번만 시도한다
    while True:
        st = run_pending(limit, tried=tried)
        for k, v in st.items():
            total[k] = (total.get(k, False) or v) if isinstance(v, bool) else total.get(k, 0) + v
        if not all_ or st["claimed"] == 0 or st["unavailable"]:
            break
    _echo(total)


@ocr.command("enqueue-low-text")
def enqueue_cmd(dry_run: bool = typer.Option(False, "--dry-run", help="판정만 하고 쓰지 않는다")) -> None:
    from reg.ocr.service import enqueue_low_text
    from reg.platform.settings import get_settings
    from reg.platform.storage.blob import blob_store

    with open_conn() as conn:
        _echo(enqueue_low_text(conn, blob_store(get_settings()), dry_run=dry_run))


@ocr.command("status")
def status_cmd() -> None:
    from reg.ocr.service import status
    from reg.platform.settings import get_settings

    s = get_settings()
    with open_conn() as conn:
        _echo({**status(conn), "mineru_available": mineru_available(s.mineru_url, s.mineru_api_key)})

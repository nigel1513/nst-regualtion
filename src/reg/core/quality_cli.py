# src/reg/core/quality_cli.py
"""reg quality — 추출·파싱·참조 품질 지표 (M6-6)."""
import csv
import json
import sys
from pathlib import Path

import typer

quality = typer.Typer(no_args_is_help=True, help="추출·파싱·참조 품질 지표")
LEXICON = Path(__file__).parent / "data" / "lexicon.tsv.gz"


@quality.command("report")
def report_cmd(scope: str = typer.Option("current", help="current | all"),
               offline: bool = typer.Option(False, "--offline", help="보관소 원본을 지금 코드로 다시 파싱해서 잰다 (DB에 쓰지 않음)"),
               limit: int = typer.Option(None, help="--offline 판본 수 상한 (시험용)"),
               out: Path = typer.Option(None, help="결과 JSON 저장 경로"),
               baseline: Path = typer.Option(None, help="비교할 이전 JSON. 나빠진 지표가 있으면 종료 코드 1")) -> None:
    """실서버에서는 nice -n 19로 돌린다 (단일 프로세스)."""
    from reg.core import quality_report as Q
    from reg.platform.runs import open_conn
    from reg.platform.storage.blob import blob_store

    with open_conn() as conn:
        r = Q.offline(conn, blob_store(), scope, limit) if offline else Q.report(conn, scope)
    if out:
        out.write_text(Q.dump(r), encoding="utf-8")
    before = json.loads(baseline.read_text(encoding="utf-8")) if baseline else None
    typer.echo(Q.to_markdown(before, r))
    if before:
        worse = Q.compare(before, r)
        for k, b, a in worse:
            typer.echo(f"나빠짐: {k} {b} → {a}")
        if worse:
            raise typer.Exit(1)


@quality.command("build-lexicon")
def build_lexicon_cmd(out: Path = typer.Option(LEXICON, help="사전 파일"),
                      min_count: int = typer.Option(3, help="이 횟수 이상 나온 어절만")) -> None:
    """HWP 원문 본문 어절로 줄 잇기 사전을 만든다 (DB 읽기만)."""
    from reg.core.quality_report import build_lexicon
    from reg.platform.runs import open_conn

    with open_conn() as conn:
        data = build_lexicon(conn, min_count)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    typer.echo(f"{out}: {len(data)} bytes")


@quality.command("refs-sample")
def refs_sample_cmd(n: int = typer.Option(100), seed: float = typer.Option(0.42),
                    out: Path = typer.Option(None, help="TSV 저장 경로 (없으면 표준 출력)")) -> None:
    """현행 참조 무작위 표본을 판정용 TSV로 낸다. 마지막 열 judge(ok/wrong)는 사람이 채운다."""
    from reg.core.quality_report import refs_sample
    from reg.platform.runs import open_conn

    with open_conn() as conn:
        rows = refs_sample(conn, n, seed)
    f = out.open("w", encoding="utf-8", newline="") if out else sys.stdout
    w = csv.writer(f, delimiter="\t")
    cols = ["id", "work_id", "path", "context", "evidence_text", "rel_type", "target_kind", "target_work_id",
            "target_path", "target_name", "resolution", "extractor"]
    w.writerow([*cols, "judge"])
    for r in rows:
        w.writerow([*(str(r[c]).replace("\n", " ") if r[c] is not None else "" for c in cols), ""])
    if out:
        f.close()

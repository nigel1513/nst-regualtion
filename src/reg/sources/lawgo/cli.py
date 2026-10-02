"""reg law … — law.go.kr 법령 수집 (M6-1에서 미러로 확장)."""
import typer

law = typer.Typer(no_args_is_help=True, help="law.go.kr 법령")


@law.command("collect")
def collect() -> None:
    from reg.platform.http import PoliteClient
    from reg.platform.runs import run_logged
    from reg.platform.settings import get_settings
    from reg.platform.storage.blob import blob_store
    from reg.sources.lawgo.client import LawGoClient
    from reg.sources.lawgo.config import load_config
    from reg.sources.lawgo.sync import sync_laws

    def body(conn, log):
        s = get_settings()
        client = LawGoClient(PoliteClient("lawgo", s.lawgo_min_interval, log=log), oc=s.lawgo_oc)
        names = list(load_config().promote_laws)
        names += [r["name"] for r in conn.execute("SELECT name FROM regulation.law_seed ORDER BY name").fetchall()
                  if r["name"] not in names]  # 참조에서 발견된 법령 (spec 6.1)
        return sync_laws(conn, client, blob_store(), names)
    run_id, stats = run_logged("lawgo", None, body)
    typer.echo(f"완료 (run {run_id}): {stats}")

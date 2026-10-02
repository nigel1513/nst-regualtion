# scripts/m6_restructure.py
"""M6-0: 파일을 새 패키지 배치로 옮기고 점 경로(import·문자열)를 모두 바꾼다. 한 번만 실행한다."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "src/reg"
MOVES = [  # (옛 파일, 새 파일)
    ("settings.py", "platform/settings.py"), ("outbox.py", "platform/outbox.py"),
    ("db/bootstrap.py", "platform/db/bootstrap.py"), ("db/conn.py", "platform/db/conn.py"),
    ("db/migrate.py", "platform/db/migrate.py"), ("storage/blob.py", "platform/storage/blob.py"),
    ("collect/polite.py", "platform/http.py"), ("collect/runs.py", "platform/runs.py"),
    ("collect/sniff.py", "platform/sniff.py"), ("collect/archive.py", "platform/archive.py"),
    ("views/converter.py", "platform/convert.py"), ("llm.py", "platform/llm.py"),
    ("structure/model.py", "core/model.py"), ("structure/text.py", "core/text.py"),
    ("structure/parse.py", "core/parse.py"), ("structure/effective.py", "core/effective.py"),
    ("extract/__init__.py", "core/extract/__init__.py"), ("extract/hwp.py", "core/extract/hwp.py"),
    ("extract/hwpx.py", "core/extract/hwpx.py"), ("extract/pdf.py", "core/extract/pdf.py"),
    ("views/anchor.py", "core/anchor.py"), ("load/loader.py", "core/ingest/loader.py"),
    ("process.py", "core/ingest/process.py"), ("refs.py", "core/refs.py"), ("quality.py", "core/quality.py"),
    ("collect/alio.py", "sources/alio/client.py"), ("collect/alio_sync.py", "sources/alio/sync.py"),
    ("collect/lawgo.py", "sources/lawgo/client.py"), ("collect/law_sync.py", "sources/lawgo/sync.py"),
    ("structure/law_xml.py", "sources/lawgo/xml.py"),
    ("search/chunks.py", "index/chunks.py"), ("search/indexer.py", "index/indexer.py"),
    ("search/mapping.py", "index/mapping.py"), ("search/os.py", "index/os.py"),
    ("search/service.py", "index/service.py"), ("evaluate.py", "qa/evaluate.py"),
]
DIRS = [("migrations", "core/migrations")]
# 점 경로 치환 (긴 것부터)
PATHS = {
    "reg.collect.alio_sync": "reg.sources.alio.sync", "reg.collect.alio": "reg.sources.alio.client",
    "reg.collect.law_sync": "reg.sources.lawgo.sync", "reg.collect.lawgo": "reg.sources.lawgo.client",
    "reg.collect.polite": "reg.platform.http", "reg.collect.runs": "reg.platform.runs",
    "reg.collect.sniff": "reg.platform.sniff", "reg.collect.archive": "reg.platform.archive",
    "reg.structure.law_xml": "reg.sources.lawgo.xml", "reg.structure.model": "reg.core.model",
    "reg.structure.text": "reg.core.text", "reg.structure.parse": "reg.core.parse",
    "reg.structure.effective": "reg.core.effective", "reg.views.converter": "reg.platform.convert",
    "reg.views.anchor": "reg.core.anchor", "reg.load.loader": "reg.core.ingest.loader",
    "reg.storage.blob": "reg.platform.storage.blob", "reg.db.bootstrap": "reg.platform.db.bootstrap",
    "reg.db.conn": "reg.platform.db.conn", "reg.db.migrate": "reg.platform.db.migrate",
    "reg.extract": "reg.core.extract", "reg.search": "reg.index", "reg.process": "reg.core.ingest.process",
    "reg.refs": "reg.core.refs", "reg.quality": "reg.core.quality", "reg.settings": "reg.platform.settings",
    "reg.outbox": "reg.platform.outbox", "reg.llm": "reg.platform.llm", "reg.evaluate": "reg.qa.evaluate",
}
FROM_REG = {"outbox": "reg.platform", "evaluate": "reg.qa", "process": "reg.core.ingest"}  # from reg import outbox / evaluate


def git(*a):
    subprocess.run(["git", "-C", str(ROOT), *a], check=True)


def main():
    for old, new in MOVES:
        (S / new).parent.mkdir(parents=True, exist_ok=True)
        git("mv", str(S / old), str(S / new))
    for old, new in DIRS:
        (S / new).parent.mkdir(parents=True, exist_ok=True)
        git("mv", str(S / old), str(S / new))
    for d in ["platform", "platform/db", "platform/storage", "core", "core/ingest", "sources", "sources/alio",
              "sources/lawgo", "index"]:
        init = S / d / "__init__.py"
        if not init.exists():
            init.write_text("")
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(PATHS, key=len, reverse=True)) + r")\b")
    for f in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        if f.name == "m6_restructure.py":
            continue
        t = f.read_text(encoding="utf-8")
        n = pat.sub(lambda m: PATHS[m[1]], t)
        for name, pkg in FROM_REG.items():
            n = re.sub(rf"^(\s*)from reg import {name}\b", rf"\1from {pkg} import {name}", n, flags=re.M)
        if n != t:
            f.write_text(n, encoding="utf-8")
    for leftover in ["collect", "structure", "load", "views", "search", "extract", "storage", "db"]:
        p = S / leftover
        if p.exists():
            for x in p.glob("__init__.py"):
                git("rm", "-q", str(x))
            if p.exists() and not any(p.iterdir()):
                p.rmdir()
    ini = ROOT / "alembic.ini"
    ini.write_text(ini.read_text().replace("src/reg/migrations", "src/reg/core/migrations"))


if __name__ == "__main__":
    main()

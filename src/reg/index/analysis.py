"""검색 분석기 설정 파일 (M7 spec §2.1): config/search_synonyms.txt, config/search_userdict.txt.
OpenSearch 노드에 파일을 둘 수 없으므로(전용 클러스터는 GPU PC) 색인 생성 때 규칙을 인라인으로 보낸다."""
from pathlib import Path

from reg.platform.settings import ROOT

SYNONYMS = ROOT / "config/search_synonyms.txt"
USERDICT = ROOT / "config/search_userdict.txt"


def _rules(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = (x.strip() for x in path.read_text(encoding="utf-8").splitlines())
    return list(dict.fromkeys(x for x in lines if x and not x.startswith("#")))


def load() -> tuple[list[str], list[str]]:
    """(동의어 규칙, 사용자 사전 규칙)."""
    return _rules(SYNONYMS), _rules(USERDICT)

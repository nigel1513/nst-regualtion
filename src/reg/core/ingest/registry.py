"""출처 처리기 등록부. core는 출처 모듈을 import하지 않고, 앱 계층(reg.wiring)이 여기에 등록한다."""
from reg.core.ingest.contract import SourceHandler

_HANDLERS: dict[str, SourceHandler] = {}


def register(h: SourceHandler) -> None:
    _HANDLERS[h.topic] = h


def handlers() -> dict[str, SourceHandler]:
    return dict(_HANDLERS)


def clear() -> None:
    _HANDLERS.clear()

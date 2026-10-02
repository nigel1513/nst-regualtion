"""출처 모듈 ↔ core 계약 (overview §2.3). 출처는 '적재할 판본 하나'를 만들어 넘기고, 적재는 core가 한다."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from reg.core.effective import Effective
from reg.core.model import ParsedDoc


@dataclass
class PreparedVersion:
    work_id: str
    work_kind: str
    title: str
    institution_id: int | None
    source_document_id: int
    doc: ParsedDoc
    effective: Effective
    external_ids: dict = field(default_factory=dict)
    posted_on: date | None = None


@dataclass
class SourceHandler:
    topic: str
    group_field: str
    prepare: Callable[..., PreparedVersion | None]  # (conn, blob, payload, today, converter)

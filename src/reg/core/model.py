from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Block:
    text: str
    page: int | None = None
    bbox: tuple | None = None


@dataclass
class Prov:
    path: str
    unit: str  # chapter|section|article|paragraph|item|subitem|supplement|supp_article|annex
    label: str
    heading: str | None = None
    text: str = ""
    parent: str | None = None
    annotations: list[str] = field(default_factory=list)
    deleted: bool = False
    effective_override: date | None = None
    anchor: dict | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class HistEntry:
    kind: str
    date: date
    number: str | None = None


@dataclass
class ParsedDoc:
    title: str
    class_code: str | None
    history: list[HistEntry]
    provisions: list[Prov]
    meta: dict = field(default_factory=dict)

    def get(self, path: str) -> Prov | None:
        return next((p for p in self.provisions if p.path == path), None)

    def children(self, path: str) -> list[Prov]:
        return [p for p in self.provisions if p.parent == path]

    def supplements(self) -> list[Prov]:
        return [p for p in self.provisions if p.unit == "supplement"]

    def to_json(self) -> dict:
        d = asdict(self)
        for h in d["history"]:
            h["date"] = h["date"].isoformat()
        for p in d["provisions"]:
            if p["effective_override"]:
                p["effective_override"] = p["effective_override"].isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> "ParsedDoc":
        hist = [HistEntry(h["kind"], date.fromisoformat(h["date"]), h["number"]) for h in d["history"]]
        provs = []
        for p in d["provisions"]:
            p = dict(p)
            if p["effective_override"]:
                p["effective_override"] = date.fromisoformat(p["effective_override"])
            provs.append(Prov(**p))
        return cls(d["title"], d["class_code"], hist, provs, d.get("meta", {}))

"""식별자 규칙: law_master.law_id와 승격 work id."""


def master_id(family: str, source_id: str) -> str:
    return source_id if family == "law" else f"admrul:{source_id}"


def family_of(law_id: str) -> str:
    return "admrul" if law_id.startswith("admrul:") else "law"


def work_id_for(law_id: str) -> str:
    return f"kr/admrul/{law_id.split(':', 1)[1]}" if family_of(law_id) == "admrul" else f"kr/law/{law_id}"

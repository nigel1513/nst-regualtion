import re

PII = [re.compile(r"\d{6}\s*-?\s*[1-4]\d{6}"), re.compile(r"01\d\s*-?\s*\d{3,4}\s*-?\s*\d{4}"),
       re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")]


def mask_pii(text: str) -> str:
    for rx in PII:
        text = rx.sub("[개인정보]", text)
    return text

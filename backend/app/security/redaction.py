import re

_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_KEY_VALUE = re.compile(r'(?i)(api[_-]?key["\s:=]+)[^\s",}]+')
_DATA_URI = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")


def redact(value: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", value)
    value = _KEY_VALUE.sub(r"\1[REDACTED]", value)
    return _DATA_URI.sub("data:image/[REDACTED]", value)


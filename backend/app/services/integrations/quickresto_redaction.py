from __future__ import annotations

import hashlib
import re
from typing import Any


STRUCTURED_DETAIL_REDACTED = "[structured detail redacted]"

_DEFAULT_MAX_SUMMARY_LENGTH = 500
_MAX_CORRELATION_ID_LENGTH = 128
_CONTROL_CHARACTERS_RE = re.compile(r"[\x00-\x1f\x7f]+")
_URL_CREDENTIALS_RE = re.compile(r"(?i)\b(https?://)[^\s/@:]+:[^\s/@]+@")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_AUTHORIZATION_VALUE_RE = re.compile(r"(?i)(\bauthorization\b\s*[:=]\s*)(?:basic\s+|bearer\s+)?[^\s,;]+")
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?(?:login|password|key)|access[_-]?token|refresh[_-]?token|login|password|passwd|"
    r"secret|token|credential|guest(?:name)?|customer|phone|email|employee|comment|table)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&}\]]+)"
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:api[_-]?(?:login|password|key)|access[_-]?token|refresh[_-]?token|login|password|"
    r"passwd|secret|token|authorization|phone|email)=)[^&#\s]*"
)
_STRUCTURED_DETAIL_KEYS_RE = re.compile(
    r"(?i)[\"'](?:orders?|payments?|shiftId|orderItemList|api_login|api_password|credentials?|guest(?:Name)?|"
    r"customer|phone|email|employee|comment|table)[\"']\s*:"
)
_EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}(?![\w.-])")
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)")
_CORRELATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_EXCEPTION_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def redact_quickresto_technical_summary(
    value: Any,
    *,
    max_length: int = _DEFAULT_MAX_SUMMARY_LENGTH,
) -> str | None:
    """Return a bounded diagnostic string without credentials or source PII."""

    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return STRUCTURED_DETAIL_REDACTED

    text = " ".join(_CONTROL_CHARACTERS_RE.sub(" ", str(value)).split()).strip()
    if not text:
        return None
    if _STRUCTURED_DETAIL_KEYS_RE.search(text):
        return STRUCTURED_DETAIL_REDACTED

    text = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", text)
    text = _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", text)
    text = _AUTHORIZATION_VALUE_RE.sub(r"\1[REDACTED]", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)
    text = _SENSITIVE_QUERY_RE.sub(r"\1[REDACTED]", text)
    text = _EMAIL_RE.sub("[PII REDACTED]", text)
    text = _PHONE_RE.sub("[PII REDACTED]", text)
    return text[: max(int(max_length), 1)] or None


def generic_quickresto_exception_summary(exc: BaseException) -> str:
    """Describe an unexpected defect without persisting its potentially unsafe message."""

    exception_name = _EXCEPTION_NAME_RE.sub("", type(exc).__name__)[:80] or "UnexpectedError"
    return f"{exception_name}: unexpected QuickResto import failure"


def redact_quickresto_correlation_id(value: Any) -> str | None:
    raw = " ".join(_CONTROL_CHARACTERS_RE.sub(" ", str(value or "")).split()).strip()
    if not raw:
        return None
    if len(raw) <= _MAX_CORRELATION_ID_LENGTH and _CORRELATION_ID_RE.fullmatch(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"redacted-{digest}"

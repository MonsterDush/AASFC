from __future__ import annotations

from enum import Enum
import re


class ProviderErrorCode(str, Enum):
    AUTHENTICATION = "AUTHENTICATION"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARY = "TEMPORARY"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class ProviderError(RuntimeError):
    code = ProviderErrorCode.TEMPORARY
    retryable = False

    def __init__(self, message: str = "Provider request failed") -> None:
        raw_message = str(message or "Provider request failed")
        safe_message = re.sub(
            r"(?i)\b(authorization|password|token|secret|api[_-]?key)\b\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]",
            raw_message,
        )
        safe_message = re.sub(r"([?&][^=\s]+)=([^&\s]+)", r"\1=[REDACTED]", safe_message)
        self.safe_message = safe_message
        super().__init__(self.safe_message)


class ProviderAuthenticationError(ProviderError):
    code = ProviderErrorCode.AUTHENTICATION


class ProviderCapabilityError(ProviderError):
    code = ProviderErrorCode.CAPABILITY_UNAVAILABLE


class ProviderRateLimitError(ProviderError):
    code = ProviderErrorCode.RATE_LIMITED
    retryable = True


class ProviderTemporaryError(ProviderError):
    code = ProviderErrorCode.TEMPORARY
    retryable = True


class ProviderValidationError(ProviderError):
    code = ProviderErrorCode.INVALID_RESPONSE

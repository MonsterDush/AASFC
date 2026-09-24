from __future__ import annotations

import base64
import hashlib

from app.core.config import settings


class IntegrationCredentialError(RuntimeError):
    """Raised when stored integration credentials cannot be encrypted or decrypted."""


def _configured_key_material() -> bytes:
    configured = str(settings.INTEGRATION_ENCRYPTION_KEY or settings.JWT_SECRET or "")
    if len(configured.encode("utf-8")) < 32:
        raise IntegrationCredentialError("Integration encryption key material is too short")
    return configured.encode("utf-8")


def _fernet_for_domain(domain: bytes):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise IntegrationCredentialError("Integration credential encryption is unavailable") from exc

    digest = hashlib.sha256(domain + b"\x00" + _configured_key_material()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet():
    # Keep the original derivation domain stable for credentials that already
    # exist in production.
    return _fernet_for_domain(b"axelio:integration-credentials:v1")


def _payload_fernet():
    return _fernet_for_domain(b"axelio:integration-source-snapshots:v1")


def _raw_payload_fernet():
    # Canonical raw objects have their own cryptographic domain. Rotating or
    # invalidating source-snapshot storage must not affect credentials or raw.
    return _fernet_for_domain(b"axelio:integration-raw-payloads:v1")


def _command_payload_fernet():
    return _fernet_for_domain(b"axelio:integration-command-payloads:v1")


def _event_payload_fernet():
    return _fernet_for_domain(b"axelio:integration-event-payloads:v1")


def _operational_payload_fernet():
    return _fernet_for_domain(b"axelio:integration-operational-payloads:v1")


def encrypt_credential(value: str) -> str:
    plaintext = str(value or "")
    if not plaintext:
        raise IntegrationCredentialError("Integration credential cannot be empty")
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"v1:{token}"


def decrypt_credential(value: str) -> str:
    stored = str(value or "")
    if not stored.startswith("v1:"):
        raise IntegrationCredentialError("Integration credential has an unsupported format")
    try:
        plaintext = _fernet().decrypt(stored[3:].encode("ascii"))
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise IntegrationCredentialError("Integration credential could not be decrypted") from exc


def encrypt_integration_payload(value: str) -> str:
    plaintext = str(value or "")
    if not plaintext:
        raise IntegrationCredentialError("Integration source snapshot cannot be empty")
    token = _payload_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"v1:{token}"


def decrypt_integration_payload(value: str) -> str:
    stored = str(value or "")
    if not stored.startswith("v1:"):
        raise IntegrationCredentialError("Integration source snapshot has an unsupported format")
    try:
        plaintext = _payload_fernet().decrypt(stored[3:].encode("ascii"))
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise IntegrationCredentialError("Integration source snapshot could not be decrypted") from exc


def encrypt_raw_integration_payload(value: str) -> str:
    plaintext = str(value or "")
    if not plaintext:
        raise IntegrationCredentialError("Integration raw payload cannot be empty")
    token = _raw_payload_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"v1:{token}"


def decrypt_raw_integration_payload(value: str) -> str:
    stored = str(value or "")
    if not stored.startswith("v1:"):
        raise IntegrationCredentialError("Integration raw payload has an unsupported format")
    try:
        plaintext = _raw_payload_fernet().decrypt(stored[3:].encode("ascii"))
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise IntegrationCredentialError("Integration raw payload could not be decrypted") from exc


def _encrypt_domain_payload(value: str, *, label: str, fernet) -> str:
    plaintext = str(value or "")
    if not plaintext:
        raise IntegrationCredentialError(f"Integration {label} payload cannot be empty")
    return f"v1:{fernet().encrypt(plaintext.encode('utf-8')).decode('ascii')}"


def _decrypt_domain_payload(value: str, *, label: str, fernet) -> str:
    stored = str(value or "")
    if not stored.startswith("v1:"):
        raise IntegrationCredentialError(f"Integration {label} payload has an unsupported format")
    try:
        return fernet().decrypt(stored[3:].encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise IntegrationCredentialError(f"Integration {label} payload could not be decrypted") from exc


def encrypt_command_payload(value: str) -> str:
    return _encrypt_domain_payload(value, label="command", fernet=_command_payload_fernet)


def decrypt_command_payload(value: str) -> str:
    return _decrypt_domain_payload(value, label="command", fernet=_command_payload_fernet)


def encrypt_event_payload(value: str) -> str:
    return _encrypt_domain_payload(value, label="event", fernet=_event_payload_fernet)


def decrypt_event_payload(value: str) -> str:
    return _decrypt_domain_payload(value, label="event", fernet=_event_payload_fernet)


def encrypt_operational_payload(value: str) -> str:
    return _encrypt_domain_payload(value, label="operational", fernet=_operational_payload_fernet)


def decrypt_operational_payload(value: str) -> str:
    return _decrypt_domain_payload(value, label="operational", fernet=_operational_payload_fernet)

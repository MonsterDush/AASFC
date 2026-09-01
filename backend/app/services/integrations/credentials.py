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

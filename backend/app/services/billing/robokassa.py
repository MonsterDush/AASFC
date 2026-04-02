from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import hashlib
import hmac
from typing import Mapping
from urllib.parse import urlencode
import logging
logger = logging.getLogger(__name__)
from app.core.config import settings


_SUPPORTED_HASHES = {
    "MD5": "md5",
    "SHA1": "sha1",
    "SHA256": "sha256",
    "SHA384": "sha384",
    "SHA512": "sha512",
}


@dataclass(slots=True)
class RobokassaConfig:
    merchant_login: str
    password1: str
    password2: str
    test_mode: bool
    hash_algorithm: str
    payment_url: str
    result_url: str
    success_url: str
    fail_url: str

    @property
    def is_enabled(self) -> bool:
        return bool(self.merchant_login and self.password1 and self.password2)


def _normalize_hash_algorithm(value: str | None) -> str:
    raw = str(value or "MD5").strip().upper()
    return raw if raw in _SUPPORTED_HASHES else "MD5"


def get_robokassa_config() -> RobokassaConfig:
    api_base = settings.api_base_url()
    test_mode = bool(settings.ROBOKASSA_TEST_MODE)
    password1 = settings.ROBOKASSA_TEST_PASSWORD1 if test_mode and settings.ROBOKASSA_TEST_PASSWORD1 else settings.ROBOKASSA_PASSWORD1
    password2 = settings.ROBOKASSA_TEST_PASSWORD2 if test_mode and settings.ROBOKASSA_TEST_PASSWORD2 else settings.ROBOKASSA_PASSWORD2
    payment_url = (settings.ROBOKASSA_PAYMENT_URL or "").strip() or "https://auth.robokassa.ru/Merchant/Index.aspx"
    return RobokassaConfig(
        merchant_login=(settings.ROBOKASSA_MERCHANT_LOGIN or "").strip(),
        password1=(password1 or "").strip(),
        password2=(password2 or "").strip(),
        test_mode=test_mode,
        hash_algorithm=_normalize_hash_algorithm(settings.ROBOKASSA_HASH_ALGORITHM),
        payment_url=payment_url.rstrip("?"),
        result_url=f"{api_base}/billing/robokassa/result",
        success_url=f"{api_base}/billing/robokassa/success",
        fail_url=f"{api_base}/billing/robokassa/fail",
    )


def format_out_sum(amount_minor: int, *, test_mode: bool) -> str:
    amount_minor_int = max(0, int(amount_minor or 0))
    amount_rub = (Decimal(amount_minor_int) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(amount_rub, "f")


def _hash_value(payload: str, *, algorithm: str) -> str:
    algo_name = _SUPPORTED_HASHES[_normalize_hash_algorithm(algorithm)]
    digest = hashlib.new(algo_name)
    digest.update(payload.encode("utf-8"))
    return digest.hexdigest()


def _sorted_shp_pairs(extra_params: Mapping[str, str] | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if not extra_params:
        return pairs
    for key, value in extra_params.items():
        key_str = str(key or "").strip()
        if not key_str:
            continue
        pairs.append((key_str, str(value or "")))
    pairs.sort(key=lambda item: item[0].lower())
    return pairs


_CHECKOUT_MODIFIER_ORDER = (
    "Receipt",
    "StepByStep",
    "ResultUrl2",
    "SuccessUrl2",
    "SuccessUrl2Method",
    "FailUrl2",
    "FailUrl2Method",
    "Token",
)


def _ordered_modifier_values(modifiers: Mapping[str, str] | None) -> list[str]:
    if not modifiers:
        return []
    values: list[str] = []
    for key in _CHECKOUT_MODIFIER_ORDER:
        raw = modifiers.get(key) if isinstance(modifiers, Mapping) else None
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        values.append(text)
    return values


def calculate_checkout_signature(
    *,
    merchant_login: str,
    out_sum: str,
    invoice_id: str,
    password1: str,
    algorithm: str,
    modifiers: Mapping[str, str] | None = None,
    extra_params: Mapping[str, str] | None = None,
) -> str:
    invoice_slot = str(invoice_id or "")
    base = f"{merchant_login}:{out_sum}:{invoice_slot}"
    for value in _ordered_modifier_values(modifiers):
        base += f":{value}"
    base += f":{password1}"
    for key, value in _sorted_shp_pairs(extra_params):
        base += f":{key}={value}"
    logger.warning("ROBOKASSA BASE STRING: %s", base)
    logger.warning("ROBOKASSA SIGNATURE : %s", _hash_value(base, algorithm=algorithm))
    return _hash_value(base, algorithm=algorithm)


def calculate_result_signature(
    *,
    out_sum: str,
    invoice_id: str,
    password2: str,
    algorithm: str,
    extra_params: Mapping[str, str] | None = None,
) -> str:
    base = f"{out_sum}:{invoice_id}:{password2}"
    for key, value in _sorted_shp_pairs(extra_params):
        base += f":{key}={value}"
    return _hash_value(base, algorithm=algorithm)


def is_valid_result_signature(
    *,
    out_sum: str,
    invoice_id: str,
    received_signature: str | None,
    password2: str,
    algorithm: str,
    extra_params: Mapping[str, str] | None = None,
) -> bool:
    expected = calculate_result_signature(
        out_sum=out_sum,
        invoice_id=invoice_id,
        password2=password2,
        algorithm=algorithm,
        extra_params=extra_params,
    )
    return hmac.compare_digest(expected.lower(), str(received_signature or "").strip().lower())


def is_valid_success_signature(
    *,
    out_sum: str,
    invoice_id: str,
    received_signature: str | None,
    password1: str,
    algorithm: str,
    extra_params: Mapping[str, str] | None = None,
) -> bool:
    expected = calculate_result_signature(
        out_sum=out_sum,
        invoice_id=invoice_id,
        password2=password1,
        algorithm=algorithm,
        extra_params=extra_params,
    )
    return hmac.compare_digest(expected.lower(), str(received_signature or "").strip().lower())


def _format_expiration_date(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        return raw or None
    return value.strftime("%Y-%m-%dT%H:%M")


def build_checkout_url(
    *,
    merchant_login: str,
    out_sum: str,
    invoice_id: str,
    description: str,
    password1: str,
    algorithm: str,
    payment_url: str,
    result_url: str,
    success_url: str,
    fail_url: str,
    extra_params: Mapping[str, str] | None = None,
    test_mode: bool = False,
    culture: str = "ru",
    expiration_date: datetime | str | None = None,
    use_return_url2: bool = False,
) -> str:
    signature = calculate_checkout_signature(
        merchant_login=merchant_login,
        out_sum=out_sum,
        invoice_id=invoice_id,
        password1=password1,
        algorithm=algorithm,
        modifiers=None,
        extra_params=None,
    )
    params: list[tuple[str, str]] = [
        ("MerchantLogin", merchant_login),
        ("OutSum", out_sum),
        ("InvId", invoice_id),
        ("Description", description),
        ("SignatureValue", signature),
    ]
    if test_mode:
        params.append(("IsTest", "1"))
    return f"{payment_url}?{urlencode(params)}"

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Mapping
from urllib.parse import urlencode

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
    pending_timeout_minutes: int

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
        pending_timeout_minutes=max(5, int(getattr(settings, 'ROBOKASSA_PENDING_TIMEOUT_MINUTES', 180) or 180)),
    )


def format_out_sum(amount_minor: int, *, test_mode: bool) -> str:
    amount_minor_int = max(0, int(amount_minor or 0))
    amount_rub = (Decimal(amount_minor_int) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if test_mode:
        if amount_rub == amount_rub.to_integral_value():
            return str(int(amount_rub))
        return format(amount_rub, "f")
    return format(amount_rub.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def format_expiration_date(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    value = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M")


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


def _checkout_modifiers(
    *,
    receipt: str | None = None,
    step_by_step: bool = False,
    result_url2: str | None = None,
    success_url2: str | None = None,
    success_url2_method: str | None = None,
    fail_url2: str | None = None,
    fail_url2_method: str | None = None,
    token: str | None = None,
) -> list[str]:
    modifiers: list[str] = []
    if receipt:
        modifiers.append(str(receipt))
    if step_by_step:
        modifiers.append("true")
    if result_url2:
        modifiers.append(str(result_url2))
    if success_url2:
        modifiers.append(str(success_url2))
    if success_url2_method:
        modifiers.append(str(success_url2_method).upper())
    if fail_url2:
        modifiers.append(str(fail_url2))
    if fail_url2_method:
        modifiers.append(str(fail_url2_method).upper())
    if token:
        modifiers.append(str(token))
    return modifiers


def calculate_checkout_signature(
    *,
    merchant_login: str,
    out_sum: str,
    invoice_id: str,
    password1: str,
    algorithm: str,
    extra_params: Mapping[str, str] | None = None,
    receipt: str | None = None,
    step_by_step: bool = False,
    result_url2: str | None = None,
    success_url2: str | None = None,
    success_url2_method: str | None = None,
    fail_url2: str | None = None,
    fail_url2_method: str | None = None,
    token: str | None = None,
) -> str:
    parts = [merchant_login, out_sum, invoice_id]
    parts.extend(_checkout_modifiers(
        receipt=receipt,
        step_by_step=step_by_step,
        result_url2=result_url2,
        success_url2=success_url2,
        success_url2_method=success_url2_method,
        fail_url2=fail_url2,
        fail_url2_method=fail_url2_method,
        token=token,
    ))
    parts.append(password1)
    base = ":".join(parts)
    for key, value in _sorted_shp_pairs(extra_params):
        base += f":{key}={value}"
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
    receipt: str | None = None,
    step_by_step: bool = False,
    use_result_url2: bool = False,
    success_url2_method: str = "GET",
    fail_url2_method: str = "GET",
    expiration_date: str | None = None,
    token: str | None = None,
) -> str:
    shp_pairs = _sorted_shp_pairs(extra_params)
    result_url2 = result_url if use_result_url2 and result_url else None
    success_url2 = success_url or None
    fail_url2 = fail_url or None
    success_method = (success_url2_method or "GET").upper() if success_url2 else None
    fail_method = (fail_url2_method or "GET").upper() if fail_url2 else None
    signature = calculate_checkout_signature(
        merchant_login=merchant_login,
        out_sum=out_sum,
        invoice_id=invoice_id,
        password1=password1,
        algorithm=algorithm,
        extra_params=dict(shp_pairs),
        receipt=receipt,
        step_by_step=step_by_step,
        result_url2=result_url2,
        success_url2=success_url2,
        success_url2_method=success_method,
        fail_url2=fail_url2,
        fail_url2_method=fail_method,
        token=token,
    )
    params: list[tuple[str, str]] = [
        ("MerchantLogin", merchant_login),
        ("OutSum", out_sum),
        ("InvId", invoice_id),
        ("Description", description),
        ("SignatureValue", signature),
        ("Culture", culture or "ru"),
    ]
    if result_url2:
        params.append(("ResultUrl2", result_url2))
    if success_url2:
        params.append(("SuccessUrl2", success_url2))
        params.append(("SuccessUrl2Method", success_method or "GET"))
    if fail_url2:
        params.append(("FailUrl2", fail_url2))
        params.append(("FailUrl2Method", fail_method or "GET"))
    if expiration_date:
        params.append(("ExpirationDate", expiration_date))
    if receipt:
        params.append(("Receipt", receipt))
    if step_by_step:
        params.append(("StepByStep", "true"))
    if token:
        params.append(("Token", token))
    if test_mode:
        params.append(("IsTest", "1"))
    params.extend(shp_pairs)
    return f"{payment_url}?{urlencode(params)}"

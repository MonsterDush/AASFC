from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
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
    # Robokassa в текущей документации рекомендует передавать сумму с точностью
    # до двух знаков после запятой как в тестовом, так и в боевом режиме.
    return format(amount_rub, ".2f")


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


def calculate_checkout_signature(
    *,
    merchant_login: str,
    out_sum: str,
    invoice_id: str,
    password1: str,
    algorithm: str,
    receipt: str | None = None,
    step_by_step: str | None = None,
    result_url2: str | None = None,
    success_url2: str | None = None,
    success_url2_method: str | None = None,
    fail_url2: str | None = None,
    fail_url2_method: str | None = None,
    token: str | None = None,
    extra_params: Mapping[str, str] | None = None,
) -> str:
    parts = [merchant_login, out_sum, invoice_id]
    for value in [receipt, step_by_step, result_url2, success_url2, success_url2_method, fail_url2, fail_url2_method, token]:
        normalized = str(value or "")
        if normalized:
            parts.append(normalized)
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
) -> str:
    shp_pairs = _sorted_shp_pairs(extra_params)
    success_method = "GET"
    fail_method = "GET"
    signature = calculate_checkout_signature(
        merchant_login=merchant_login,
        out_sum=out_sum,
        invoice_id=invoice_id,
        password1=password1,
        algorithm=algorithm,
        success_url2=success_url,
        success_url2_method=success_method,
        fail_url2=fail_url,
        fail_url2_method=fail_method,
        extra_params=dict(shp_pairs),
    )
    params: list[tuple[str, str]] = [
        ("MerchantLogin", merchant_login),
        ("OutSum", out_sum),
        ("InvId", invoice_id),
        ("Description", description),
        ("SignatureValue", signature),
        ("Culture", culture or "ru"),
        # Основной ResultURL остаётся в настройках магазина; здесь задаём только
        # пользовательские обратные адреса второго уровня.
        ("SuccessUrl2", success_url),
        ("SuccessUrl2Method", success_method),
        ("FailUrl2", fail_url),
        ("FailUrl2Method", fail_method),
    ]
    expiration_value = _format_expiration_date(expiration_date)
    if expiration_value:
        params.append(("ExpirationDate", expiration_value))
    if test_mode:
        params.append(("IsTest", "1"))
    params.extend(shp_pairs)
    return f"{payment_url}?{urlencode(params)}"

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import html
import json
from typing import Mapping
from urllib.parse import quote, urlencode

from app.core.config import settings


_SUPPORTED_HASHES = {
    "MD5": "md5",
    "SHA1": "sha1",
    "SHA256": "sha256",
    "SHA384": "sha384",
    "SHA512": "sha512",
}

_SUPPORTED_RECEIPT_TAXES = {
    "none",
    "vat0",
    "vat5",
    "vat7",
    "vat10",
    "vat20",
    "vat22",
    "vat105",
    "vat107",
    "vat110",
    "vat120",
    "vat122",
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
    receipt_tax: str

    @property
    def is_enabled(self) -> bool:
        return bool(self.merchant_login and self.password1 and self.password2)


def _normalize_hash_algorithm(value: str | None) -> str:
    raw = str(value or "MD5").strip().upper()
    return raw if raw in _SUPPORTED_HASHES else "MD5"


def _normalize_receipt_tax(value: str | None) -> str:
    raw = str(value or "none").strip().lower()
    return raw if raw in _SUPPORTED_RECEIPT_TAXES else "none"


def get_robokassa_config() -> RobokassaConfig:
    api_base = settings.api_base_url()
    test_mode = bool(settings.ROBOKASSA_TEST_MODE)
    password1 = (
        settings.ROBOKASSA_TEST_PASSWORD1
        if test_mode and settings.ROBOKASSA_TEST_PASSWORD1
        else settings.ROBOKASSA_PASSWORD1
    )
    password2 = (
        settings.ROBOKASSA_TEST_PASSWORD2
        if test_mode and settings.ROBOKASSA_TEST_PASSWORD2
        else settings.ROBOKASSA_PASSWORD2
    )
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
        receipt_tax=_normalize_receipt_tax(getattr(settings, "ROBOKASSA_RECEIPT_TAX", "none")),
    )


def format_out_sum(amount_minor: int, *, test_mode: bool) -> str:
    amount_minor_int = max(0, int(amount_minor or 0))
    amount_rub = (Decimal(amount_minor_int) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if test_mode:
        if amount_rub == amount_rub.to_integral_value():
            return str(int(amount_rub))
        return format(amount_rub, "f")
    return format(amount_rub.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def _format_receipt_sum(amount_minor: int) -> float:
    amount_minor_int = max(0, int(amount_minor or 0))
    amount_rub = (Decimal(amount_minor_int) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(amount_rub)


def build_receipt_json(
    *,
    amount_minor: int,
    item_name: str,
    tax: str = "none",
    quantity: int = 1,
    payment_method: str = "full_payment",
    payment_object: str = "service",
) -> str:
    quantity_int = max(1, int(quantity or 1))
    receipt = {
        "items": [
            {
                "name": str(item_name or "Axelio").strip() or "Axelio",
                "quantity": quantity_int,
                "sum": _format_receipt_sum(amount_minor),
                "payment_method": str(payment_method or "full_payment").strip() or "full_payment",
                "payment_object": str(payment_object or "service").strip() or "service",
                "tax": _normalize_receipt_tax(tax),
            }
        ]
    }
    return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))


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
    extra_params: Mapping[str, str] | None = None,
) -> str:
    base = f"{merchant_login}:{out_sum}:{invoice_id}"
    receipt_raw = str(receipt or "").strip()
    if receipt_raw:
        base += f":{quote(receipt_raw, safe='')}"
    base += f":{password1}"
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
    if isinstance(value, datetime):
        normalized = value.replace(second=0, microsecond=0)
        if normalized.tzinfo is not None:
            normalized = normalized.astimezone(normalized.tzinfo).replace(tzinfo=None)
        return normalized.isoformat(timespec="minutes")
    raw = str(value or "").strip()
    return raw or None


def build_checkout_fields(
    *,
    merchant_login: str,
    out_sum: str,
    invoice_id: str,
    description: str,
    password1: str,
    algorithm: str,
    result_url: str,
    success_url: str,
    fail_url: str,
    receipt: str | None = None,
    extra_params: Mapping[str, str] | None = None,
    test_mode: bool = False,
    culture: str = "ru",
    expiration_date: datetime | str | None = None,
    use_return_url2: bool = True,
    success_url2_method: str = "GET",
    fail_url2_method: str = "GET",
) -> dict[str, str]:
    shp_pairs = _sorted_shp_pairs(extra_params)
    receipt_raw = str(receipt or "").strip()
    signature = calculate_checkout_signature(
        merchant_login=merchant_login,
        out_sum=out_sum,
        invoice_id=invoice_id,
        password1=password1,
        algorithm=algorithm,
        receipt=receipt_raw or None,
        extra_params=dict(shp_pairs),
    )
    fields: dict[str, str] = {
        "MerchantLogin": merchant_login,
        "OutSum": out_sum,
        "InvId": invoice_id,
        "Description": description,
        "SignatureValue": signature,
        "Culture": culture or "ru",
        "ResultURL": result_url,
    }
    if receipt_raw:
        fields["Receipt"] = receipt_raw
    if use_return_url2:
        fields.update(
            {
                "SuccessUrl2": success_url,
                "SuccessUrl2Method": str(success_url2_method or "GET").upper(),
                "FailUrl2": fail_url,
                "FailUrl2Method": str(fail_url2_method or "GET").upper(),
            }
        )
    else:
        fields.update({"SuccessURL": success_url, "FailURL": fail_url})
    formatted_expiration_date = _format_expiration_date(expiration_date)
    if formatted_expiration_date:
        fields["ExpirationDate"] = formatted_expiration_date
    if test_mode:
        fields["IsTest"] = "1"
    fields.update(dict(shp_pairs))
    return fields


def build_checkout_post_html(*, payment_url: str, fields: Mapping[str, str]) -> str:
    action = html.escape(str(payment_url or "").strip(), quote=True)
    inputs = "\n".join(
        f'<input type="hidden" name="{html.escape(str(key), quote=True)}" value="{html.escape(str(value), quote=True)}">'
        for key, value in fields.items()
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Переход к оплате · Axelio</title>
</head>
<body>
  <form id="robokassa-form" method="post" action="{action}">
    {inputs}
    <noscript><button type="submit">Перейти к оплате</button></noscript>
  </form>
  <script>document.getElementById("robokassa-form").submit();</script>
</body>
</html>"""


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
    receipt: str | None = None,
    extra_params: Mapping[str, str] | None = None,
    test_mode: bool = False,
    culture: str = "ru",
    expiration_date: datetime | str | None = None,
    use_return_url2: bool = True,
    success_url2_method: str = "GET",
    fail_url2_method: str = "GET",
) -> str:
    fields = build_checkout_fields(
        merchant_login=merchant_login,
        out_sum=out_sum,
        invoice_id=invoice_id,
        description=description,
        password1=password1,
        algorithm=algorithm,
        result_url=result_url,
        success_url=success_url,
        fail_url=fail_url,
        receipt=receipt,
        extra_params=extra_params,
        test_mode=test_mode,
        culture=culture,
        expiration_date=expiration_date,
        use_return_url2=use_return_url2,
        success_url2_method=success_url2_method,
        fail_url2_method=fail_url2_method,
    )
    return f"{payment_url}?{urlencode(list(fields.items()))}"

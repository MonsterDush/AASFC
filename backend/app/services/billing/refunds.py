from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import xml.etree.ElementTree as ET
from typing import Any

import jwt
import requests

from app.core.config import settings
from .robokassa import _hash_value, _normalize_hash_algorithm, get_robokassa_config


@dataclass(slots=True)
class RobokassaRefundConfig:
    merchant_login: str
    password2: str
    password3: str
    hash_algorithm: str
    jwt_algorithm: str
    refund_api_url: str
    refund_state_url: str
    opstate_url: str
    timeout_seconds: int
    test_mode: bool

    @property
    def is_enabled(self) -> bool:
        return bool(self.merchant_login and self.password2 and self.password3 and not self.test_mode)


def get_robokassa_refund_config() -> RobokassaRefundConfig:
    base_cfg = get_robokassa_config()
    try:
        timeout_seconds = max(5, int(getattr(settings, "ROBOKASSA_REFUND_TIMEOUT_SECONDS", 15) or 15))
    except (TypeError, ValueError):
        timeout_seconds = 15
    jwt_algorithm = str(getattr(settings, "ROBOKASSA_REFUND_JWT_ALGORITHM", "HS256") or "HS256").strip().upper()
    if jwt_algorithm not in {"HS256", "HS384", "HS512"}:
        jwt_algorithm = "HS256"
    return RobokassaRefundConfig(
        merchant_login=base_cfg.merchant_login,
        password2=base_cfg.password2,
        password3=str(getattr(settings, "ROBOKASSA_PASSWORD3", "") or "").strip(),
        hash_algorithm=_normalize_hash_algorithm(base_cfg.hash_algorithm),
        jwt_algorithm=jwt_algorithm,
        refund_api_url=str(getattr(settings, "ROBOKASSA_REFUND_API_URL", "") or "https://services.robokassa.ru/RefundService/Refund/Create").strip(),
        refund_state_url=str(getattr(settings, "ROBOKASSA_REFUND_STATE_URL", "") or "https://services.robokassa.ru/RefundService/Refund/GetState").strip(),
        opstate_url=str(getattr(settings, "ROBOKASSA_OPSTATE_URL", "") or "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt").strip(),
        timeout_seconds=timeout_seconds,
        test_mode=base_cfg.test_mode,
    )


def _money_minor_to_major(amount_minor: int | None) -> float:
    amount_minor_int = max(0, int(amount_minor or 0))
    amount_rub = (Decimal(amount_minor_int) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(amount_rub)


def create_refund_request(*, op_key: str, refund_amount_minor: int | None = None) -> dict[str, Any]:
    cfg = get_robokassa_refund_config()
    if not cfg.is_enabled:
        raise RuntimeError("Robokassa refund API is not configured or test mode is enabled")
    payload: dict[str, Any] = {"OpKey": str(op_key)}
    if refund_amount_minor is not None and int(refund_amount_minor or 0) > 0:
        payload["RefundSum"] = _money_minor_to_major(int(refund_amount_minor))
    token = jwt.encode(payload, cfg.password3, algorithm=cfg.jwt_algorithm, headers={"typ": "JWT"})
    response = requests.post(
        cfg.refund_api_url,
        data=token,
        headers={"Content-Type": "text/plain; charset=utf-8"},
        timeout=cfg.timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Robokassa refund API returned invalid response")
    return data


def get_refund_request_state(*, request_id: str) -> dict[str, Any]:
    cfg = get_robokassa_refund_config()
    if not cfg.is_enabled:
        raise RuntimeError("Robokassa refund API is not configured or test mode is enabled")
    response = requests.get(cfg.refund_state_url, params={"id": str(request_id)}, timeout=cfg.timeout_seconds)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Robokassa refund state API returned invalid response")
    return data


def fetch_operation_info(*, invoice_id: str | int) -> dict[str, Any]:
    cfg = get_robokassa_refund_config()
    if not cfg.is_enabled:
        raise RuntimeError("Robokassa refund API is not configured or test mode is enabled")
    invoice_id_str = str(invoice_id)
    signature = _hash_value(f"{cfg.merchant_login}:{invoice_id_str}:{cfg.password2}", algorithm=cfg.hash_algorithm)
    response = requests.get(
        cfg.opstate_url,
        params={
            "MerchantLogin": cfg.merchant_login,
            "InvoiceID": invoice_id_str,
            "Signature": signature,
        },
        timeout=cfg.timeout_seconds,
    )
    response.raise_for_status()
    raw = response.text
    root = ET.fromstring(raw)
    ns = {"ns": root.tag[root.tag.find("{")+1:root.tag.find("}")] if root.tag.startswith("{") else ""}

    def _find(path: str) -> str | None:
        node = root.find(path, ns) if ns["ns"] else root.find(path.replace("ns:", ""))
        if node is None or node.text is None:
            return None
        return node.text.strip()

    result_code = _find("ns:Result/ns:Code") or _find("Result/Code")
    if str(result_code or "") != "0":
        description = _find("ns:Result/ns:Description") or _find("Result/Description") or "OpStateExt failed"
        raise RuntimeError(description)

    payment_method = _find("ns:Info/ns:PaymentMethod/ns:Code") or _find("Info/PaymentMethod/Code")
    op_key = _find("ns:Info/ns:OpKey") or _find("Info/OpKey")
    inc_sum = _find("ns:Info/ns:IncSum") or _find("Info/IncSum")
    out_sum = _find("ns:Info/ns:OutSum") or _find("Info/OutSum")
    state_code = _find("ns:State/ns:Code") or _find("State/Code")
    state_date = _find("ns:State/ns:StateDate") or _find("State/StateDate")
    return {
        "result_code": result_code,
        "state_code": state_code,
        "state_date": state_date,
        "payment_method_code": payment_method,
        "op_key": op_key,
        "inc_sum": inc_sum,
        "out_sum": out_sum,
        "raw": raw,
    }

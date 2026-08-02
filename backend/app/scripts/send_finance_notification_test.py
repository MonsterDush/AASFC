"""Send the finance/payroll notification previews to the configured test chat."""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.services import tg_notify  # noqa: E402
from app.services.payroll.notifications import (  # noqa: E402
    build_due_draft_expenses_text,
    build_employee_payroll_period_text,
    build_payroll_draft_ready_text,
)
from app.services.payroll.payments import PayrollPaymentWindow  # noqa: E402
from app.settings import settings  # noqa: E402


def _test_chat_id() -> int:
    raw = str(os.getenv("TEST_NOTIFICATION_CHAT_ID") or os.getenv("SUPER_ADMIN_TG_USER_IDS") or "")
    values = [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
    if not values:
        raise RuntimeError("TEST_NOTIFICATION_CHAT_ID or SUPER_ADMIN_TG_USER_IDS is not configured")
    return int(values[0])


def main() -> int:
    chat_id = _test_chat_id()
    window = PayrollPaymentWindow(
        payment_date=date(2026, 8, 5),
        period_start=date(2026, 7, 16),
        period_end=date(2026, 7, 31),
    )
    base_url = settings.frontend_base_url()
    previews = [
        (
            "ТЕСТ · напоминание о расходах\n\n" + build_due_draft_expenses_text(
                venue_name="Тестовое заведение",
                draft_count=3,
                amount_minor=485_000,
            ),
            f"{base_url}/owner-expenses.html?statuses=DRAFT",
            "Открыть черновики",
        ),
        (
            "ТЕСТ · черновик ФОТ\n\n" + build_payroll_draft_ready_text(
                venue_name="Тестовое заведение",
                window=window,
                amount_minor=1_245_000,
            ),
            f"{base_url}/owner-expenses.html?statuses=DRAFT&expense_kind=PAYROLL",
            "Открыть черновик",
        ),
        (
            "ТЕСТ · сводка сотрудника\n\n" + build_employee_payroll_period_text(
                venue_name="Тестовое заведение",
                window=window,
                summary={
                    "items": [{"days_count": 8}],
                    "totals": {"net_minor": 978_000, "bonuses_minor": 85_000, "penalties_minor": 22_000},
                },
            ),
            f"{base_url}/staff-salary.html?date_from=2026-07-16&date_to=2026-07-31",
            "Открыть начисления",
        ),
    ]
    results = [
        tg_notify.notify_result(chat_id=chat_id, text=text, url=url, button_text=button_text)
        for text, url, button_text in previews
    ]
    print(json.dumps({"sent": sum(int(bool(item.get("ok"))) for item in results), "total": len(results)}))
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

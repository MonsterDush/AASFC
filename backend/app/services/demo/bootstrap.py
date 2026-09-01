from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Adjustment,
    DailyReport,
    DailyReportAudit,
    DailyReportTipAllocation,
    DailyReportValue,
    Department,
    Expense,
    ExpenseCategory,
    KpiMetric,
    PayComponent,
    PayProfile,
    PayProfileAssignment,
    PaymentMethod,
    PayrollRun,
    Shift,
    ShiftAssignment,
    ShiftComment,
    ShiftInterval,
    Supplier,
    User,
    Venue,
    VenueBillingEvent,
    VenueBillingTransaction,
    VenueMember,
    VenuePosition,
)
from app.services.billing.manager import get_or_create_billing_state
from app.services.demo.fixture import clear_demo_venue_data, export_demo_fixture
from app.services.demo.session import DEMO_KIND_PUBLIC, DEMO_KIND_TEMPLATE, DEMO_PERSONA_OWNER, DEMO_PERSONA_STAFF
from app.services.finance.expenses import rebuild_expense_allocations_for_expense
from app.services.finance.revenue import rebuild_revenue_entries_for_report
from app.services.payroll import calculate_payroll_for_month


DEFAULT_DEMO_REFERENCE_YEAR = 2026
DEFAULT_DEMO_REFERENCE_MONTH = 3
DEFAULT_DEMO_HISTORY_MONTHS = 1
DEFAULT_DEMO_VENUE_NAME = "NOIR Lounge · DEMO by Axelio"

# March is the reference point for the existing hand-tuned DEMO dataset. The
# remaining coefficients describe a lounge with a clear cold-season peak and a
# sustained off-season decline beginning in May.
DEMO_SEASONAL_FACTORS: dict[int, float] = {
    1: 1.12,
    2: 1.08,
    3: 1.00,
    4: 0.94,
    5: 0.84,
    6: 0.72,
    7: 0.66,
    8: 0.70,
    9: 0.78,
    10: 0.88,
    11: 1.02,
    12: 1.16,
}

MONTH_NAMES_ACCUSATIVE = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}

OWNER_PERMISSIONS: list[str] = []
HOOKAH_REPORTER_PERMISSIONS = [
    "SHIFT_REPORT_VIEW",
    "SHIFT_REPORT_EDIT",
    "SHIFT_REPORT_CLOSE",
    "DEPARTMENTS_VIEW",
    "PAYMENT_METHODS_VIEW",
    "KPI_METRICS_VIEW",
]


@dataclass
class DemoBootstrapResult:
    venue_id: int
    venue_name: str
    reference_year: int
    reference_month: int
    history_months: int
    period_start_year: int
    period_start_month: int
    fixture_path: str | None
    counts: dict[str, int]
    warnings: list[str]


def _slug(value: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw.strip("-") or "demo"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _month_start(year: int, month: int) -> date:
    return date(int(year), int(month), 1)


def _month_end(year: int, month: int) -> date:
    return date(int(year), int(month), calendar.monthrange(int(year), int(month))[1])


def _month_iter(year: int, month: int) -> Iterable[date]:
    cur = _month_start(year, month)
    end = _month_end(year, month)
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _history_periods(reference_year: int, reference_month: int, history_months: int) -> list[tuple[int, int]]:
    if not 1 <= int(reference_month) <= 12:
        raise ValueError("reference_month должен быть от 1 до 12")
    if not 1 <= int(history_months) <= 24:
        raise ValueError("history_months должен быть от 1 до 24")
    reference_index = int(reference_year) * 12 + (int(reference_month) - 1)
    periods: list[tuple[int, int]] = []
    for offset in range(int(history_months) - 1, -1, -1):
        month_index = reference_index - offset
        periods.append((month_index // 12, (month_index % 12) + 1))
    return periods


def _seasonal_factor(month: int) -> float:
    return float(DEMO_SEASONAL_FACTORS.get(int(month), 1.0))


def _scale_minor(amount_minor: int, factor: float) -> int:
    return int(round(int(amount_minor) * float(factor)))


def _merge_counts(target: dict[str, int], additions: dict[str, int]) -> None:
    for key, value in additions.items():
        target[key] = int(target.get(key, 0)) + int(value or 0)


def _require_safe_target_venue(db: Session, venue: Venue) -> None:
    if bool(getattr(venue, "is_demo", False)):
        return
    non_demo_members = int(
        db.execute(
            select(func.count(VenueMember.id))
            .join(User, User.id == VenueMember.user_id)
            .where(VenueMember.venue_id == int(venue.id), User.is_demo_user.is_(False))
        ).scalar()
        or 0
    )
    has_live_content = any(
        int(db.execute(select(func.count(model.id)).where(model.venue_id == int(venue.id))).scalar() or 0) > 0
        for model in [Shift, DailyReport, Expense, PayrollRun]
    )
    if non_demo_members or has_live_content:
        raise ValueError(
            "Bootstrap DEMO можно запускать только на DEMO-заведении или на пустом venue без боевых данных"
        )


def _ensure_venue(
    db: Session, *, venue_id: int | None, venue_name: str, reference_year: int, reference_month: int, make_public: bool
) -> Venue:
    venue: Venue | None = None
    if venue_id is not None:
        venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
        if venue is None:
            raise ValueError(f"Venue #{int(venue_id)} not found")
        _require_safe_target_venue(db, venue)
    else:
        venue = Venue(name=venue_name)
        db.add(venue)
        db.flush()

    venue.name = venue_name
    venue.is_demo = bool(make_public)
    venue.demo_kind = DEMO_KIND_PUBLIC if bool(make_public) else DEMO_KIND_TEMPLATE
    venue.demo_reference_year = int(reference_year)
    venue.demo_reference_month = int(reference_month)
    venue.is_archived = False
    venue.archived_at = None
    venue.tips_enabled = True
    venue.tips_split_mode = "EQUAL"
    venue.tips_weights = None
    db.flush()
    return venue


def _build_demo_users() -> list[dict]:
    return [
        {
            "key": "owner",
            "persona": DEMO_PERSONA_OWNER,
            "venue_role": "OWNER",
            "full_name": "Владимир Сергеев",
            "short_name": "Владелец",
            "tg_username": "axelio_demo_owner",
            "position_title": None,
            "profile_key": None,
            "permission_codes": OWNER_PERMISSIONS,
        },
        {
            "key": "staff_persona",
            "persona": DEMO_PERSONA_STAFF,
            "venue_role": "STAFF",
            "full_name": "Илья Орлов",
            "short_name": "Илья",
            "tg_username": "axelio_demo_staff",
            "position_title": "Кальянный мастер",
            "profile_key": "hookah",
            "permission_codes": [],
        },
        {
            "key": "anna_admin",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "Анна Соколова",
            "short_name": "Анна",
            "tg_username": "axelio_demo_anna",
            "position_title": "Администратор",
            "profile_key": "admin",
            "permission_codes": [],
        },
        {
            "key": "kirill_hookah",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "Кирилл Громов",
            "short_name": "Кирилл",
            "tg_username": "axelio_demo_kirill",
            "position_title": "Кальянный мастер",
            "profile_key": "hookah",
            "permission_codes": HOOKAH_REPORTER_PERMISSIONS,
        },
        {
            "key": "maksim_hookah",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "Максим Новиков",
            "short_name": "Максим",
            "tg_username": "axelio_demo_maksim",
            "position_title": "Кальянный мастер",
            "profile_key": "hookah",
            "permission_codes": [],
        },
        {
            "key": "maria_bar",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "Мария Белова",
            "short_name": "Мария",
            "tg_username": "axelio_demo_maria",
            "position_title": "Бармен",
            "profile_key": "bar",
            "permission_codes": [],
        },
        {
            "key": "aleksey_waiter",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "Алексей Фомин",
            "short_name": "Алексей",
            "tg_username": "axelio_demo_alex",
            "position_title": "Официант",
            "profile_key": "floor",
            "permission_codes": [],
        },
        {
            "key": "polina_waiter",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "Полина Кузнецова",
            "short_name": "Полина",
            "tg_username": "axelio_demo_polina",
            "position_title": "Официант",
            "profile_key": "floor",
            "permission_codes": [],
        },
        {
            "key": "daniil_host",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "Даниил Морозов",
            "short_name": "Даниил",
            "tg_username": "axelio_demo_daniil",
            "position_title": "Хостес",
            "profile_key": "host",
            "permission_codes": [],
        },
        {
            "key": "sofia_manager",
            "persona": None,
            "venue_role": "STAFF",
            "full_name": "София Волкова",
            "short_name": "София",
            "tg_username": "axelio_demo_sofia",
            "position_title": "Старший менеджер",
            "profile_key": "admin",
            "permission_codes": HOOKAH_REPORTER_PERMISSIONS,
        },
    ]


def _create_user(db: Session, spec: dict, *, existing_user: User | None = None) -> User:
    user = existing_user or User()
    user.tg_username = spec.get("tg_username")
    user.full_name = spec.get("full_name")
    user.short_name = spec.get("short_name")
    user.system_role = "NONE"
    user.notify_enabled = False
    user.notify_adjustments = False
    user.notify_shifts = False
    user.notify_shift_comments = False
    user.notify_day_economics = False
    user.notify_salary = False
    user.notify_soft_alerts = False
    user.notify_integrations = False
    user.shift_reminder_lead_time_hours = 18
    user.notification_detail_level = "standard"
    user.is_demo_user = True
    user.demo_persona = spec.get("persona")
    if existing_user is None:
        db.add(user)
    db.flush()
    return user


def _create_member_and_position(db: Session, *, venue: Venue, user: User, spec: dict) -> VenuePosition | None:
    db.add(
        VenueMember(
            venue_id=int(venue.id),
            user_id=int(user.id),
            venue_role=str(spec.get("venue_role") or "STAFF").upper(),
            is_active=True,
        )
    )
    position_title = spec.get("position_title")
    if not position_title:
        return None
    permission_codes = spec.get("permission_codes") or []
    position = VenuePosition(
        venue_id=int(venue.id),
        member_user_id=int(user.id),
        title=str(position_title),
        rate=0,
        percent=0,
        permission_codes=json.dumps(permission_codes, ensure_ascii=False) if permission_codes else None,
        is_active=True,
    )
    db.add(position)
    db.flush()
    return position


def _create_dictionaries(db: Session, *, venue: Venue) -> dict:
    departments = [
        Department(venue_id=int(venue.id), code="hookah", title="Кальянный зал", sort_order=10, is_active=True),
        Department(venue_id=int(venue.id), code="bar", title="Бар", sort_order=20, is_active=True),
        Department(venue_id=int(venue.id), code="kitchen", title="VIP-комнаты", sort_order=30, is_active=True),
    ]
    payment_methods = [
        PaymentMethod(venue_id=int(venue.id), code="cash", title="Наличные", sort_order=10, is_active=True),
        PaymentMethod(venue_id=int(venue.id), code="cashless", title="Эквайринг", sort_order=20, is_active=True),
        PaymentMethod(venue_id=int(venue.id), code="sbp", title="СБП", sort_order=30, is_active=True),
        PaymentMethod(venue_id=int(venue.id), code="other", title="Прочее", sort_order=40, is_active=True),
    ]
    kpis = [
        KpiMetric(venue_id=int(venue.id), code="upsale", title="Допродажи", unit="QTY", sort_order=10, is_active=True),
        KpiMetric(venue_id=int(venue.id), code="vip", title="VIP-брони", unit="QTY", sort_order=20, is_active=True),
        KpiMetric(venue_id=int(venue.id), code="retail", title="Ритейл", unit="RUB", sort_order=30, is_active=True),
    ]
    categories = [
        ExpenseCategory(venue_id=int(venue.id), code="rent", title="Аренда", sort_order=10, is_active=True),
        ExpenseCategory(venue_id=int(venue.id), code="tobacco", title="Табак и уголь", sort_order=20, is_active=True),
        ExpenseCategory(venue_id=int(venue.id), code="barstock", title="Барная закупка", sort_order=30, is_active=True),
        ExpenseCategory(venue_id=int(venue.id), code="supplies", title="Хозтовары", sort_order=40, is_active=True),
        ExpenseCategory(venue_id=int(venue.id), code="marketing", title="Маркетинг", sort_order=50, is_active=True),
    ]
    suppliers = [
        Supplier(
            venue_id=int(venue.id), title="Hookah Trade", contact="@hookah_trade_demo", sort_order=10, is_active=True
        ),
        Supplier(
            venue_id=int(venue.id),
            title="Metro Cash & Carry",
            contact="+7 800 700-10-77",
            sort_order=20,
            is_active=True,
        ),
        Supplier(
            venue_id=int(venue.id), title="Local Partner", contact="@axelio_partner", sort_order=30, is_active=True
        ),
    ]
    for item in [*departments, *payment_methods, *kpis, *categories, *suppliers]:
        db.add(item)
    db.flush()
    return {
        "departments": {item.code: item for item in departments},
        "payment_methods": {item.code: item for item in payment_methods},
        "kpis": {item.code: item for item in kpis},
        "categories": {item.code: item for item in categories},
        "suppliers": {item.title: item for item in suppliers},
    }


def _create_intervals(db: Session, *, venue: Venue) -> dict[str, ShiftInterval]:
    opening = ShiftInterval(
        venue_id=int(venue.id), title="День", start_time=time(12, 0), end_time=time(18, 0), is_active=True
    )
    evening = ShiftInterval(
        venue_id=int(venue.id), title="Прайм-тайм", start_time=time(18, 0), end_time=time(23, 45), is_active=True
    )
    db.add_all([opening, evening])
    db.flush()
    return {"opening": opening, "evening": evening}


def _rotation_pick(pool: list[str], idx: int, count: int) -> list[str]:
    if not pool or count <= 0:
        return []
    out = []
    for shift in range(count):
        out.append(pool[(idx + shift) % len(pool)])
    return out


def _create_schedule(
    db: Session,
    *,
    venue: Venue,
    reference_year: int,
    reference_month: int,
    users_by_key: dict[str, User],
    positions_by_key: dict[str, VenuePosition],
    owner_user: User,
    intervals: dict[str, ShiftInterval] | None = None,
) -> dict[str, int]:
    intervals = intervals or _create_intervals(db, venue=venue)
    hookah_keys = ["staff_persona", "kirill_hookah", "maksim_hookah"]
    floor_keys = ["aleksey_waiter", "polina_waiter"]
    admin_keys = ["anna_admin", "sofia_manager"]
    host_keys = ["daniil_host"]
    bar_keys = ["maria_bar"]
    created_shifts = 0
    created_assignments = 0
    created_comments = 0

    for idx, day in enumerate(_month_iter(reference_year, reference_month)):
        opening_shift = Shift(
            venue_id=int(venue.id),
            date=day,
            interval_id=int(intervals["opening"].id),
            created_by_user_id=int(owner_user.id),
            is_active=True,
        )
        evening_shift = Shift(
            venue_id=int(venue.id),
            date=day,
            interval_id=int(intervals["evening"].id),
            created_by_user_id=int(owner_user.id),
            is_active=True,
        )
        db.add_all([opening_shift, evening_shift])
        db.flush()
        created_shifts += 2

        opening_staff = []
        opening_staff += _rotation_pick(admin_keys, idx, 1)
        opening_staff += _rotation_pick(hookah_keys, idx, 1)
        opening_staff += _rotation_pick(host_keys, idx, 1)
        if day.weekday() in {4, 5, 6}:
            opening_staff += _rotation_pick(floor_keys, idx, 1)

        evening_staff = []
        evening_staff += _rotation_pick(admin_keys, idx + 1, 1)
        evening_staff += _rotation_pick(hookah_keys, idx + 1, 2)
        evening_staff += _rotation_pick(bar_keys, idx, 1)
        evening_staff += _rotation_pick(floor_keys, idx + 1, 1)
        if day.weekday() in {4, 5}:
            evening_staff += _rotation_pick(host_keys, idx, 1)

        for shift_obj, keys in ((opening_shift, opening_staff), (evening_shift, evening_staff)):
            seen: set[str] = set()
            for key in keys:
                if key in seen:
                    continue
                seen.add(key)
                pos = positions_by_key.get(key)
                if pos is None:
                    continue
                db.add(
                    ShiftAssignment(
                        shift_id=int(shift_obj.id),
                        member_user_id=int(users_by_key[key].id),
                        venue_position_id=int(pos.id),
                    )
                )
                created_assignments += 1

        shift_note = None
        if day.month == 3 and day.day == 8:
            shift_note = "Праздничный день: усилить VIP-зал, собрать предзаказы и держать запас льда и фруктов."
        elif day.day in {14, 15}:
            shift_note = "Пиковая посадка в середине месяца: готовим две VIP-комнаты и держим запас по топовым вкусам."
        elif day.day in {22, 28}:
            shift_note = (
                "Акцент на сервис: проверить посадку, подготовить welcome-комплименты и сделать фотоотчёт по залу."
            )
        elif day.day == 3:
            shift_note = "Старт месяца: проверить остатки табака, угля и ритейла перед вечерней волной."

        if shift_note:
            db.add(
                ShiftComment(
                    shift_id=int(evening_shift.id),
                    author_user_id=int(users_by_key["anna_admin"].id),
                    text=shift_note,
                    created_at=datetime.combine(day, time(hour=9), tzinfo=timezone.utc),
                )
            )
            created_comments += 1

    db.flush()
    return {
        "shifts": created_shifts,
        "shift_assignments": created_assignments,
        "shift_comments": created_comments,
    }


def _daily_base_minor(day: date) -> int:
    if day.month == 3 and day.day == 8:
        base_minor = 11800000
    elif day.day in {14, 15, 28, 29}:
        base_minor = 10300000
    elif day.weekday() in {4, 5}:  # fri/sat
        base_minor = 9400000
    elif day.weekday() == 6:
        base_minor = 7900000
    elif day.weekday() == 0:
        base_minor = 4700000
    else:
        base_minor = 6250000
    return _scale_minor(base_minor, _seasonal_factor(day.month))


def _minor_to_report_units(amount_minor: int) -> int:
    return int(round(int(amount_minor or 0) / 100))


def _create_reports(
    db: Session,
    *,
    venue: Venue,
    reference_year: int,
    reference_month: int,
    users_by_key: dict[str, User],
    dictionaries: dict,
) -> dict[str, int]:
    pm = dictionaries["payment_methods"]
    dept = dictionaries["departments"]
    kpis = dictionaries["kpis"]
    created_reports = 0
    created_values = 0
    created_audits = 0
    created_tips = 0
    created_finance_entries = 0
    owner_user = users_by_key["owner"]
    admin_user = users_by_key["anna_admin"]
    season_factor = _seasonal_factor(reference_month)

    for idx, day in enumerate(_month_iter(reference_year, reference_month)):
        is_peak_day = (day.month == 3 and day.day == 8) or day.day in {14, 15, 28, 29}
        total_minor = _daily_base_minor(day) + ((idx % 5) * 250000)
        total_value = _minor_to_report_units(total_minor)

        hookah_ratio = 0.58
        bar_ratio = 0.27
        if is_peak_day:
            hookah_ratio = 0.61
            bar_ratio = 0.24
        elif day.weekday() == 0:
            hookah_ratio = 0.54
            bar_ratio = 0.29
        hookah_value = int(total_value * hookah_ratio)
        bar_value = int(total_value * bar_ratio)
        kitchen_value = int(total_value - hookah_value - bar_value)

        cash_ratio = 0.22
        cashless_ratio = 0.53
        sbp_ratio = 0.20
        if is_peak_day:
            cash_ratio = 0.17
            cashless_ratio = 0.55
            sbp_ratio = 0.24
        cash_value = int(total_value * cash_ratio)
        cashless_value = int(total_value * cashless_ratio)
        sbp_value = int(total_value * sbp_ratio)
        other_value = int(total_value - cash_value - cashless_value - sbp_value)

        discrepancy = 0
        comment = None
        if day.day == 12:
            discrepancy = _minor_to_report_units(70000)
            cash_value += discrepancy
            comment = "Пример дня с расхождением: часть оплаты по СБП подтвердилась уже после закрытия смены."
        elif day.day == 27:
            discrepancy = _minor_to_report_units(50000)
            cash_value += discrepancy
            comment = "Пример дня с расхождением: гость доплатил наличными после сверки кассы."
        elif day.month == 3 and day.day == 8:
            comment = "Праздничный вечер: усиленная посадка, две VIP-комнаты и повышенный спрос на премиум-миксы."
        elif day.day in {14, 15}:
            comment = "Пиковая посадка в середине месяца: высокий оборот по кальянам и СБП, усиленный состав на вечер."

        tips_total = _minor_to_report_units(
            _scale_minor(360000 + (idx % 4) * 65000 + (120000 if is_peak_day else 0), season_factor)
        )
        report = DailyReport(
            venue_id=int(venue.id),
            date=day,
            cash=cash_value,
            cashless=cashless_value + sbp_value,
            revenue_total=total_value,
            tips_total=tips_total,
            status="CLOSED",
            comment=comment,
            closed_by_user_id=int(admin_user.id),
            closed_at=datetime.combine(day, time(23, 30), tzinfo=timezone.utc),
            created_by_user_id=int(admin_user.id),
            created_at=datetime.combine(day, time(23, 0), tzinfo=timezone.utc),
            updated_by_user_id=int(admin_user.id),
            updated_at=datetime.combine(day, time(23, 35), tzinfo=timezone.utc),
        )
        db.add(report)
        db.flush()
        created_reports += 1

        values = [
            ("PAYMENT", int(pm["cash"].id), cash_value),
            ("PAYMENT", int(pm["cashless"].id), cashless_value),
            ("PAYMENT", int(pm["sbp"].id), sbp_value),
            ("PAYMENT", int(pm["other"].id), other_value),
            ("DEPT", int(dept["hookah"].id), hookah_value),
            ("DEPT", int(dept["bar"].id), bar_value),
            ("DEPT", int(dept["kitchen"].id), kitchen_value),
            (
                "KPI",
                int(kpis["upsale"].id),
                max(1, int(round((11 + (idx % 7) + (2 if is_peak_day else 0)) * season_factor))),
            ),
            (
                "KPI",
                int(kpis["vip"].id),
                max(
                    1,
                    int(round((2 + (1 if day.weekday() in {4, 5} else 0) + (1 if is_peak_day else 0)) * season_factor)),
                ),
            ),
            (
                "KPI",
                int(kpis["retail"].id),
                _minor_to_report_units(
                    _scale_minor(85000 + (idx % 6) * 12000 + (25000 if is_peak_day else 0), season_factor)
                ),
            ),
        ]
        report_values: list[DailyReportValue] = []
        for kind, ref_id, value in values:
            row = DailyReportValue(report_id=int(report.id), kind=kind, ref_id=int(ref_id), value_numeric=int(value))
            db.add(row)
            report_values.append(row)
            created_values += 1
        db.flush()

        created_finance_entries += rebuild_revenue_entries_for_report(
            db=db,
            report=report,
            values=report_values,
        )

        tip_receivers = (
            ["staff_persona", "kirill_hookah", "maria_bar"]
            if day.weekday() in {4, 5}
            else ["staff_persona", "aleksey_waiter"]
        )
        share = tips_total // len(tip_receivers)
        remainder = tips_total % len(tip_receivers)
        for t_idx, key in enumerate(tip_receivers):
            db.add(
                DailyReportTipAllocation(
                    report_id=int(report.id),
                    user_id=int(users_by_key[key].id),
                    amount=int(share + (remainder if t_idx == 0 else 0)),
                    split_mode="EQUAL",
                    meta_json={"demo": True},
                )
            )
            created_tips += 1

        if day.day in {5, 12, 27}:
            db.add(
                DailyReportAudit(
                    report_id=int(report.id),
                    user_id=int(owner_user.id),
                    changed_at=datetime.combine(day, time(23, 40), tzinfo=timezone.utc),
                    diff_json={
                        "status": "CLOSED",
                        "comment": comment,
                        "note": "Демо-аудит: пример истории изменений после закрытия смены",
                    },
                )
            )
            created_audits += 1

    db.flush()
    return {
        "daily_reports": created_reports,
        "daily_report_values": created_values,
        "daily_report_tip_allocations": created_tips,
        "daily_report_audits": created_audits,
        "finance_entries_revenue": created_finance_entries,
    }


def _create_expenses(
    db: Session,
    *,
    venue: Venue,
    dictionaries: dict,
    users_by_key: dict[str, User],
    reference_year: int,
    reference_month: int,
) -> dict[str, int]:
    categories = dictionaries["categories"]
    suppliers = dictionaries["suppliers"]
    payment_methods = dictionaries["payment_methods"]
    owner = users_by_key["owner"]
    season_factor = _seasonal_factor(reference_month)
    variable_cost_factor = 0.55 + (0.45 * season_factor)
    month_title = MONTH_NAMES_ACCUSATIVE[int(reference_month)]
    items = [
        (
            "rent",
            "Metro Cash & Carry",
            13500000,
            date(reference_year, reference_month, 5),
            1,
            f"Аренда помещения за {month_title}",
        ),
        (
            "tobacco",
            "Hookah Trade",
            _scale_minor(5200000, variable_cost_factor),
            date(reference_year, reference_month, 3),
            2,
            "Стартовая закупка табака, угля и чаш перед пиковыми выходными",
        ),
        (
            "barstock",
            "Metro Cash & Carry",
            _scale_minor(2850000, variable_cost_factor),
            date(reference_year, reference_month, 7),
            1,
            "Барная закупка: лимонады, пюре, лёд и стекло",
        ),
        (
            "supplies",
            "Local Partner",
            _scale_minor(980000, variable_cost_factor),
            date(reference_year, reference_month, 10),
            1,
            "Хозтовары, расходники и уборка после первых пиковых дней",
        ),
        (
            "marketing",
            "Local Partner",
            _scale_minor(1800000, variable_cost_factor),
            date(reference_year, reference_month, 12),
            3,
            "Таргет и блогеры под пятничные и праздничные посадки",
        ),
        (
            "tobacco",
            "Hookah Trade",
            _scale_minor(3450000, variable_cost_factor),
            date(reference_year, reference_month, 17),
            2,
            "Дозакупка премиум-линеек и самых ходовых вкусов",
        ),
        (
            "barstock",
            "Metro Cash & Carry",
            _scale_minor(1620000, variable_cost_factor),
            date(reference_year, reference_month, 21),
            1,
            "Дозакупка фруктов, напитков и сиропов под конец месяца",
        ),
        (
            "supplies",
            "Local Partner",
            _scale_minor(760000, variable_cost_factor),
            date(reference_year, reference_month, 25),
            1,
            "Текстиль, аромасвечи и расходники для VIP-комнат",
        ),
    ]
    created = 0
    for category_code, supplier_title, amount_minor, expense_date, spread_months, comment in items:
        expense = Expense(
            venue_id=int(venue.id),
            category_id=int(categories[category_code].id),
            supplier_id=int(suppliers[supplier_title].id),
            payment_method_id=int(payment_methods["cashless"].id),
            amount_minor=int(amount_minor),
            expense_date=expense_date,
            generated_for_month=expense_date.replace(day=1),
            spread_months=int(spread_months),
            comment=comment,
            status="CONFIRMED",
            created_by_user_id=int(owner.id),
            created_at=datetime.combine(expense_date, time(11, 0), tzinfo=timezone.utc),
            updated_at=datetime.combine(expense_date, time(11, 5), tzinfo=timezone.utc),
        )
        db.add(expense)
        db.flush()
        rebuild_expense_allocations_for_expense(db=db, expense=expense)
        created += 1
    db.flush()
    return {"expenses": created}


def _create_pay_profiles(
    db: Session,
    *,
    venue: Venue,
    dictionaries: dict,
    users_by_key: dict[str, User],
    reference_year: int,
    reference_month: int,
) -> dict[str, int]:
    hookah_profile = PayProfile(
        venue_id=int(venue.id),
        title="Кальянный мастер",
        description="Почасовая ставка + % от выручки кальянного зала + KPI за допродажи",
        is_active=True,
    )
    admin_profile = PayProfile(
        venue_id=int(venue.id),
        title="Администратор",
        description="Фикс за месяц + оплата за смены старшего состава",
        is_active=True,
    )
    bar_profile = PayProfile(
        venue_id=int(venue.id),
        title="Бар и зал",
        description="Почасовая ставка + фикс за смену для бара и сервиса",
        is_active=True,
    )
    db.add_all([hookah_profile, admin_profile, bar_profile])
    db.flush()

    hookah_dept = dictionaries["departments"]["hookah"]
    kpi_upsale = dictionaries["kpis"]["upsale"]

    components = [
        PayComponent(
            venue_id=int(venue.id),
            pay_profile_id=int(hookah_profile.id),
            component_type="SALARY_HOURLY",
            title="Почасовая ставка",
            rate_minor=52000,
            is_active=True,
            sort_order=10,
        ),
        PayComponent(
            venue_id=int(venue.id),
            pay_profile_id=int(hookah_profile.id),
            component_type="PERCENT_DEPARTMENT_REVENUE",
            title="% от кальянного зала",
            percent_bps=340,
            department_id=int(hookah_dept.id),
            base_scope="WORKED_DATES",
            is_active=True,
            sort_order=20,
        ),
        PayComponent(
            venue_id=int(venue.id),
            pay_profile_id=int(hookah_profile.id),
            component_type="KPI_BONUS",
            title="Бонус за допродажи",
            amount_minor=420000,
            kpi_metric_id=int(kpi_upsale.id),
            threshold_value=13,
            is_active=True,
            sort_order=30,
        ),
        PayComponent(
            venue_id=int(venue.id),
            pay_profile_id=int(admin_profile.id),
            component_type="SALARY_FIXED_MONTH",
            title="Фикс за месяц",
            amount_minor=6900000,
            is_active=True,
            sort_order=10,
        ),
        PayComponent(
            venue_id=int(venue.id),
            pay_profile_id=int(admin_profile.id),
            component_type="SALARY_PER_SHIFT",
            title="Смена администратора",
            amount_minor=220000,
            is_active=True,
            sort_order=20,
        ),
        PayComponent(
            venue_id=int(venue.id),
            pay_profile_id=int(bar_profile.id),
            component_type="SALARY_HOURLY",
            title="Почасовая ставка",
            rate_minor=35000,
            is_active=True,
            sort_order=10,
        ),
        PayComponent(
            venue_id=int(venue.id),
            pay_profile_id=int(bar_profile.id),
            component_type="SALARY_PER_SHIFT",
            title="Фикс за смену",
            amount_minor=100000,
            is_active=True,
            sort_order=20,
        ),
    ]
    db.add_all(components)
    db.flush()

    profile_by_key = {
        "hookah": hookah_profile,
        "admin": admin_profile,
        "bar": bar_profile,
        "floor": bar_profile,
        "host": bar_profile,
    }
    created_assignments = 0
    month_start = _month_start(reference_year, reference_month)
    for spec in _build_demo_users():
        profile_key = spec.get("profile_key")
        if not profile_key:
            continue
        user = users_by_key[spec["key"]]
        profile = profile_by_key[profile_key]
        db.add(
            PayProfileAssignment(
                venue_id=int(venue.id),
                pay_profile_id=int(profile.id),
                member_user_id=int(user.id),
                start_date=month_start,
                end_date=None,
                is_active=True,
            )
        )
        created_assignments += 1
    db.flush()
    return {
        "pay_profiles": 3,
        "pay_components": len(components),
        "pay_profile_assignments": created_assignments,
    }


def _create_adjustments(
    db: Session,
    *,
    venue: Venue,
    users_by_key: dict[str, User],
    owner_user: User,
    reference_year: int,
    reference_month: int,
) -> dict[str, int]:
    items = [
        (
            "bonus",
            "staff_persona",
            date(reference_year, reference_month, 6),
            140000,
            "Лучшие допродажи недели по кальянному залу",
        ),
        ("penalty", "aleksey_waiter", date(reference_year, reference_month, 11), 60000, "Опоздание на вечернюю смену"),
        ("writeoff", None, date(reference_year, reference_month, 19), 95000, "Списание инвентаря после инвентаризации"),
        (
            "bonus",
            "anna_admin",
            date(reference_year, reference_month, 28),
            180000,
            "Высокая оценка сервиса и сильная координация вечерних смен",
        ),
    ]
    for adj_type, member_key, adj_date, amount, reason in items:
        db.add(
            Adjustment(
                venue_id=int(venue.id),
                type=adj_type,
                member_user_id=int(users_by_key[member_key].id) if member_key else None,
                date=adj_date,
                amount=int(amount),
                reason=reason,
                is_active=True,
                created_by_user_id=int(owner_user.id),
                created_at=datetime.combine(adj_date, time(12, 0), tzinfo=timezone.utc),
                updated_by_user_id=int(owner_user.id),
                updated_at=datetime.combine(adj_date, time(12, 10), tzinfo=timezone.utc),
            )
        )
    db.flush()
    return {"adjustments": len(items)}


def _configure_billing(db: Session, *, venue: Venue, owner_user: User) -> dict[str, int]:
    state = get_or_create_billing_state(db, venue_id=int(venue.id))
    state.status = "ACTIVE"
    state.paid_until = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    state.grace_until = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    state.last_payment_at = datetime(2026, 3, 18, 11, 30, tzinfo=timezone.utc)
    state.next_payment_due_at = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    state.provider = "ROBOKASSA"
    state.updated_at = _utcnow()
    db.flush()

    tx = VenueBillingTransaction(
        venue_id=int(venue.id),
        source="MANUAL_ADMIN",
        type="EXTEND",
        status="SUCCEEDED",
        amount_minor=299000,
        days_added=30,
        period_from=datetime(2026, 3, 19, 0, 0, tzinfo=timezone.utc),
        period_until=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
        provider_invoice_id="DEMO-EXTEND-1",
        provider_payment_id="DEMO-PAY-1",
        provider_payload_json={"demo": True},
        comment="Тестовое продление DEMO после оплаты тарифа владельцем",
        created_by_user_id=int(owner_user.id),
        created_at=datetime(2026, 3, 19, 11, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 19, 11, 30, tzinfo=timezone.utc),
    )
    event = VenueBillingEvent(
        venue_id=int(venue.id),
        event_type="DEMO_BOOTSTRAP",
        old_status="ACTIVE",
        new_status="ACTIVE",
        meta_json={"paid_until": state.paid_until.isoformat() if state.paid_until else None},
        created_by_user_id=int(owner_user.id),
        created_at=datetime(2026, 3, 19, 11, 30, tzinfo=timezone.utc),
    )
    db.add_all([tx, event])
    db.flush()
    return {"billing_transactions": 1, "billing_events": 1}


def bootstrap_demo_venue(
    db: Session,
    *,
    venue_id: int | None = None,
    venue_name: str = DEFAULT_DEMO_VENUE_NAME,
    reference_year: int = DEFAULT_DEMO_REFERENCE_YEAR,
    reference_month: int = DEFAULT_DEMO_REFERENCE_MONTH,
    history_months: int = DEFAULT_DEMO_HISTORY_MONTHS,
    make_public: bool = True,
    export_fixture_path: str | None = None,
    export_fixture_after: bool = False,
) -> DemoBootstrapResult:
    warnings: list[str] = []
    counts: dict[str, int] = {}
    periods = _history_periods(reference_year, reference_month, history_months)
    period_start_year, period_start_month = periods[0]

    venue = _ensure_venue(
        db,
        venue_id=venue_id,
        venue_name=str(venue_name or DEFAULT_DEMO_VENUE_NAME).strip() or DEFAULT_DEMO_VENUE_NAME,
        reference_year=int(reference_year),
        reference_month=int(reference_month),
        make_public=bool(make_public),
    )

    existing_users_by_username: dict[str, User] = {}
    existing_demo_users = (
        db.execute(
            select(User)
            .join(VenueMember, VenueMember.user_id == User.id)
            .where(
                VenueMember.venue_id == int(venue.id),
                User.is_demo_user.is_(True),
            )
            .order_by(User.id.asc())
        )
        .scalars()
        .all()
    )
    for existing_user in existing_demo_users:
        username = str(existing_user.tg_username or "").strip()
        if username:
            existing_users_by_username.setdefault(username, existing_user)

    deleted = clear_demo_venue_data(db, venue_id=int(venue.id))
    for key, value in deleted.items():
        if value:
            counts[f"deleted_{key}"] = int(value)

    users_by_key: dict[str, User] = {}
    positions_by_key: dict[str, VenuePosition] = {}
    for spec in _build_demo_users():
        user = _create_user(
            db,
            spec,
            existing_user=existing_users_by_username.get(str(spec.get("tg_username") or "")),
        )
        users_by_key[spec["key"]] = user
        position = _create_member_and_position(db, venue=venue, user=user, spec=spec)
        if position is not None:
            positions_by_key[spec["key"]] = position
    counts["users"] = len(users_by_key)
    counts["venue_members"] = len(users_by_key)
    counts["venue_positions"] = len(positions_by_key)

    dictionaries = _create_dictionaries(db, venue=venue)
    counts["departments"] = len(dictionaries["departments"])
    counts["payment_methods"] = len(dictionaries["payment_methods"])
    counts["kpi_metrics"] = len(dictionaries["kpis"])
    counts["expense_categories"] = len(dictionaries["categories"])
    counts["suppliers"] = len(dictionaries["suppliers"])

    intervals = _create_intervals(db, venue=venue)
    counts["shift_intervals"] = len(intervals)
    counts.update(
        _create_pay_profiles(
            db,
            venue=venue,
            dictionaries=dictionaries,
            users_by_key=users_by_key,
            reference_year=int(period_start_year),
            reference_month=int(period_start_month),
        )
    )

    for year, month in periods:
        _merge_counts(
            counts,
            _create_schedule(
                db,
                venue=venue,
                reference_year=int(year),
                reference_month=int(month),
                users_by_key=users_by_key,
                positions_by_key=positions_by_key,
                owner_user=users_by_key["owner"],
                intervals=intervals,
            ),
        )
        _merge_counts(
            counts,
            _create_reports(
                db,
                venue=venue,
                reference_year=int(year),
                reference_month=int(month),
                users_by_key=users_by_key,
                dictionaries=dictionaries,
            ),
        )
        _merge_counts(
            counts,
            _create_expenses(
                db,
                venue=venue,
                dictionaries=dictionaries,
                users_by_key=users_by_key,
                reference_year=int(year),
                reference_month=int(month),
            ),
        )
        _merge_counts(
            counts,
            _create_adjustments(
                db,
                venue=venue,
                users_by_key=users_by_key,
                owner_user=users_by_key["owner"],
                reference_year=int(year),
                reference_month=int(month),
            ),
        )
    counts.update(_configure_billing(db, venue=venue, owner_user=users_by_key["owner"]))

    db.flush()
    for year, month in periods:
        try:
            calc = calculate_payroll_for_month(
                db=db,
                venue_id=int(venue.id),
                month=f"{int(year):04d}-{int(month):02d}",
                calculated_by_user_id=int(users_by_key["owner"].id),
            )
            counts["payroll_runs"] = int(counts.get("payroll_runs", 0)) + 1
            counts["payroll_lines"] = int(counts.get("payroll_lines", 0)) + len(calc.lines or [])
            counts["payroll_total_amount_minor"] = int(counts.get("payroll_total_amount_minor", 0)) + (
                int(calc.run.total_amount_minor or 0) if getattr(calc, "run", None) is not None else 0
            )
        except Exception as exc:  # pragma: no cover - best effort seed
            warnings.append(f"Payroll bootstrap skipped for {int(year):04d}-{int(month):02d}: {exc}")

    db.flush()
    fixture_path = None
    if export_fixture_after:
        fixture = export_demo_fixture(db, venue_id=int(venue.id), fixture_path=export_fixture_path)
        fixture_path = fixture.fixture_path
        counts["fixture_tables"] = len(fixture.counts or {})
        if fixture.warnings:
            warnings.extend(fixture.warnings)

    return DemoBootstrapResult(
        venue_id=int(venue.id),
        venue_name=str(venue.name or ""),
        reference_year=int(reference_year),
        reference_month=int(reference_month),
        history_months=len(periods),
        period_start_year=int(period_start_year),
        period_start_month=int(period_start_month),
        fixture_path=fixture_path,
        counts=counts,
        warnings=warnings,
    )

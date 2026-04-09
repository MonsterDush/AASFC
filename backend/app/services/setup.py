from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.expense_category import ExpenseCategory
from app.models.kpi_metric import KpiMetric
from app.models.pay_profile import PayProfile
from app.models.payment_method import PaymentMethod
from app.models.recurring_expense_rule import RecurringExpenseRule
from app.models.shift_interval import ShiftInterval
from app.models.supplier import Supplier
from app.models.user import User
from app.models.venue_invite import VenueInvite
from app.models.venue_member import VenueMember
from app.models.venue_position import VenuePosition
from app.models.venue_setup_state import VenueSetupState

SETUP_WIZARD_VERSION = 1

SETUP_STATUS_NOT_STARTED = "NOT_STARTED"
SETUP_STATUS_IN_PROGRESS = "IN_PROGRESS"
SETUP_STATUS_PREPARE_DONE = "PREPARE_DONE"
SETUP_STATUS_EXTRA_IN_PROGRESS = "EXTRA_IN_PROGRESS"
SETUP_STATUS_DONE = "DONE"

SETUP_PHASE_PREPARE = "PREPARE"
SETUP_PHASE_EXTRA = "EXTRA"

STEP_STATUS_LOCKED = "LOCKED"
STEP_STATUS_AVAILABLE = "AVAILABLE"
STEP_STATUS_COMPLETED = "COMPLETED"
STEP_STATUS_SKIPPED = "SKIPPED"
STEP_STATUS_REQUIRES_ATTENTION = "REQUIRES_ATTENTION"

STEP_WELCOME = "welcome"
STEP_PAYMENT_METHODS = "payment_methods"
STEP_DEPARTMENTS = "departments"
STEP_KPI = "kpi"
STEP_PAY_PROFILES = "pay_profiles"
STEP_POSITIONS = "positions"
STEP_INVITES = "invites"
STEP_SHIFT_INTERVALS = "shift_intervals"
STEP_EXPENSE_CATEGORIES = "expense_categories"
STEP_SUPPLIERS = "suppliers"
STEP_RECURRING_EXPENSES = "recurring_expenses"

SETUP_STEPS: list[dict[str, Any]] = [
    {
        "key": STEP_WELCOME,
        "title": "Приветствие и название",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": False,
        "count_key": None,
        "skippable": False,
    },
    {
        "key": STEP_PAYMENT_METHODS,
        "title": "Способы оплат",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": True,
        "count_key": "payment_methods_count",
        "skippable": False,
    },
    {
        "key": STEP_DEPARTMENTS,
        "title": "Департаменты",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": True,
        "count_key": "departments_count",
        "skippable": False,
    },
    {
        "key": STEP_KPI,
        "title": "KPI и доп. продажи",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": True,
        "count_key": "kpi_count",
        "skippable": True,
    },
    {
        "key": STEP_PAY_PROFILES,
        "title": "Профили зарплат",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": True,
        "count_key": "pay_profiles_count",
        "skippable": False,
    },
    {
        "key": STEP_POSITIONS,
        "title": "Должности и права",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": True,
        "count_key": "positions_count",
        "skippable": False,
    },
    {
        "key": STEP_INVITES,
        "title": "Приглашение участников",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": True,
        "count_key": "team_targets_count",
        "skippable": True,
    },
    {
        "key": STEP_SHIFT_INTERVALS,
        "title": "Интервалы смен",
        "phase": SETUP_PHASE_PREPARE,
        "requires_data": True,
        "count_key": "shift_intervals_count",
        "skippable": False,
    },
    {
        "key": STEP_EXPENSE_CATEGORIES,
        "title": "Категории расходов",
        "phase": SETUP_PHASE_EXTRA,
        "requires_data": True,
        "count_key": "expense_categories_count",
        "skippable": True,
    },
    {
        "key": STEP_SUPPLIERS,
        "title": "Поставщики",
        "phase": SETUP_PHASE_EXTRA,
        "requires_data": True,
        "count_key": "suppliers_count",
        "skippable": True,
    },
    {
        "key": STEP_RECURRING_EXPENSES,
        "title": "Регулярные настройки",
        "phase": SETUP_PHASE_EXTRA,
        "requires_data": True,
        "count_key": "recurring_expenses_count",
        "skippable": True,
    },
]

STEP_BY_KEY = {item["key"]: item for item in SETUP_STEPS}
PREPARE_STEP_KEYS = [item["key"] for item in SETUP_STEPS if item["phase"] == SETUP_PHASE_PREPARE]
EXTRA_STEP_KEYS = [item["key"] for item in SETUP_STEPS if item["phase"] == SETUP_PHASE_EXTRA]
ALL_STEP_KEYS = [item["key"] for item in SETUP_STEPS]


def utcnow() -> datetime:
    return datetime.utcnow()


def _step_key_set(value: Any) -> set[str]:
    raw: Iterable[Any]
    if isinstance(value, dict):
        raw = value.keys()
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = []
    return {str(item).strip() for item in raw if str(item or "").strip() in STEP_BY_KEY}


def _step_meta_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _state_attr(state: Any, attr: str, default: Any = None) -> Any:
    if state is None:
        return default
    if isinstance(state, dict):
        return state.get(attr, default)
    return getattr(state, attr, default)


def _build_default_counts(venue_ids: Iterable[int]) -> dict[int, dict[str, int]]:
    return {
        int(venue_id): {
            "payment_methods_count": 0,
            "departments_count": 0,
            "kpi_count": 0,
            "pay_profiles_count": 0,
            "positions_count": 0,
            "team_members_count": 0,
            "pending_invites_count": 0,
            "team_targets_count": 0,
            "shift_intervals_count": 0,
            "expense_categories_count": 0,
            "suppliers_count": 0,
            "recurring_expenses_count": 0,
        }
        for venue_id in venue_ids
    }


def _apply_grouped_counts(db: Session, counts_map: dict[int, dict[str, int]], *, model: Any, key: str, filters: list[Any]) -> None:
    venue_ids = list(counts_map.keys())
    if not venue_ids:
        return
    rows = db.execute(
        select(model.venue_id, func.count(model.id))
        .where(model.venue_id.in_(venue_ids), *filters)
        .group_by(model.venue_id)
    ).all()
    for venue_id, count_value in rows:
        if int(venue_id) in counts_map:
            counts_map[int(venue_id)][key] = int(count_value or 0)


def _load_setup_counts_map(db: Session, venue_ids: Iterable[int]) -> dict[int, dict[str, int]]:
    clean_ids = [int(x) for x in dict.fromkeys(int(v) for v in venue_ids)]
    counts_map = _build_default_counts(clean_ids)
    if not clean_ids:
        return counts_map

    _apply_grouped_counts(db, counts_map, model=PaymentMethod, key="payment_methods_count", filters=[PaymentMethod.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=Department, key="departments_count", filters=[Department.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=KpiMetric, key="kpi_count", filters=[KpiMetric.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=PayProfile, key="pay_profiles_count", filters=[PayProfile.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=VenuePosition, key="positions_count", filters=[VenuePosition.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=ShiftInterval, key="shift_intervals_count", filters=[ShiftInterval.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=ExpenseCategory, key="expense_categories_count", filters=[ExpenseCategory.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=Supplier, key="suppliers_count", filters=[Supplier.is_active.is_(True)])
    _apply_grouped_counts(db, counts_map, model=RecurringExpenseRule, key="recurring_expenses_count", filters=[RecurringExpenseRule.is_active.is_(True)])
    _apply_grouped_counts(
        db,
        counts_map,
        model=VenueMember,
        key="team_members_count",
        filters=[VenueMember.is_active.is_(True), VenueMember.venue_role != "OWNER"],
    )
    _apply_grouped_counts(
        db,
        counts_map,
        model=VenueInvite,
        key="pending_invites_count",
        filters=[
            VenueInvite.is_active.is_(True),
            VenueInvite.accepted_at.is_(None),
            VenueInvite.revoked_at.is_(None),
            VenueInvite.venue_role != "OWNER",
        ],
    )
    for venue_id, row in counts_map.items():
        row["team_targets_count"] = int(row.get("team_members_count", 0) or 0) + int(row.get("pending_invites_count", 0) or 0)
    return counts_map


def get_setup_state(db: Session, *, venue_id: int) -> VenueSetupState | None:
    return db.execute(select(VenueSetupState).where(VenueSetupState.venue_id == int(venue_id))).scalar_one_or_none()


def get_or_create_setup_state(db: Session, *, venue_id: int) -> VenueSetupState:
    state = get_setup_state(db, venue_id=venue_id)
    if state is not None:
        return state
    state = VenueSetupState(
        venue_id=int(venue_id),
        wizard_version=SETUP_WIZARD_VERSION,
        status=SETUP_STATUS_NOT_STARTED,
        phase=SETUP_PHASE_PREPARE,
        current_step_key=STEP_WELCOME,
        completed_steps_json=[],
        skipped_steps_json=[],
        step_meta_json={},
    )
    db.add(state)
    db.flush()
    return state


def build_setup_summary_from_data(*, state: Any = None, counts: dict[str, int] | None = None) -> dict[str, Any]:
    counts = dict(counts or {})
    completed = _step_key_set(_state_attr(state, "completed_steps_json", []))
    skipped = _step_key_set(_state_attr(state, "skipped_steps_json", []))
    step_meta = _step_meta_dict(_state_attr(state, "step_meta_json", {}))
    current_step_key = _state_attr(state, "current_step_key")
    explicit_phase = str(_state_attr(state, "phase", SETUP_PHASE_PREPARE) or SETUP_PHASE_PREPARE).strip().upper()
    prepare_completed_at = _state_attr(state, "prepare_completed_at")
    done_at = _state_attr(state, "done_at")

    steps: list[dict[str, Any]] = []
    completed_count = 0
    resolved_count = 0
    prepare_resolved = 0
    extra_resolved = 0
    prepare_total = len(PREPARE_STEP_KEYS)
    extra_total = len(EXTRA_STEP_KEYS)

    for item in SETUP_STEPS:
        key = item["key"]
        count_key = item["count_key"]
        count_value = int(counts.get(count_key, 0) or 0) if count_key else 0
        data_ready = (count_value > 0) if item["requires_data"] else True
        is_skipped = key in skipped
        is_completed = key in completed
        if is_skipped:
            status = STEP_STATUS_SKIPPED
            is_valid = True
        elif is_completed and data_ready:
            status = STEP_STATUS_COMPLETED
            is_valid = True
        elif is_completed and not data_ready:
            status = STEP_STATUS_REQUIRES_ATTENTION
            is_valid = False
        else:
            status = STEP_STATUS_AVAILABLE
            is_valid = False

        if status == STEP_STATUS_COMPLETED:
            completed_count += 1
        if status in {STEP_STATUS_COMPLETED, STEP_STATUS_SKIPPED}:
            resolved_count += 1
            if item["phase"] == SETUP_PHASE_PREPARE:
                prepare_resolved += 1
            else:
                extra_resolved += 1

        step_payload = {
            "key": key,
            "title": item["title"],
            "phase": item["phase"],
            "skippable": bool(item["skippable"]),
            "requires_data": bool(item["requires_data"]),
            "count": count_value,
            "count_key": count_key,
            "data_ready": bool(data_ready),
            "status": status,
            "completed": status == STEP_STATUS_COMPLETED,
            "skipped": status == STEP_STATUS_SKIPPED,
            "requires_attention": status == STEP_STATUS_REQUIRES_ATTENTION,
            "meta": step_meta.get(key),
            "is_valid": is_valid,
        }
        steps.append(step_payload)

    prepare_done = prepare_resolved == prepare_total
    extra_done = extra_resolved == extra_total
    all_done = prepare_done and extra_done

    if all_done or done_at is not None:
        overall_status = SETUP_STATUS_DONE
    elif prepare_done and (explicit_phase == SETUP_PHASE_EXTRA or extra_resolved > 0):
        overall_status = SETUP_STATUS_EXTRA_IN_PROGRESS
    elif prepare_done or prepare_completed_at is not None:
        overall_status = SETUP_STATUS_PREPARE_DONE
    elif resolved_count > 0 or _state_attr(state, "started_at") is not None or current_step_key:
        overall_status = SETUP_STATUS_IN_PROGRESS
    else:
        overall_status = SETUP_STATUS_NOT_STARTED

    active_phase = SETUP_PHASE_EXTRA if overall_status in {SETUP_STATUS_PREPARE_DONE, SETUP_STATUS_EXTRA_IN_PROGRESS, SETUP_STATUS_DONE} else SETUP_PHASE_PREPARE
    if explicit_phase in {SETUP_PHASE_PREPARE, SETUP_PHASE_EXTRA}:
        active_phase = explicit_phase if overall_status != SETUP_STATUS_NOT_STARTED else SETUP_PHASE_PREPARE
        if overall_status == SETUP_STATUS_PREPARE_DONE:
            active_phase = SETUP_PHASE_EXTRA

    resume_step = None
    unresolved_prepare = [s for s in steps if s["phase"] == SETUP_PHASE_PREPARE and s["status"] in {STEP_STATUS_AVAILABLE, STEP_STATUS_REQUIRES_ATTENTION}]
    unresolved_extra = [s for s in steps if s["phase"] == SETUP_PHASE_EXTRA and s["status"] in {STEP_STATUS_AVAILABLE, STEP_STATUS_REQUIRES_ATTENTION}]
    current_step_obj = next((s for s in steps if s["key"] == current_step_key), None)
    if current_step_obj and current_step_obj["status"] in {STEP_STATUS_AVAILABLE, STEP_STATUS_REQUIRES_ATTENTION}:
        resume_step = current_step_obj["key"]
    elif overall_status in {SETUP_STATUS_NOT_STARTED, SETUP_STATUS_IN_PROGRESS}:
        resume_step = unresolved_prepare[0]["key"] if unresolved_prepare else None
    elif overall_status in {SETUP_STATUS_PREPARE_DONE, SETUP_STATUS_EXTRA_IN_PROGRESS}:
        resume_step = unresolved_extra[0]["key"] if unresolved_extra else None

    return {
        "wizard_version": int(_state_attr(state, "wizard_version", SETUP_WIZARD_VERSION) or SETUP_WIZARD_VERSION),
        "status": overall_status,
        "phase": active_phase,
        "current_step_key": current_step_key,
        "resume_step": resume_step,
        "prepare_done": prepare_done,
        "extra_done": extra_done,
        "progress_total": len(SETUP_STEPS),
        "progress_done": completed_count,
        "progress_resolved": resolved_count,
        "prepare_total": prepare_total,
        "prepare_resolved": prepare_resolved,
        "extra_total": extra_total,
        "extra_resolved": extra_resolved,
        "steps": steps,
        "counts": counts,
        "started_at": _state_attr(state, "started_at"),
        "updated_at": _state_attr(state, "updated_at"),
        "prepare_completed_at": prepare_completed_at,
        "done_at": done_at,
        "completed_steps": sorted(completed),
        "skipped_steps": sorted(skipped),
        "step_meta": step_meta,
    }


def build_setup_summary(db: Session, *, venue_id: int, create_missing: bool = False) -> dict[str, Any]:
    state = get_or_create_setup_state(db, venue_id=venue_id) if create_missing else get_setup_state(db, venue_id=venue_id)
    counts = _load_setup_counts_map(db, [venue_id]).get(int(venue_id), {})
    summary = build_setup_summary_from_data(state=state, counts=counts)
    if state is not None:
        summary["venue_id"] = int(state.venue_id)
        summary["state_id"] = int(state.id)
    else:
        summary["venue_id"] = int(venue_id)
        summary["state_id"] = None
    return summary


def build_setup_summary_map(db: Session, venue_ids: Iterable[int], *, create_missing: bool = False) -> dict[int, dict[str, Any]]:
    clean_ids = [int(x) for x in dict.fromkeys(int(v) for v in venue_ids)]
    counts_map = _load_setup_counts_map(db, clean_ids)
    states_by_venue: dict[int, VenueSetupState] = {}
    if clean_ids:
        if create_missing:
            for venue_id in clean_ids:
                state = get_or_create_setup_state(db, venue_id=venue_id)
                states_by_venue[int(venue_id)] = state
        else:
            rows = db.execute(select(VenueSetupState).where(VenueSetupState.venue_id.in_(clean_ids))).scalars().all()
            states_by_venue = {int(row.venue_id): row for row in rows}
    out: dict[int, dict[str, Any]] = {}
    for venue_id in clean_ids:
        summary = build_setup_summary_from_data(state=states_by_venue.get(int(venue_id)), counts=counts_map.get(int(venue_id), {}))
        state = states_by_venue.get(int(venue_id))
        summary["venue_id"] = int(venue_id)
        summary["state_id"] = int(state.id) if state is not None else None
        out[int(venue_id)] = summary
    return out


def _write_summary_back_to_state(state: VenueSetupState, summary: dict[str, Any]) -> None:
    now = utcnow()
    state.wizard_version = int(summary.get("wizard_version") or SETUP_WIZARD_VERSION)
    state.status = str(summary.get("status") or SETUP_STATUS_NOT_STARTED)
    state.phase = str(summary.get("phase") or SETUP_PHASE_PREPARE)
    state.current_step_key = summary.get("resume_step") or summary.get("current_step_key") or state.current_step_key
    if state.status == SETUP_STATUS_NOT_STARTED and state.started_at is None:
        state.current_step_key = STEP_WELCOME
    if summary.get("prepare_done") and state.prepare_completed_at is None:
        state.prepare_completed_at = now
    if summary.get("status") == SETUP_STATUS_DONE and state.done_at is None:
        state.done_at = now
    if state.started_at is None and state.status != SETUP_STATUS_NOT_STARTED:
        state.started_at = now
    state.updated_at = now


def sync_setup_state(db: Session, state: VenueSetupState) -> dict[str, Any]:
    summary = build_setup_summary(db, venue_id=int(state.venue_id), create_missing=False)
    _write_summary_back_to_state(state, summary)
    db.flush()
    return build_setup_summary(db, venue_id=int(state.venue_id), create_missing=False)


def _ensure_known_step(step_key: str) -> str:
    normalized = str(step_key or "").strip()
    if normalized not in STEP_BY_KEY:
        raise ValueError("Bad step_key")
    return normalized


def start_setup(db: Session, *, venue_id: int, seen_by_user: User | None = None) -> dict[str, Any]:
    state = get_or_create_setup_state(db, venue_id=venue_id)
    now = utcnow()
    if state.started_at is None:
        state.started_at = now
    state.updated_at = now
    state.status = SETUP_STATUS_IN_PROGRESS
    state.phase = SETUP_PHASE_PREPARE
    state.current_step_key = state.current_step_key or STEP_WELCOME
    if seen_by_user is not None:
        state.last_seen_by_user_id = int(seen_by_user.id)
    db.flush()
    return sync_setup_state(db, state)


def patch_setup_state(
    db: Session,
    *,
    venue_id: int,
    current_step_key: str | None = None,
    phase: str | None = None,
    step_meta: dict[str, Any] | None = None,
    seen_by_user: User | None = None,
) -> dict[str, Any]:
    state = get_or_create_setup_state(db, venue_id=venue_id)
    if current_step_key is not None:
        state.current_step_key = _ensure_known_step(current_step_key)
    if phase is not None:
        phase_upper = str(phase or "").strip().upper()
        if phase_upper not in {SETUP_PHASE_PREPARE, SETUP_PHASE_EXTRA}:
            raise ValueError("Bad phase")
        state.phase = phase_upper
    if step_meta is not None:
        merged = _step_meta_dict(state.step_meta_json)
        merged.update(dict(step_meta))
        state.step_meta_json = merged
    if seen_by_user is not None:
        state.last_seen_by_user_id = int(seen_by_user.id)
    state.updated_at = utcnow()
    db.flush()
    return sync_setup_state(db, state)


def _can_skip_step(step_key: str) -> bool:
    return bool(STEP_BY_KEY[step_key].get("skippable"))


def _step_has_required_data(summary: dict[str, Any], step_key: str) -> bool:
    step = next((item for item in summary.get("steps", []) if item.get("key") == step_key), None)
    if step is None:
        return False
    return bool(step.get("data_ready")) or not bool(step.get("requires_data"))


def complete_setup_step(db: Session, *, venue_id: int, step_key: str, seen_by_user: User | None = None) -> dict[str, Any]:
    key = _ensure_known_step(step_key)
    state = get_or_create_setup_state(db, venue_id=venue_id)
    preview = build_setup_summary(db, venue_id=venue_id, create_missing=False)
    if not _step_has_required_data(preview, key):
        raise ValueError("Step data is not ready")
    completed = _step_key_set(state.completed_steps_json)
    skipped = _step_key_set(state.skipped_steps_json)
    completed.add(key)
    skipped.discard(key)
    state.completed_steps_json = sorted(completed)
    state.skipped_steps_json = sorted(skipped)
    state.current_step_key = key
    if seen_by_user is not None:
        state.last_seen_by_user_id = int(seen_by_user.id)
    state.updated_at = utcnow()
    db.flush()
    summary = sync_setup_state(db, state)
    next_step = summary.get("resume_step")
    if next_step:
        state.current_step_key = str(next_step)
        state.updated_at = utcnow()
        db.flush()
        summary = build_setup_summary(db, venue_id=venue_id, create_missing=False)
    return summary


def skip_setup_step(db: Session, *, venue_id: int, step_key: str, seen_by_user: User | None = None) -> dict[str, Any]:
    key = _ensure_known_step(step_key)
    if not _can_skip_step(key):
        raise ValueError("Step is not skippable")
    state = get_or_create_setup_state(db, venue_id=venue_id)
    completed = _step_key_set(state.completed_steps_json)
    skipped = _step_key_set(state.skipped_steps_json)
    skipped.add(key)
    completed.discard(key)
    state.completed_steps_json = sorted(completed)
    state.skipped_steps_json = sorted(skipped)
    state.current_step_key = key
    if seen_by_user is not None:
        state.last_seen_by_user_id = int(seen_by_user.id)
    state.updated_at = utcnow()
    db.flush()
    summary = sync_setup_state(db, state)
    next_step = summary.get("resume_step")
    if next_step:
        state.current_step_key = str(next_step)
        state.updated_at = utcnow()
        db.flush()
        summary = build_setup_summary(db, venue_id=venue_id, create_missing=False)
    return summary


def reset_setup_step(db: Session, *, venue_id: int, step_key: str, seen_by_user: User | None = None) -> dict[str, Any]:
    key = _ensure_known_step(step_key)
    state = get_or_create_setup_state(db, venue_id=venue_id)
    completed = _step_key_set(state.completed_steps_json)
    skipped = _step_key_set(state.skipped_steps_json)
    completed.discard(key)
    skipped.discard(key)
    state.completed_steps_json = sorted(completed)
    state.skipped_steps_json = sorted(skipped)
    state.current_step_key = key
    if seen_by_user is not None:
        state.last_seen_by_user_id = int(seen_by_user.id)
    state.updated_at = utcnow()
    db.flush()
    return sync_setup_state(db, state)


def finish_prepare_setup(db: Session, *, venue_id: int, seen_by_user: User | None = None) -> dict[str, Any]:
    state = get_or_create_setup_state(db, venue_id=venue_id)
    summary = build_setup_summary(db, venue_id=venue_id, create_missing=False)
    if not bool(summary.get("prepare_done")):
        raise ValueError("Prepare phase is not completed")
    state.prepare_completed_at = state.prepare_completed_at or utcnow()
    state.phase = SETUP_PHASE_EXTRA
    if seen_by_user is not None:
        state.last_seen_by_user_id = int(seen_by_user.id)
    state.updated_at = utcnow()
    db.flush()
    return sync_setup_state(db, state)


def finish_extra_setup(db: Session, *, venue_id: int, seen_by_user: User | None = None) -> dict[str, Any]:
    state = get_or_create_setup_state(db, venue_id=venue_id)
    summary = build_setup_summary(db, venue_id=venue_id, create_missing=False)
    if not bool(summary.get("prepare_done")):
        raise ValueError("Prepare phase is not completed")
    if not bool(summary.get("extra_done")):
        raise ValueError("Extra phase is not completed")
    state.prepare_completed_at = state.prepare_completed_at or utcnow()
    state.done_at = state.done_at or utcnow()
    state.phase = SETUP_PHASE_EXTRA
    if seen_by_user is not None:
        state.last_seen_by_user_id = int(seen_by_user.id)
    state.updated_at = utcnow()
    db.flush()
    return sync_setup_state(db, state)

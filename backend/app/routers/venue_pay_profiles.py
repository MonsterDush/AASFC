from fastapi import APIRouter

from app.routers.venue_core import (
    Department,
    Depends,
    HTTPException,
    KpiMetric,
    MINIMUM_GUARANTEE_MONTH,
    PAY_COMPONENT_TYPES,
    PayComponent,
    PayComponentCreateIn,
    PayComponentUpdateIn,
    PayProfile,
    PayProfileAssignment,
    PayProfileAssignmentCreateIn,
    PayProfileAssignmentUpdateIn,
    PayProfileCreateIn,
    PayProfileUpdateIn,
    PayrollLine,
    Query,
    Session,
    User,
    VenueMember,
    _component_boost_department_ids,
    _component_department_ids,
    _dump_int_ids,
    _ensure_department_ids_in_venue,
    _get_pay_component_or_404,
    _get_pay_profile_assignment_or_404,
    _get_pay_profile_or_404,
    _load_pay_profile_detail,
    _normalize_int_ids,
    _normalize_minimum_guarantee_scope,
    _parse_json_text,
    _require_active_member_or_admin,
    _require_pay_profiles_manage,
    _require_pay_profiles_view,
    _serialize_pay_component,
    _serialize_pay_profile,
    _serialize_pay_profile_assignment,
    _validate_pay_component_fields,
    datetime,
    func,
    get_current_user,
    get_db,
    json,
    sa,
    select,
)


router = APIRouter()


@router.get("/{venue_id}/pay-profiles")
def list_pay_profiles(
    venue_id: int,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_view(db, venue_id=venue_id, user=user)

    stmt = select(PayProfile).where(PayProfile.venue_id == venue_id).order_by(PayProfile.is_active.desc(), PayProfile.title.asc(), PayProfile.id.asc())
    if not include_inactive:
        stmt = stmt.where(PayProfile.is_active.is_(True))
    profiles = db.execute(stmt).scalars().all()
    profile_ids = [int(profile.id) for profile in profiles]

    components_counts = {
        int(profile_id): int(count or 0)
        for profile_id, count in db.execute(
            select(PayComponent.pay_profile_id, func.count(PayComponent.id))
            .where(PayComponent.venue_id == venue_id, PayComponent.pay_profile_id.in_(profile_ids) if profile_ids else sa.true())
            .group_by(PayComponent.pay_profile_id)
        ).all()
    } if profile_ids else {}

    assignments_counts = {
        int(profile_id): int(count or 0)
        for profile_id, count in db.execute(
            select(PayProfileAssignment.pay_profile_id, func.count(PayProfileAssignment.id))
            .where(PayProfileAssignment.venue_id == venue_id, PayProfileAssignment.pay_profile_id.in_(profile_ids) if profile_ids else sa.true())
            .group_by(PayProfileAssignment.pay_profile_id)
        ).all()
    } if profile_ids else {}

    return [
        _serialize_pay_profile(
            profile,
            components_count=components_counts.get(int(profile.id), 0),
            assignments_count=assignments_counts.get(int(profile.id), 0),
        )
        for profile in profiles
    ]


@router.get("/{venue_id}/pay-profiles/{profile_id}")
def get_pay_profile(
    venue_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_view(db, venue_id=venue_id, user=user)
    return _load_pay_profile_detail(db, venue_id=venue_id, profile_id=profile_id)


@router.post("/{venue_id}/pay-profiles")
def create_pay_profile(
    venue_id: int,
    payload: PayProfileCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    profile = PayProfile(
        venue_id=venue_id,
        title=payload.title.strip(),
        description=(payload.description or None),
        is_active=payload.is_active,
        updated_at=datetime.utcnow(),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _serialize_pay_profile(profile, components_count=0, assignments_count=0)


@router.patch("/{venue_id}/pay-profiles/{profile_id}")
def update_pay_profile(
    venue_id: int,
    profile_id: int,
    payload: PayProfileUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    fields_set = getattr(payload, 'model_fields_set', getattr(payload, '__fields_set__', set()))
    if 'title' in fields_set and payload.title is not None:
        profile.title = payload.title.strip()
    if 'description' in fields_set:
        profile.description = payload.description or None
    if 'is_active' in fields_set and payload.is_active is not None:
        profile.is_active = payload.is_active
    profile.updated_at = datetime.utcnow()
    db.commit()
    return _load_pay_profile_detail(db, venue_id=venue_id, profile_id=profile_id)


@router.delete("/{venue_id}/pay-profiles/{profile_id}")
def delete_pay_profile(
    venue_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    used = db.execute(select(PayrollLine.id).where(PayrollLine.pay_profile_id == profile_id).limit(1)).scalar_one_or_none()
    if used is not None:
        raise HTTPException(status_code=400, detail="Pay profile is already used in payroll runs. Archive it instead of deleting.")

    db.delete(profile)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/pay-profiles/{profile_id}/assignments")
def create_pay_profile_assignment(
    venue_id: int,
    profile_id: int,
    payload: PayProfileAssignmentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)
    _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    if payload.start_date and payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == payload.member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=400, detail="Member not found in venue")

    assignment = PayProfileAssignment(
        venue_id=venue_id,
        pay_profile_id=profile_id,
        member_user_id=payload.member_user_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_active=payload.is_active,
        updated_at=datetime.utcnow(),
    )
    db.add(assignment)
    db.commit()
    member = db.execute(select(User).where(User.id == payload.member_user_id)).scalar_one_or_none()
    return _serialize_pay_profile_assignment(assignment, member=member)


@router.patch("/{venue_id}/pay-profile-assignments/{assignment_id}")
def update_pay_profile_assignment(
    venue_id: int,
    assignment_id: int,
    payload: PayProfileAssignmentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    assignment = _get_pay_profile_assignment_or_404(db, venue_id=venue_id, assignment_id=assignment_id)
    fields_set = getattr(payload, 'model_fields_set', getattr(payload, '__fields_set__', set()))
    new_start_date = payload.start_date if 'start_date' in fields_set else assignment.start_date
    new_end_date = payload.end_date if 'end_date' in fields_set else assignment.end_date
    if new_start_date and new_end_date and new_end_date < new_start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    if 'start_date' in fields_set:
        assignment.start_date = payload.start_date
    if 'end_date' in fields_set:
        assignment.end_date = payload.end_date
    if 'is_active' in fields_set and payload.is_active is not None:
        assignment.is_active = payload.is_active
    assignment.updated_at = datetime.utcnow()
    db.commit()
    member = db.execute(select(User).where(User.id == assignment.member_user_id)).scalar_one_or_none()
    return _serialize_pay_profile_assignment(assignment, member=member)


@router.delete("/{venue_id}/pay-profile-assignments/{assignment_id}")
def delete_pay_profile_assignment(
    venue_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    assignment = _get_pay_profile_assignment_or_404(db, venue_id=venue_id, assignment_id=assignment_id)
    db.delete(assignment)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/pay-profiles/{profile_id}/components")
def create_pay_component(
    venue_id: int,
    profile_id: int,
    payload: PayComponentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)
    _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)

    component_type = payload.component_type.strip().upper()
    if component_type not in PAY_COMPONENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported pay component type")

    if payload.department_id is not None:
        dep = db.execute(select(Department.id).where(Department.id == payload.department_id, Department.venue_id == venue_id)).scalar_one_or_none()
        if dep is None:
            raise HTTPException(status_code=400, detail="Department not found in venue")
    if payload.kpi_metric_id is not None:
        kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
        if kpi is None:
            raise HTTPException(status_code=400, detail="KPI metric not found in venue")
    if payload.boost_department_id is not None:
        dep = db.execute(select(Department.id).where(Department.id == payload.boost_department_id, Department.venue_id == venue_id)).scalar_one_or_none()
        if dep is None:
            raise HTTPException(status_code=400, detail="Boost department not found in venue")
    department_ids = _normalize_int_ids(payload.department_ids)
    boost_department_ids = _normalize_int_ids(payload.boost_department_ids)
    _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=department_ids, detail="Departments not found in venue")
    _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=boost_department_ids, detail="Boost departments not found in venue")
    if payload.boost_kpi_metric_id is not None:
        kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.boost_kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
        if kpi is None:
            raise HTTPException(status_code=400, detail="Boost KPI metric not found in venue")
    _validate_pay_component_fields(
        component_type=component_type,
        amount_minor=payload.amount_minor,
        rate_minor=payload.rate_minor,
        percent_bps=payload.percent_bps,
        department_id=payload.department_id,
        department_ids=department_ids,
        kpi_metric_id=payload.kpi_metric_id,
        threshold_value=payload.threshold_value,
        steps_json=payload.steps_json,
        base_scope=payload.base_scope,
        boost_enabled=payload.boost_enabled,
        boost_percent_bps=payload.boost_percent_bps,
        boost_source_type=payload.boost_source_type,
        boost_recalc_mode=payload.boost_recalc_mode,
        boost_department_id=payload.boost_department_id,
        boost_department_ids=boost_department_ids,
        boost_kpi_metric_id=payload.boost_kpi_metric_id,
        boost_threshold_value=payload.boost_threshold_value,
        minimum_guarantee_minor=payload.minimum_guarantee_minor,
        minimum_guarantee_scope=payload.minimum_guarantee_scope,
        maximum_cap_minor=payload.maximum_cap_minor,
    )

    component = PayComponent(
        venue_id=venue_id,
        pay_profile_id=profile_id,
        component_type=component_type,
        title=payload.title.strip(),
        amount_minor=payload.amount_minor,
        rate_minor=payload.rate_minor,
        percent_bps=payload.percent_bps,
        department_id=payload.department_id or (department_ids[0] if department_ids else None),
        department_ids_json=_dump_int_ids(department_ids),
        kpi_metric_id=payload.kpi_metric_id,
        threshold_value=payload.threshold_value,
        steps_json=json.dumps(payload.steps_json, ensure_ascii=False) if payload.steps_json is not None else None,
        base_scope=(payload.base_scope or '').strip().upper() or None,
        boost_enabled=bool(payload.boost_enabled),
        boost_percent_bps=payload.boost_percent_bps,
        boost_source_type=(payload.boost_source_type or '').strip().upper() or None,
        boost_recalc_mode=(payload.boost_recalc_mode or '').strip().upper() or None,
        boost_department_id=payload.boost_department_id or (boost_department_ids[0] if boost_department_ids else None),
        boost_department_ids_json=_dump_int_ids(boost_department_ids),
        boost_kpi_metric_id=payload.boost_kpi_metric_id,
        boost_threshold_value=payload.boost_threshold_value,
        minimum_guarantee_minor=payload.minimum_guarantee_minor,
        minimum_guarantee_scope=(
            _normalize_minimum_guarantee_scope(payload.minimum_guarantee_scope)
            if component_type == "MINIMUM_PAYOUT" or payload.minimum_guarantee_minor is not None
            else None
        ),
        maximum_cap_minor=payload.maximum_cap_minor,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        updated_at=datetime.utcnow(),
    )
    db.add(component)
    db.commit()
    return _serialize_pay_component(component)


@router.patch("/{venue_id}/pay-components/{component_id}")
def update_pay_component(
    venue_id: int,
    component_id: int,
    payload: PayComponentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    component = _get_pay_component_or_404(db, venue_id=venue_id, component_id=component_id)
    fields_set = getattr(payload, 'model_fields_set', getattr(payload, '__fields_set__', set()))
    if 'component_type' in fields_set and payload.component_type is not None:
        new_component_type = payload.component_type.strip().upper()
        if new_component_type not in PAY_COMPONENT_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported pay component type")
        component.component_type = new_component_type
    if 'title' in fields_set and payload.title is not None:
        component.title = payload.title.strip()
    if 'amount_minor' in fields_set:
        component.amount_minor = payload.amount_minor
    if 'rate_minor' in fields_set:
        component.rate_minor = payload.rate_minor
    if 'percent_bps' in fields_set:
        component.percent_bps = payload.percent_bps
    if 'department_id' in fields_set:
        if payload.department_id is None:
            component.department_id = None
        else:
            dep = db.execute(select(Department.id).where(Department.id == payload.department_id, Department.venue_id == venue_id)).scalar_one_or_none()
            if dep is None:
                raise HTTPException(status_code=400, detail="Department not found in venue")
            component.department_id = payload.department_id
    if 'department_ids' in fields_set:
        department_ids_payload = _normalize_int_ids(payload.department_ids)
        _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=department_ids_payload, detail="Departments not found in venue")
        component.department_ids_json = _dump_int_ids(department_ids_payload)
        if 'department_id' not in fields_set:
            component.department_id = department_ids_payload[0] if department_ids_payload else None
    if 'kpi_metric_id' in fields_set:
        if payload.kpi_metric_id is None:
            component.kpi_metric_id = None
        else:
            kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
            if kpi is None:
                raise HTTPException(status_code=400, detail="KPI metric not found in venue")
            component.kpi_metric_id = payload.kpi_metric_id
    if 'boost_department_id' in fields_set:
        if payload.boost_department_id is None:
            component.boost_department_id = None
        else:
            dep = db.execute(select(Department.id).where(Department.id == payload.boost_department_id, Department.venue_id == venue_id)).scalar_one_or_none()
            if dep is None:
                raise HTTPException(status_code=400, detail="Boost department not found in venue")
            component.boost_department_id = payload.boost_department_id
    if 'boost_department_ids' in fields_set:
        boost_department_ids_payload = _normalize_int_ids(payload.boost_department_ids)
        _ensure_department_ids_in_venue(db, venue_id=venue_id, ids=boost_department_ids_payload, detail="Boost departments not found in venue")
        component.boost_department_ids_json = _dump_int_ids(boost_department_ids_payload)
        if 'boost_department_id' not in fields_set:
            component.boost_department_id = boost_department_ids_payload[0] if boost_department_ids_payload else None
    if 'boost_kpi_metric_id' in fields_set:
        if payload.boost_kpi_metric_id is None:
            component.boost_kpi_metric_id = None
        else:
            kpi = db.execute(select(KpiMetric.id).where(KpiMetric.id == payload.boost_kpi_metric_id, KpiMetric.venue_id == venue_id)).scalar_one_or_none()
            if kpi is None:
                raise HTTPException(status_code=400, detail="Boost KPI metric not found in venue")
            component.boost_kpi_metric_id = payload.boost_kpi_metric_id
    if 'threshold_value' in fields_set:
        component.threshold_value = payload.threshold_value
    if 'steps_json' in fields_set:
        component.steps_json = json.dumps(payload.steps_json, ensure_ascii=False) if payload.steps_json is not None else None
    if 'base_scope' in fields_set:
        component.base_scope = (payload.base_scope or '').strip().upper() or None
    if 'boost_enabled' in fields_set:
        component.boost_enabled = bool(payload.boost_enabled)
    if 'boost_percent_bps' in fields_set:
        component.boost_percent_bps = payload.boost_percent_bps
    if 'boost_source_type' in fields_set:
        component.boost_source_type = (payload.boost_source_type or '').strip().upper() or None
    if 'boost_recalc_mode' in fields_set:
        component.boost_recalc_mode = (payload.boost_recalc_mode or '').strip().upper() or None
    if 'boost_threshold_value' in fields_set:
        component.boost_threshold_value = payload.boost_threshold_value
    if 'minimum_guarantee_minor' in fields_set:
        component.minimum_guarantee_minor = payload.minimum_guarantee_minor
        if payload.minimum_guarantee_minor is None and 'minimum_guarantee_scope' not in fields_set:
            component.minimum_guarantee_scope = None
    if 'minimum_guarantee_scope' in fields_set:
        component.minimum_guarantee_scope = (
            _normalize_minimum_guarantee_scope(payload.minimum_guarantee_scope)
            if str(component.component_type or "").strip().upper() == "MINIMUM_PAYOUT" or component.minimum_guarantee_minor is not None
            else None
        )
    elif str(component.component_type or "").strip().upper() == "MINIMUM_PAYOUT" and not component.minimum_guarantee_scope:
        component.minimum_guarantee_scope = MINIMUM_GUARANTEE_MONTH
    elif component.minimum_guarantee_minor is not None and not component.minimum_guarantee_scope:
        component.minimum_guarantee_scope = MINIMUM_GUARANTEE_MONTH
    if 'maximum_cap_minor' in fields_set:
        component.maximum_cap_minor = payload.maximum_cap_minor
    if 'sort_order' in fields_set and payload.sort_order is not None:
        component.sort_order = payload.sort_order
    if 'is_active' in fields_set and payload.is_active is not None:
        component.is_active = payload.is_active
    _validate_pay_component_fields(
        component_type=component.component_type,
        amount_minor=component.amount_minor,
        rate_minor=component.rate_minor,
        percent_bps=component.percent_bps,
        department_id=component.department_id,
        department_ids=_component_department_ids(component),
        kpi_metric_id=component.kpi_metric_id,
        threshold_value=component.threshold_value,
        steps_json=_parse_json_text(component.steps_json),
        base_scope=component.base_scope,
        boost_enabled=bool(component.boost_enabled),
        boost_percent_bps=component.boost_percent_bps,
        boost_source_type=component.boost_source_type,
        boost_recalc_mode=component.boost_recalc_mode,
        boost_department_id=component.boost_department_id,
        boost_department_ids=_component_boost_department_ids(component),
        boost_kpi_metric_id=component.boost_kpi_metric_id,
        boost_threshold_value=component.boost_threshold_value,
        minimum_guarantee_minor=component.minimum_guarantee_minor,
        minimum_guarantee_scope=component.minimum_guarantee_scope,
        maximum_cap_minor=component.maximum_cap_minor,
    )
    component.updated_at = datetime.utcnow()
    db.commit()
    return _serialize_pay_component(component)


@router.delete("/{venue_id}/pay-components/{component_id}")
def delete_pay_component(
    venue_id: int,
    component_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)

    component = _get_pay_component_or_404(db, venue_id=venue_id, component_id=component_id)
    db.delete(component)
    db.commit()
    return {"ok": True}


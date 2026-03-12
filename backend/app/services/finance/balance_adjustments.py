from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import BalanceAdjustment
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source


def rebuild_balance_adjustment_entries(*, db: Session, adjustment: BalanceAdjustment) -> int:
    if adjustment.id is None:
        raise ValueError("BalanceAdjustment must be flushed before ledger rebuild")

    delete_finance_entries_for_source(db=db, source_type="balance_adjustment", source_id=int(adjustment.id))

    status = str(getattr(adjustment, 'status', 'CONFIRMED') or 'CONFIRMED').upper()
    if status != 'CONFIRMED':
        return 0

    delta_minor = int(adjustment.delta_minor or 0)
    if delta_minor == 0:
        return 0

    create_finance_entry(
        db=db,
        venue_id=int(adjustment.venue_id),
        entry_date=adjustment.adjustment_date,
        amount_minor=abs(delta_minor),
        direction='INCOME' if delta_minor > 0 else 'EXPENSE',
        kind='BALANCE_ADJUSTMENT',
        source_type='balance_adjustment',
        source_id=int(adjustment.id),
        payment_method_id=int(adjustment.payment_method_id),
        meta_json={
            'adjustment_date': adjustment.adjustment_date.isoformat(),
            'reason': adjustment.reason,
            'comment': adjustment.comment,
            'delta_minor': delta_minor,
        },
    )
    return 1


def delete_balance_adjustment_entries(*, db: Session, adjustment_id: int) -> int:
    return delete_finance_entries_for_source(db=db, source_type='balance_adjustment', source_id=int(adjustment_id))

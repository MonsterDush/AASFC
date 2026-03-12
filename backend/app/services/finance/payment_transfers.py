from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import PaymentMethodTransfer
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source


def rebuild_payment_method_transfer_entries(*, db: Session, transfer: PaymentMethodTransfer) -> int:
    if transfer.id is None:
        raise ValueError("PaymentMethodTransfer must be flushed before ledger rebuild")

    delete_finance_entries_for_source(db=db, source_type="payment_method_transfer", source_id=int(transfer.id))

    status = str(getattr(transfer, 'status', 'CONFIRMED') or 'CONFIRMED').upper()
    if status != 'CONFIRMED':
        return 0

    amount_minor = int(transfer.amount_minor or 0)
    if amount_minor <= 0:
        return 0

    meta_common = {
        'transfer_date': transfer.transfer_date.isoformat(),
        'comment': transfer.comment,
        'from_payment_method_id': int(transfer.from_payment_method_id),
        'to_payment_method_id': int(transfer.to_payment_method_id),
    }

    create_finance_entry(
        db=db,
        venue_id=int(transfer.venue_id),
        entry_date=transfer.transfer_date,
        amount_minor=amount_minor,
        direction='EXPENSE',
        kind='TRANSFER',
        source_type='payment_method_transfer',
        source_id=int(transfer.id),
        payment_method_id=int(transfer.from_payment_method_id),
        meta_json={**meta_common, 'side': 'OUT'},
    )
    create_finance_entry(
        db=db,
        venue_id=int(transfer.venue_id),
        entry_date=transfer.transfer_date,
        amount_minor=amount_minor,
        direction='INCOME',
        kind='TRANSFER',
        source_type='payment_method_transfer',
        source_id=int(transfer.id),
        payment_method_id=int(transfer.to_payment_method_id),
        meta_json={**meta_common, 'side': 'IN'},
    )
    return 2


def delete_payment_method_transfer_entries(*, db: Session, transfer_id: int) -> int:
    return delete_finance_entries_for_source(db=db, source_type='payment_method_transfer', source_id=int(transfer_id))

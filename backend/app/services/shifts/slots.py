from __future__ import annotations

SHIFT_SLOT_DAY = "DAY"
SHIFT_SLOT_NIGHT = "NIGHT"
_SHIFT_SLOTS = {SHIFT_SLOT_DAY, SHIFT_SLOT_NIGHT}


def normalize_shift_slot(value: str | None) -> str:
    slot = str(value or SHIFT_SLOT_DAY).strip().upper()
    if slot not in _SHIFT_SLOTS:
        return SHIFT_SLOT_DAY
    return slot

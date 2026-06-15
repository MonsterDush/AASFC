def normalize_tg_username(value: str) -> str:
    v = (value or "").strip()
    if v.startswith("@"):
        v = v[1:]
    return v.lower()

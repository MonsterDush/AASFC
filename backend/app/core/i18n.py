from __future__ import annotations

from typing import Any


SUPPORTED_LOCALES = frozenset({"ru", "en"})
DEFAULT_LOCALE = "ru"


def normalize_locale(value: Any, *, default: str | None = DEFAULT_LOCALE) -> str | None:
    locale = str(value or "").strip().lower().replace("_", "-").split("-", 1)[0]
    if locale in SUPPORTED_LOCALES:
        return locale
    return default


def user_locale(user: Any, *, default: str = DEFAULT_LOCALE) -> str:
    return normalize_locale(getattr(user, "preferred_locale", None), default=default) or default


def localized(locale: str | None, *, ru: str, en: str) -> str:
    return en if normalize_locale(locale) == "en" else ru

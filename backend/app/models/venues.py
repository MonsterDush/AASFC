"""Compatibility alias for the venue router module.

This file used to blur the boundary between the model layer and router layer by
re-exporting everything from ``app.routers.venues`` via ``import *``.
Keep the alias tiny and explicit so there is no second implementation here.
Prefer importing from ``app.routers.venues`` directly in new code.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_TARGET = "app.routers.venues"


def __getattr__(name: str) -> Any:
    return getattr(import_module(_TARGET), name)

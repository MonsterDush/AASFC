"""Deprecated compatibility shim.

Legacy API/router code used to live in ``app.models.venues``.
The canonical implementation is now in ``app.routers.venues``.
Keep this file tiny so there is no second source of truth.
"""

from app.routers.venues import *  # noqa: F401,F403

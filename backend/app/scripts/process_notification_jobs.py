"""Process queued notification jobs.

Run periodically (e.g. every minute) to retry/flush background notification jobs.
This is safe to run alongside the in-request FastAPI BackgroundTasks trigger.
"""

from __future__ import annotations

from app.routers.venues import process_pending_notification_jobs_once


def main() -> int:
    processed = process_pending_notification_jobs_once(50)
    print(f"processed={processed}")
    return processed


if __name__ == "__main__":
    raise SystemExit(0 if main() >= 0 else 1)

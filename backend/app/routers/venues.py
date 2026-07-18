from fastapi import APIRouter

from app.routers.venue_adjustments import router as adjustments_router
from app.routers.venue_catalogs import router as catalogs_router
from app.routers.venue_core import process_pending_notification_jobs_once, router as core_router
from app.routers.venue_economics import router as economics_router
from app.routers.venue_finance import router as finance_router
from app.routers.venue_membership import router as membership_router
from app.routers.venue_pay_profiles import router as pay_profiles_router
from app.routers.venue_payroll import router as payroll_router
from app.routers.venue_positions import router as positions_router
from app.routers.venue_reports import router as reports_router
from app.routers.venue_revenue_exports import router as revenue_exports_router
from app.routers.venue_schedule_templates import router as schedule_templates_router
from app.routers.venue_shift_intervals import router as shift_intervals_router
from app.routers.venue_shifts import router as shifts_router


router = APIRouter()
router.include_router(core_router)
router.include_router(positions_router, prefix="/venues", tags=["venues"])
router.include_router(pay_profiles_router, prefix="/venues", tags=["venues"])
router.include_router(payroll_router, prefix="/venues", tags=["venues"])
router.include_router(reports_router, prefix="/venues", tags=["venues"])
router.include_router(revenue_exports_router, prefix="/venues", tags=["venues"])
router.include_router(adjustments_router, prefix="/venues", tags=["venues"])
router.include_router(membership_router, prefix="/venues", tags=["venues"])
router.include_router(schedule_templates_router, prefix="/venues", tags=["venues"])
router.include_router(shift_intervals_router, prefix="/venues", tags=["venues"])
router.include_router(shifts_router, prefix="/venues", tags=["venues"])
router.include_router(catalogs_router, prefix="/venues", tags=["venues"])
router.include_router(finance_router, prefix="/venues", tags=["venues"])
router.include_router(economics_router, prefix="/venues", tags=["venues"])

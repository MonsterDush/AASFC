from fastapi import APIRouter

from app.routers.venue_expenses import router as expenses_router
from app.routers.venue_finance_summary import router as finance_summary_router
from app.routers.venue_ledger import router as ledger_router
from app.routers.venue_recurring_expenses import router as recurring_expenses_router


router = APIRouter()
router.include_router(expenses_router)
router.include_router(ledger_router)
router.include_router(recurring_expenses_router)
router.include_router(finance_summary_router)

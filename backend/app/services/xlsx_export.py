from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter


def _auto_width(ws, col_idx: int, values: list[str], min_w: int = 8, max_w: int = 60) -> None:
    mx = 0
    for v in values:
        try:
            mx = max(mx, len(str(v)))
        except Exception:
            pass
    w = max(min_w, min(max_w, mx + 2))
    ws.column_dimensions[get_column_letter(col_idx)].width = w


def build_revenue_xlsx(
    *,
    month: str,
    mode: str,
    venue_name: str,
    rows: list[dict[str, Any]],
    total: int,
    closed_reports: int,
) -> bytes:
    """Build a simple XLSX export for revenue summary."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Revenue"

    title = f"Доходы · {venue_name} · {month} · {('Оплаты' if mode == 'PAYMENTS' else 'Департаменты')} · CLOSED: {closed_reports}"
    ws.append([title])
    ws.append([])

    ws.append(["Категория", "Сумма"])
    header_row = ws.max_row
    ws[header_row][0].font = Font(bold=True)
    ws[header_row][1].font = Font(bold=True)

    for r in rows:
        ws.append([str(r.get("title") or "—"), int(r.get("amount") or 0)])

    ws.append([])
    ws.append(["ИТОГО", int(total)])

    # Styling
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    # number format for amounts (column B)
    for cell in ws[header_row + 1 : ws.max_row]:
        # cell is a tuple (A,B)
        if len(cell) >= 2 and cell[1].value is not None and isinstance(cell[1].value, (int, float)):
            cell[1].number_format = "#,##0"

    # bold total row
    total_row = ws.max_row
    ws[total_row][0].font = Font(bold=True)
    ws[total_row][1].font = Font(bold=True)

    # widths
    col1_vals = ["Категория"] + [str(r.get("title") or "") for r in rows] + ["ИТОГО"]
    col2_vals = ["Сумма"] + [str(int(r.get("amount") or 0)) for r in rows] + [str(total)]
    _auto_width(ws, 1, col1_vals, min_w=18, max_w=70)
    _auto_width(ws, 2, col2_vals, min_w=10, max_w=18)

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def build_revenue_csv(
    *,
    month: str,
    mode: str,
    venue_name: str,
    rows: list[dict[str, Any]],
    total: int,
    closed_reports: int,
    delimiter: str = ";",
) -> str:
    """CSV export (Excel-friendly, semicolon delimiter)."""
    lines: list[list[str]] = []
    lines.append(["venue", venue_name])
    lines.append(["month", month])
    lines.append(["mode", mode])
    lines.append(["closed_reports", str(closed_reports)])
    lines.append([])
    lines.append(["Категория", "Сумма"])
    for r in rows:
        lines.append([str(r.get("title") or "—"), str(int(r.get("amount") or 0))])
    lines.append(["ИТОГО", str(int(total))])

    def esc(s: str) -> str:
        s = str(s)
        return '"' + s.replace('"', '""') + '"'

    return "\n".join(delimiter.join(esc(x) for x in row) for row in lines)

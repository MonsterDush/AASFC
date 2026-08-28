from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
SERIES_PATH = ROOT.parent / "2026-08-26-check-employee-payroll" / "build_guide.py"
SPEC = spec_from_file_location("axelio_payroll_export_series", SERIES_PATH)
SERIES = module_from_spec(SPEC)
SPEC.loader.exec_module(SERIES)

NAVY = SERIES.NAVY
TEXT = SERIES.TEXT
MUTED = SERIES.MUTED
PURPLE = SERIES.PURPLE
PURPLE_LIGHT = SERIES.PURPLE_LIGHT
PANEL_CARD = SERIES.PANEL_CARD
PANEL_CARD_2 = SERIES.PANEL_CARD_2
PANEL_LINE = SERIES.PANEL_LINE
PANEL_TEXT = SERIES.PANEL_TEXT
PANEL_MUTED = SERIES.PANEL_MUTED
BLUE = SERIES.BLUE
GREEN = SERIES.GREEN

font = SERIES.font
base_canvas = SERIES.base_canvas
rounded_shadow = SERIES.rounded_shadow
fit_text = SERIES.fit_text
draw_brand = SERIES.draw_brand
draw_step_header = SERIES.draw_step_header
draw_bottom_note = SERIES.draw_bottom_note
draw_ui_frame = SERIES.draw_ui_frame
panel_text = SERIES.panel_text
button = SERIES.button
draw_finance_entry = SERIES.draw_finance_entry

STEP_GRID = {
    "number_circle": (64, 50, 124, 110),
    "step_label": (145, 64),
    "title_start": (64, 137),
    "explanation_start": (64, 230),
    "ui_frame": (60, 315, 1020, 930),
    "bottom_note_y": 950,
}


def save(img, name):
    img.convert("RGB").save(ROOT / name, quality=95)


def payroll_header(draw, highlight_export=False):
    panel_text(draw, (108, 354), "Расчёт зарплаты", 28, True)
    fit_text(
        draw,
        "Начисления по активным профилям: ставки, проценты и KPI-бонусы по закрытым отчётам выбранного периода.",
        (108, 397),
        510,
        15,
        PANEL_MUTED,
        spacing=4,
    )
    button(draw, (644, 360, 738, 414), "Профили", size=13)
    button(draw, (750, 360, 887, 414), "Экспорт XLSX", highlight=highlight_export, size=12)
    button(draw, (899, 360, 990, 414), "Рассчитать", kind="primary", size=11)


def period_card(draw, highlight=False):
    draw.rounded_rectangle(
        (100, 504, 980, 816),
        radius=20,
        fill=PANEL_CARD,
        outline=PURPLE if highlight else PANEL_LINE,
        width=4 if highlight else 2,
    )
    panel_text(draw, (130, 532), "Период начислений", 22, True)
    draw.rounded_rectangle((130, 590, 580, 660), radius=15, fill="#121b36", outline=PANEL_LINE, width=2)
    button(draw, (148, 600, 276, 650), "Месяц", kind="primary", size=15)
    button(draw, (288, 600, 416, 650), "Период", size=15)
    draw.rounded_rectangle((130, 704, 580, 768), radius=13, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (151, 724), "август 2026 г.", 18, True)
    panel_text(draw, (632, 534), "Последний расчёт", 16, True)
    panel_text(draw, (632, 570), "обновлено 27.08.2026, 16:16:48", 14, False, PANEL_MUTED)
    fit_text(
        draw,
        "Перерасчёт обновляет ФОТ и детализацию для каждого сотрудника.",
        (632, 626),
        290,
        15,
        PANEL_MUTED,
        spacing=4,
    )


def summary_cards(draw):
    cards = (
        ((108, 520, 516, 650), "Фонд оплаты труда", "1 285 235,58 ₽"),
        ((548, 520, 956, 650), "Сотрудников в расчёте", "9"),
    )
    for box, label, value in cards:
        x1, y1, x2, y2 = box
        draw.rounded_rectangle(box, radius=17, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
        panel_text(draw, (x1 + 20, y1 + 18), label, 15, False, PANEL_MUTED)
        panel_text(draw, (x1 + 20, y1 + 55), value, 24, True)
    draw.rounded_rectangle((108, 682, 956, 808), radius=17, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (132, 706), "Начисления сотрудникам", 20, True)
    panel_text(draw, (132, 746), "9 строк · полный разбор компонентов профиля", 15, False, PANEL_MUTED)


def workbook_preview(draw, outer=(102, 486, 978, 846)):
    x1, y1, x2, y2 = outer
    draw.rounded_rectangle(outer, radius=20, fill="#f8fafc", outline=PURPLE, width=4)

    sheet_x1, sheet_y1, sheet_x2, sheet_y2 = x1 + 26, y1 + 28, x2 - 26, y2 - 62
    draw.rounded_rectangle((sheet_x1, sheet_y1, sheet_x2, sheet_y2), radius=12, fill="white", outline="#d7dce7", width=2)
    panel_text(draw, (sheet_x1 + 22, sheet_y1 + 18), "Начисления · Axelio E2E Lounge", 22, True, NAVY)

    rows = (
        ("Период", "2026-08"),
        ("Строк начислений", "9"),
        ("Итого, ₽", "1 285 235,58"),
        ("Рассчитано", "27.08.2026, 16:16:48"),
        ("Run ID", "1"),
    )
    start_y = sheet_y1 + 70
    for idx, (label, value) in enumerate(rows):
        row_y = start_y + idx * 36
        if idx % 2 == 0:
            draw.rectangle((sheet_x1 + 12, row_y - 2, sheet_x2 - 12, row_y + 32), fill="#f3f5fb")
        panel_text(draw, (sheet_x1 + 24, row_y + 5), label, 14, idx in (1, 2), NAVY)
        panel_text(draw, (sheet_x1 + 470, row_y + 5), value, 14, idx in (1, 2), NAVY)
        draw.line((sheet_x1 + 12, row_y + 33, sheet_x2 - 12, row_y + 33), fill="#e1e5ee", width=1)

    tab_y = y2 - 48
    tabs = (("Сводка", 132, 142, True), ("Начисления", 286, 190, False), ("Разбор", 488, 136, False))
    for label, tx, width, active in tabs:
        draw.rounded_rectangle(
            (tx, tab_y, tx + width, tab_y + 38),
            radius=10,
            fill="#dcd5ff" if active else "#edf0f6",
            outline=PURPLE if active else "#cfd5e1",
            width=2 if active else 1,
        )
        f = font(13, True)
        tw = draw.textbbox((0, 0), label, font=f)[2]
        draw.text((tx + width / 2 - tw / 2, tab_y + 10), label, font=f, fill=NAVY)


def file_card(draw):
    draw.rounded_rectangle((102, 352, 978, 462), radius=19, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    draw.rounded_rectangle((126, 374, 188, 438), radius=12, fill=GREEN)
    for x in (140, 155, 170):
        draw.line((x, 387, x, 426), fill="white", width=2)
    for y in (390, 403, 416, 428):
        draw.line((138, y, 177, y), fill="white", width=2)
    panel_text(draw, (214, 372), "Файл скачан", 16, False, GREEN)
    panel_text(draw, (214, 401), "payroll_Axelio_E2E_Lounge_2026-08.xlsx", 19, True)
    panel_text(draw, (800, 394), "XLSX", 16, True, PURPLE_LIGHT)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как выгрузить\nначисления в XLSX?", font=font(52, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Скачайте расчёт зарплаты с итогами по сотрудникам и полным разбором компонентов.",
        (66, 405),
        475,
        27,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Файл можно открыть в Excel или другой программе для таблиц.",
        (66, 625),
        470,
        27,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "export-payroll-illustration.png").convert("RGB")
    art = art.crop((115, 120, 1139, 1144)).resize((450, 450), Image.Resampling.LANCZOS)
    mask = Image.new("L", art.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, 450, 450), radius=44, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    img.paste(art, (615, 305), mask)

    rounded_shadow(img, (62, 842, 1018, 1015), radius=28, fill="#ffffff", outline="#d4cdf6", width=2, blur=14)
    draw = ImageDraw.Draw(img)
    draw.ellipse((106, 881, 194, 969), fill=PURPLE)
    draw.text((140, 901), "1", font=font(43, True), fill="white")
    draw.text((235, 877), "Откройте «Начисления»", font=font(33, True), fill=NAVY)
    draw.text((235, 930), "В блоке «Финансы» нужного заведения.", font=font(25), fill=MUTED)
    save(img, "01-cover.png")


def build_step_1():
    img = base_canvas()
    draw_step_header(img, "1", "ШАГ 1", "Откройте начисления", "На странице заведения найдите блок «Финансы».")
    draw_finance_entry(img)
    draw_bottom_note(img, "Нажмите «Начисления» — откроется расчёт зарплаты.")
    save(img, "02-step.png")


def build_step_2():
    img = base_canvas()
    draw_step_header(img, "2", "ШАГ 2", "Выберите период", "В файл попадёт расчёт за выбранный месяц или диапазон дат.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw)
    period_card(draw, highlight=True)
    draw_bottom_note(img, "В примере выбран август 2026 года.")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Запустите экспорт", "Нажмите «Экспорт XLSX» в правом верхнем углу.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw, highlight_export=True)
    summary_cards(draw)
    draw_bottom_note(img, "Файл с выбранным расчётом скачивается автоматически.")
    save(img, "04-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Файл XLSX готов", "В книге есть сводка, строки начислений и разбор компонентов.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    file_card(draw)
    workbook_preview(draw)
    draw.rounded_rectangle((102, 866, 978, 914), radius=13, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(draw, (130, 879), "Дальше: Как сравнить начисления с прошлым периодом?", 18, True, PURPLE_LIGHT)
    draw_bottom_note(img, "Листы книги: «Сводка», «Начисления» и «Разбор».")
    save(img, "05-result.png")


def verify_outputs():
    files = ["01-cover.png", "02-step.png", "03-step.png", "04-step.png", "05-result.png"]
    for filename in files:
        with Image.open(ROOT / filename) as image:
            assert image.size == (1080, 1080), f"{filename}: {image.size}"
            assert image.mode == "RGB", f"{filename}: {image.mode}"
    assert STEP_GRID == SERIES.STEP_GRID
    print(f"Verified {len(files)} RGB slides at 1080x1080; fixed step grid: {STEP_GRID}")


def verify_ui_strings():
    repo = ROOT.parents[2]
    product_source = "\n".join(
        (repo / path).read_text(encoding="utf-8")
        for path in (
            "frontend/app-venue.html",
            "frontend/owner-payroll.js",
            "backend/app/routers/venue_revenue_exports.py",
            "backend/app/services/xlsx_export.py",
        )
    )
    required = (
        "Начисления",
        "Расчёт зарплаты",
        "Начисления по активным профилям: ставки, проценты и KPI-бонусы по закрытым отчётам выбранного периода.",
        "Профили",
        "Экспорт XLSX",
        "Рассчитать",
        "Период начислений",
        "Месяц",
        "Период",
        "Месяц начислений",
        "Начало периода",
        "Конец периода",
        "Показать",
        "Фонд оплаты труда",
        "Сотрудников в расчёте",
        "Начисления сотрудникам",
        "Сводка",
        "Начисления",
        "Разбор",
        "Начисления ·",
        "Строк начислений",
        "Итого, ₽",
        "Рассчитано",
        "Сотрудник",
        "Username",
        "Профиль",
        "Сумма, ₽",
        "Часы",
        "Смены",
        "Отработано дней",
        "Детализация компонентов",
        'filename = f"payroll_{safe_venue}_{filename_period}.xlsx"',
    )
    missing = [label for label in required if label not in product_source]
    assert not missing, f"UI/export strings not found in current product source: {missing}"
    print(f"Verified {len(required)} current UI and XLSX strings")


if __name__ == "__main__":
    build_cover()
    build_step_1()
    build_step_2()
    build_step_3()
    build_result()
    verify_outputs()
    verify_ui_strings()

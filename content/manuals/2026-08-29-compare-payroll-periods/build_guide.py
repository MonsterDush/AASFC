from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
SERIES_PATH = ROOT.parent / "2026-08-26-check-employee-payroll" / "build_guide.py"
SPEC = spec_from_file_location("axelio_payroll_comparison_series", SERIES_PATH)
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


def badge(draw, box, label, fill="#202c52", text_fill=PANEL_TEXT, outline=PANEL_LINE):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=fill, outline=outline, width=1)
    f = font(13, True)
    bbox = draw.textbbox((0, 0), label, font=f)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    draw.text(
        ((x1 + x2 - width) / 2, (y1 + y2 - height) / 2 - 2),
        label,
        font=f,
        fill=text_fill,
    )


def payroll_header(draw, range_mode=True):
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
    button(draw, (680, 360, 775, 414), "Профили", size=13)
    button(draw, (789, 360, 932, 414), "Экспорт XLSX", size=12)
    if not range_mode:
        button(draw, (840, 426, 962, 478), "Рассчитать", kind="primary", size=11)


def period_card(draw, target="segment"):
    draw.rounded_rectangle((100, 496, 980, 790), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (130, 524), "Период начислений", 22, True)
    draw.rounded_rectangle((130, 578, 548, 648), radius=15, fill="#121b36", outline=PANEL_LINE, width=2)

    button(draw, (148, 588, 276, 638), "Месяц", size=15)
    period_outline = PURPLE if target == "segment" else PANEL_LINE
    period_width = 4 if target == "segment" else 2
    draw.rounded_rectangle((284, 584, 424, 642), radius=15, outline=period_outline, width=period_width)
    button(draw, (290, 588, 418, 638), "Период", kind="primary", size=15)

    range_box = (130, 686, 956, 756)
    draw.rounded_rectangle(
        range_box,
        radius=15,
        fill="#121b36",
        outline=PURPLE if target == "range" else PANEL_LINE,
        width=4 if target == "range" else 2,
    )
    draw.rounded_rectangle((148, 697, 394, 745), radius=11, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (169, 712), "16.08.2026", 16, True)
    draw.rounded_rectangle((410, 697, 656, 745), radius=11, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (431, 712), "31.08.2026", 16, True)
    button(draw, (674, 697, 806, 745), "Показать", size=14)

    panel_text(draw, (588, 524), "Последний расчёт", 15, True)
    panel_text(draw, (588, 558), "агрегация по дневным начислениям", 13, False, PANEL_MUTED)


def comparison_collapsed(draw, highlighted=False):
    box = (100, 810, 980, 884)
    draw.rounded_rectangle(
        box,
        radius=17,
        fill=PANEL_CARD,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (128, 826), "Сравнение начислений", 18, True)
    panel_text(draw, (128, 855), "Открыть настройки сравнения", 13, False, PANEL_MUTED)
    badge(draw, (832, 830, 952, 864), "Настроить")


def comparison_open(draw, highlighted_auto=False, compact=False):
    y1 = 365 if compact else 504
    y2 = 552 if compact else 732
    draw.rounded_rectangle((100, y1, 980, y2), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (130, y1 + 24), "СРАВНЕНИЕ", 12, True, PANEL_MUTED)
    panel_text(draw, (130, y1 + 49), "2026-07-31 — 2026-08-15", 19, True)
    panel_text(draw, (130, y2 - 40), "к предыдущему периоду такой же длины", 14, False, PANEL_MUTED)

    seg_y = y1 + 38
    draw.rounded_rectangle((534, seg_y, 954, seg_y + 68), radius=15, fill="#121b36", outline=PANEL_LINE, width=2)
    auto_box = (548, seg_y + 8, 648, seg_y + 60)
    if highlighted_auto:
        draw.rounded_rectangle((542, seg_y + 2, 654, seg_y + 66), radius=16, outline=PURPLE, width=4)
    button(draw, auto_box, "Авто", kind="primary", size=14)
    button(draw, (658, seg_y + 8, 810, seg_y + 60), "Другой период", size=11)
    button(draw, (820, seg_y + 8, 942, seg_y + 60), "Без сравнения", size=10)


def metric_card(draw, box, label, value, delta, delta_fill=PURPLE_LIGHT):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=17, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (x1 + 18, y1 + 15), label, 14, False, PANEL_MUTED)
    panel_text(draw, (x1 + 18, y1 + 45), value, 22, True)
    delta_head, delta_tail = (delta.split(" к ", 1) + [""])[:2]
    panel_text(draw, (x1 + 18, y1 + 84), delta_head, 12, False, delta_fill)
    if delta_tail:
        panel_text(draw, (x1 + 18, y1 + 108), f"к {delta_tail}", 11, False, PANEL_MUTED)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как сравнить\nначисления?", font=font(56, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Сопоставьте ФОТ, среднее начисление и нагрузку команды с предыдущим периодом.",
        (66, 405),
        480,
        28,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Axelio рассчитает одинаковые по длине диапазоны автоматически.",
        (66, 632),
        470,
        27,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "compare-payroll-illustration.png").convert("RGB")
    art = art.crop((80, 80, 1174, 1174)).resize((450, 450), Image.Resampling.LANCZOS)
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
    draw_step_header(img, "2", "ШАГ 2", "Выберите «Период»", "Переключите расчёт с месяца на диапазон дат.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw)
    period_card(draw, target="segment")
    draw_bottom_note(img, "В режиме «Период» можно сравнить равные диапазоны.")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Укажите диапазон", "Выберите даты начислений и нажмите «Показать».")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw)
    period_card(draw, target="range")
    draw_bottom_note(img, "В примере выбран период с 16 по 31 августа 2026 года.")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Откройте сравнение", "Раскройте карточку «Сравнение начислений».")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw)
    period_card(draw, target="none")
    comparison_collapsed(draw, highlighted=True)
    draw_bottom_note(img, "Нажмите строку с бейджем «Настроить».")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Оставьте «Авто»", "Axelio подберёт предыдущий период той же длины.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw)
    comparison_open(draw, highlighted_auto=True)
    draw.rounded_rectangle((100, 766, 980, 866), radius=17, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (128, 786), "Текущий период", 14, False, PANEL_MUTED)
    panel_text(draw, (128, 816), "2026-08-16 — 2026-08-31", 18, True)
    panel_text(draw, (564, 786), "Период сравнения", 14, False, PANEL_MUTED)
    panel_text(draw, (564, 816), "2026-07-31 — 2026-08-15", 18, True)
    draw_bottom_note(img, "Для ручного диапазона выберите «Другой период».")
    save(img, "06-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Сравнение готово", "Дельты появились под ключевыми показателями начислений.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    comparison_open(draw, compact=True)
    metric_card(
        draw,
        (100, 570, 524, 724),
        "Фонд оплаты труда",
        "705 435,59 ₽",
        "+21,7% · +125 635,60 ₽ к предыдущему периоду такой же длины",
    )
    metric_card(
        draw,
        (548, 570, 980, 724),
        "Сотрудников в расчёте",
        "9",
        "0% · 0 к предыдущему периоду такой же длины",
    )
    metric_card(
        draw,
        (100, 742, 524, 896),
        "Среднее начисление",
        "78 381,73 ₽",
        "+21,7% · +13 959,51 ₽ к предыдущему периоду такой же длины",
    )
    metric_card(
        draw,
        (548, 742, 980, 896),
        "Среднее за смену",
        "5 075,08 ₽",
        "+15,5% · +682,66 ₽ к предыдущему периоду такой же длины",
    )
    draw_bottom_note(img, "Дельты рассчитаны к предыдущему периоду такой же длины.")
    save(img, "07-result.png")


def verify_outputs():
    files = [
        "01-cover.png",
        "02-step.png",
        "03-step.png",
        "04-step.png",
        "05-step.png",
        "06-step.png",
        "07-result.png",
    ]
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
            "frontend/app/period-comparison.js",
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
        "Начало периода",
        "Конец периода",
        "Показать",
        "Последний расчёт",
        "Сравнение начислений",
        "Открыть настройки сравнения",
        "Настроить",
        "Сравнение",
        "Авто",
        "Другой период",
        "Без сравнения",
        "Начало периода сравнения",
        "Конец периода сравнения",
        "Сравнить",
        "к предыдущему периоду такой же длины",
        "Фонд оплаты труда",
        "Сотрудников в расчёте",
        "Среднее начисление",
        "Среднее за смену",
    )
    missing = [label for label in required if label not in product_source]
    assert not missing, f"UI strings not found in current product source: {missing}"
    print(f"Verified {len(required)} current UI strings")


if __name__ == "__main__":
    build_cover()
    build_step_1()
    build_step_2()
    build_step_3()
    build_step_4()
    build_step_5()
    build_result()
    verify_outputs()
    verify_ui_strings()

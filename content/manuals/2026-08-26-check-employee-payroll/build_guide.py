from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
SERIES_PATH = ROOT.parent / "2026-08-20-pay-profile" / "build_guide.py"
SPEC = spec_from_file_location("axelio_payroll_series", SERIES_PATH)
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


def badge(draw, xy, text, fill="#202c52", text_fill=PANEL_TEXT, width=None):
    x, y = xy
    f = font(13, True)
    measured = draw.textbbox((0, 0), text, font=f)[2]
    w = width or measured + 28
    draw.rounded_rectangle((x, y, x + w, y + 32), radius=16, fill=fill, outline=PANEL_LINE, width=1)
    draw.text((x + 14, y + 7), text, font=f, fill=text_fill)
    return w


def metric_card(draw, box, label, value, highlighted=False):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(
        box,
        radius=17,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (x1 + 20, y1 + 18), label, 15, False, PANEL_MUTED)
    panel_text(draw, (x1 + 20, y1 + 54), value, 24, True)


def draw_money_note(img, text):
    draw = ImageDraw.Draw(img)
    draw.ellipse((76, 963, 95, 982), fill=PURPLE)
    panel_text(draw, (116, 951), text, 27, False, "#68718a")


def payroll_header(draw, compact=False):
    panel_text(draw, (108, 354), "Расчёт зарплаты", 28, True)
    if not compact:
        fit_text(
            draw,
            "Начисления по активным профилям: ставки, проценты и KPI-бонусы по закрытым отчётам выбранного периода.",
            (108, 397),
            520,
            15,
            PANEL_MUTED,
            spacing=4,
        )
    button(draw, (644, 360, 738, 414), "Профили", size=13)
    button(draw, (750, 360, 887, 414), "Экспорт XLSX", size=12)
    button(draw, (899, 360, 990, 414), "Рассчитать", kind="primary", size=11)


def employee_row(draw, top=480, highlight_row=False, highlight_breakdown=False, open_details=False):
    bottom = 858 if open_details else 766
    draw.rounded_rectangle(
        (102, top, 978, bottom),
        radius=18,
        fill=PANEL_CARD,
        outline=PURPLE if highlight_row else PANEL_LINE,
        width=4 if highlight_row else 2,
    )
    panel_text(draw, (130, top + 24), "София", 22, True)
    badge(draw, (224, top + 20), "Администратор")
    panel_text(draw, (780, top + 20), "137 200,00 ₽", 21, True)

    metrics = (
        ("182 ч", 130, 88),
        ("31 смен", 230, 106),
        ("31 дней", 348, 104),
        ("4 425,81 ₽ за смену", 464, 204),
    )
    for text, x, width in metrics:
        badge(draw, (x, top + 70), text, fill="#17213f", width=width)

    breakdown_box = (118, top + 127, 344, top + 181)
    draw.rounded_rectangle(
        breakdown_box,
        radius=13,
        fill="#121b36",
        outline=PURPLE if highlight_breakdown else PANEL_LINE,
        width=4 if highlight_breakdown else 2,
    )
    panel_text(draw, (140, top + 145), "Показать разбор", 15, True)
    draw.polygon(
        [(316, top + 148), (326, top + 148), (321, top + 155)],
        fill=PANEL_MUTED,
    )

    if open_details:
        breakdown_component(
            draw,
            (118, top + 205, 962, top + 277),
            "Оклад за месяц",
            "Фикс за месяц",
            "Фиксированная часть за период.",
            "69 000,00 ₽",
        )
        breakdown_component(
            draw,
            (118, top + 289, 962, top + 381),
            "Фикс за смену",
            "Смена администратора",
            "Компонент посчитан по количеству смен в периоде.",
            "68 200,00 ₽",
            meta="Фикс за смену · 2 200,00 ₽ / смена",
        )


def breakdown_component(draw, box, kind, title, explanation, amount, meta=None):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=14, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (x1 + 18, y1 + 12), kind, 12, True, PURPLE_LIGHT)
    panel_text(draw, (x1 + 18, y1 + 32), title, 17, True)
    panel_text(draw, (x1 + 250, y1 + 34), explanation, 13, False, PANEL_MUTED)
    panel_text(draw, (x2 - 164, y1 + 26), amount, 18, True)
    if meta:
        panel_text(draw, (x1 + 18, y1 + 65), meta, 12, False, PANEL_MUTED)


def draw_finance_entry(img):
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    panel_text(draw, (118, 380), "Axelio E2E Lounge", 21, True)
    panel_text(draw, (118, 420), "Здесь собраны основные разделы, настройки и команда заведения.", 17, False, PANEL_MUTED)
    panel_text(draw, (118, 486), "Финансы", 30, True)
    panel_text(draw, (118, 530), "Сводка, зарплаты, расходы и аналитика дня.", 19, False, PANEL_MUTED)
    labels = [
        ("Сводка", 118, 590, 186),
        ("Профили зарплаты", 332, 590, 246),
        ("Начисления", 606, 590, 186),
        ("Экономика дня", 808, 590, 164),
        ("Планы", 118, 690, 186),
        ("Нормативы", 332, 690, 186),
        ("Расходы", 546, 690, 186),
        ("Штрафы", 760, 690, 186),
    ]
    for label, x, y, width in labels:
        highlighted = label == "Начисления"
        draw.rounded_rectangle(
            (x, y, x + width, y + 72),
            radius=15,
            fill=PANEL_CARD,
            outline=PURPLE if highlighted else PANEL_LINE,
            width=5 if highlighted else 2,
        )
        f = font(16 if label == "Профили зарплаты" else 17, True)
        tw = draw.textbbox((0, 0), label, font=f)[2]
        draw.text((x + width / 2 - tw / 2, y + 23), label, font=f, fill=PANEL_TEXT)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как проверить\nначисления сотрудника?", font=font(52, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Откройте расчёт, найдите сотрудника и посмотрите, из каких компонентов сложилась сумма.",
        (66, 405),
        480,
        27,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Покажем на готовом расчёте за август.",
        (66, 656),
        470,
        28,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "check-payroll-illustration.png").convert("RGB")
    art = art.crop((100, 100, 1154, 1154)).resize((450, 450), Image.Resampling.LANCZOS)
    mask = Image.new("L", art.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, 450, 450), radius=44, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    img.paste(art, (615, 310), mask)

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
    draw_step_header(img, "2", "ШАГ 2", "Выберите месяц", "В блоке «Период начислений» оставьте режим «Месяц».")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw)
    draw.rounded_rectangle((100, 504, 980, 816), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (130, 532), "Период начислений", 22, True)
    draw.rounded_rectangle((130, 590, 580, 660), radius=15, fill="#121b36", outline=PURPLE, width=4)
    button(draw, (148, 600, 276, 650), "Месяц", kind="primary", size=15)
    button(draw, (288, 600, 416, 650), "Период", size=15)
    draw.rounded_rectangle((130, 704, 580, 768), radius=13, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (151, 724), "август 2026 г.", 18, True)
    panel_text(draw, (632, 534), "Последний расчёт", 16, True)
    panel_text(draw, (632, 570), "обновлено 26.08.2026, 18:25:44", 14, False, PANEL_MUTED)
    fit_text(draw, "Перерасчёт обновляет ФОТ и детализацию для каждого сотрудника.", (632, 626), 290, 15, PANEL_MUTED, spacing=4)
    draw_bottom_note(img, "В примере выбран август 2026 года.")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Проверьте сводку", "Сначала сверьте общий ФОТ и число сотрудников в расчёте.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payroll_header(draw, compact=True)
    draw.rounded_rectangle((92, 458, 988, 814), radius=22, fill=PANEL_CARD, outline=PURPLE, width=4)
    metric_card(draw, (116, 490, 526, 622), "Фонд оплаты труда", "1 285 235,58 ₽")
    metric_card(draw, (554, 490, 964, 622), "Сотрудников в расчёте", "9")
    metric_card(draw, (116, 650, 526, 782), "Среднее начисление", "142 803,95 ₽")
    metric_card(draw, (554, 650, 964, 782), "Среднее за смену", "4 742,57 ₽")
    draw_bottom_note(img, "Эти показатели помогают быстро заметить пропуск или резкое отклонение.")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Найдите сотрудника", "В блоке «Начисления сотрудникам» откройте нужную строку.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    panel_text(draw, (102, 355), "Начисления сотрудникам", 27, True)
    panel_text(draw, (102, 398), "Сумма, рабочая нагрузка и полный разбор компонентов профиля.", 15, False, PANEL_MUTED)
    employee_row(draw, top=482, highlight_row=True)
    draw_bottom_note(img, "В строке видны итоговая сумма, часы, смены, дни и сумма за смену.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Откройте разбор", "Нажмите «Показать разбор» под показателями сотрудника.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    panel_text(draw, (102, 355), "Начисления сотрудникам", 27, True)
    panel_text(draw, (102, 398), "Сумма, рабочая нагрузка и полный разбор компонентов профиля.", 15, False, PANEL_MUTED)
    employee_row(draw, top=482, highlight_breakdown=True)
    draw_bottom_note(img, "Axelio раскроет компоненты профиля, участвующие в расчёте.")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Сверьте составляющие", "Проверьте название, правило и сумму каждого компонента.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((92, 344, 988, 882), radius=22, fill=PANEL_CARD, outline=PURPLE, width=4)
    panel_text(draw, (118, 366), "София", 22, True)
    badge(draw, (212, 362), "Администратор")
    panel_text(draw, (780, 364), "137 200,00 ₽", 21, True)
    panel_text(draw, (118, 418), "Показать разбор", 15, True)
    breakdown_component(
        draw,
        (118, 466, 962, 580),
        "Оклад за месяц",
        "Фикс за месяц",
        "Фиксированная часть за период.",
        "69 000,00 ₽",
    )
    breakdown_component(
        draw,
        (118, 600, 962, 742),
        "Фикс за смену",
        "Смена администратора",
        "Компонент посчитан по количеству смен в периоде.",
        "68 200,00 ₽",
        meta="Фикс за смену · 2 200,00 ₽ / смена",
    )
    draw.rounded_rectangle((118, 765, 962, 842), radius=14, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(draw, (142, 783), "Базовая ставка", 14, False, PANEL_MUTED)
    panel_text(draw, (780, 783), "2 200,00 ₽ / смена", 16, True)
    draw_money_note(img, "69 000,00 ₽ + 68 200,00 ₽ = 137 200,00 ₽.")
    save(img, "07-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Начисление проверено", "Итог совпадает с суммой компонентов профиля.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((102, 352, 978, 820), radius=22, fill=PANEL_CARD, outline=PURPLE, width=4)
    draw.ellipse((132, 382, 204, 454), fill=GREEN)
    draw.line((151, 418, 166, 432), fill="white", width=7)
    draw.line((166, 432, 188, 401), fill="white", width=7)
    panel_text(draw, (230, 384), "София · Администратор", 23, True)
    panel_text(draw, (230, 424), "август 2026 г.", 15, False, PANEL_MUTED)
    panel_text(draw, (132, 504), "Итого", 18, False, PANEL_MUTED)
    panel_text(draw, (132, 542), "137 200,00 ₽", 36, True)
    breakdown_component(draw, (132, 620, 948, 694), "Оклад за месяц", "Фикс за месяц", "", "69 000,00 ₽")
    breakdown_component(draw, (132, 712, 948, 786), "Фикс за смену", "Смена администратора", "", "68 200,00 ₽")
    draw.rounded_rectangle((102, 844, 978, 900), radius=14, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(draw, (132, 861), "Следующая инструкция: Как выгрузить начисления в XLSX?", 19, True, PURPLE_LIGHT)
    draw_bottom_note(img, "Сумма складывается из компонентов назначенного профиля.")
    save(img, "08-result.png")


def verify_outputs():
    files = [
        "01-cover.png",
        "02-step.png",
        "03-step.png",
        "04-step.png",
        "05-step.png",
        "06-step.png",
        "07-step.png",
        "08-result.png",
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
        "Последний расчёт",
        "Перерасчёт обновляет ФОТ и детализацию для каждого сотрудника.",
        "Фонд оплаты труда",
        "Сотрудников в расчёте",
        "Среднее начисление",
        "Среднее за смену",
        "Начисления сотрудникам",
        "Сумма, рабочая нагрузка и полный разбор компонентов профиля.",
        "Показать разбор",
        "Показать разбор периода",
        "Фиксированная часть за период.",
        "Компонент посчитан по количеству смен в периоде.",
        "Базовая ставка",
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
    build_step_6()
    build_result()
    verify_outputs()
    verify_ui_strings()

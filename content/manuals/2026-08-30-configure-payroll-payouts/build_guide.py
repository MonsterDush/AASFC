from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
SERIES_PATH = ROOT.parent / "2026-08-29-compare-payroll-periods" / "build_guide.py"
SPEC = spec_from_file_location("axelio_payroll_payouts_series", SERIES_PATH)
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
BLUE = SERIES.SERIES.BLUE

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


def center_text(draw, box, label, size=13, bold=True, fill=PANEL_TEXT):
    x1, y1, x2, y2 = box
    f = font(size, bold)
    bbox = draw.textbbox((0, 0), label, font=f)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    draw.text(((x1 + x2 - width) / 2, (y1 + y2 - height) / 2 - 2), label, font=f, fill=fill)


def ui_badge(draw, box, label, fill="#202c52", text_fill=PANEL_TEXT):
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill, outline=PANEL_LINE, width=1)
    center_text(draw, box, label, size=13, fill=text_fill)


def payment_summary(draw, configured=False, highlighted=False, top=360):
    box = (100, top, 980, top + 90)
    draw.rounded_rectangle(
        box,
        radius=18,
        fill=PANEL_CARD,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (128, top + 18), "Выплаты ФОТ", 21, True)
    panel_text(
        draw,
        (128, top + 54),
        "Наличные · по датам месяца" if configured else "Настройте способ оплаты и календарь выплат",
        14,
        False,
        PANEL_MUTED,
    )
    ui_badge(
        draw,
        (824, top + 24, 952, top + 64),
        "Включено" if configured else "Не настроено",
        fill="#173a33" if configured else "#202c52",
        text_fill=GREEN if configured else PANEL_TEXT,
    )


def select_field(draw, box, label, value, highlighted=False):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 28), label, 15, True, PANEL_MUTED)
    draw.rounded_rectangle(
        box,
        radius=13,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (x1 + 17, y1 + 15), value, 17, True)
    cx = x2 - 23
    cy = (y1 + y2) // 2
    draw.polygon(((cx - 7, cy - 4), (cx + 7, cy - 4), (cx, cy + 5)), fill=PANEL_MUTED)


def payment_fields(draw, target=None):
    select_field(draw, (120, 510, 528, 574), "Способ оплаты", "Наличные", highlighted=target == "method")
    select_field(draw, (552, 510, 960, 574), "Периодичность", "По датам месяца", highlighted=target == "cadence")


def checked_toggle(draw, highlighted=False, y=620):
    if highlighted:
        draw.rounded_rectangle((110, y - 12, 520, y + 54), radius=14, outline=PURPLE, width=4)
    draw.rounded_rectangle((124, y, 160, y + 36), radius=8, fill=BLUE, outline=BLUE, width=2)
    draw.line((133, y + 18, 143, y + 28), fill="white", width=4)
    draw.line((143, y + 28, 153, y + 10), fill="white", width=4)
    panel_text(draw, (176, y + 7), "Формировать черновики выплат", 16, True)


def subtle_button(draw, box, label, disabled=False, size=12):
    fill = "#111a35" if not disabled else "#10172b"
    outline = PANEL_LINE if not disabled else "#27304d"
    text_fill = PANEL_TEXT if not disabled else "#66708c"
    draw.rounded_rectangle(box, radius=12, fill=fill, outline=outline, width=2)
    center_text(draw, box, label, size=size, fill=text_fill)


def payout_rule(draw, top, payment_day, period_from, period_to, month_label):
    box = (118, top, 962, top + 100)
    draw.rounded_rectangle(box, radius=14, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    labels = (
        ("Выплата", str(payment_day), 138, 110),
        ("Период с", str(period_from), 266, 110),
        ("по", str(period_to), 394, 90),
        ("Месяц периода", month_label, 502, 230),
    )
    for label, value, x, width in labels:
        panel_text(draw, (x, top + 12), label, 11, False, PANEL_MUTED)
        draw.rounded_rectangle((x, top + 38, x + width, top + 84), radius=9, fill="#121b36", outline=PANEL_LINE, width=1)
        panel_text(draw, (x + 12, top + 51), value, 14, True)
    panel_text(draw, (222, top + 55), "числа", 11, False, PANEL_MUTED)
    subtle_button(draw, (752, top + 38, 938, top + 84), "Удалить", size=12)


def payment_schedule(draw, highlighted=False, top=468):
    box = (100, top, 980, top + 348)
    draw.rounded_rectangle(
        box,
        radius=19,
        fill=PANEL_CARD,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (126, top + 22), "Даты и периоды выплат", 21, True)
    panel_text(draw, (126, top + 55), "Для каждой даты укажите, начисления за какие числа попадут в черновик.", 13, False, PANEL_MUTED)
    subtle_button(draw, (764, top + 18, 952, top + 62), "Добавить выплату", size=11)
    payout_rule(draw, top + 92, 5, 16, 31, "Предыдущий")
    payout_rule(draw, top + 204, 20, 1, 15, "Текущий")


def preview_card(draw, top=498):
    draw.rounded_rectangle((100, top, 980, top + 260), radius=19, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (128, top + 22), "Предпросмотр выплат выбранного месяца", 20, True)
    fit_text(
        draw,
        "Черновик не влияет на сводку. Списание выбранного баланса произойдёт после подтверждения расхода.",
        (128, top + 56),
        790,
        12,
        PANEL_MUTED,
        spacing=4,
    )
    rows = (
        ("5 августа 2026 г.", "16 июля 2026 г. — 31 июля 2026 г."),
        ("20 августа 2026 г.", "1 августа 2026 г. — 15 августа 2026 г."),
    )
    for idx, (payment_date, period) in enumerate(rows):
        y = top + 126 + idx * 58
        draw.rounded_rectangle((126, y, 954, y + 48), radius=11, fill=PANEL_CARD_2, outline=PANEL_LINE, width=1)
        panel_text(draw, (146, y + 14), payment_date, 14, True)
        panel_text(draw, (420, y + 14), period, 14, False, PANEL_MUTED)


def schedule_teaser(draw, top=700):
    draw.rounded_rectangle((100, top, 980, top + 166), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (128, top + 22), "Даты и периоды выплат", 20, True)
    panel_text(draw, (128, top + 55), "Для каждой даты укажите, начисления за какие числа попадут в черновик.", 12, False, PANEL_MUTED)
    panel_text(draw, (128, top + 105), "5 августа 2026 г.", 14, True)
    panel_text(draw, (410, top + 105), "16 июля 2026 г. — 31 июля 2026 г.", 14, False, PANEL_MUTED)
    panel_text(draw, (128, top + 135), "20 августа 2026 г.", 14, True)
    panel_text(draw, (410, top + 135), "1 августа 2026 г. — 15 августа 2026 г.", 14, False, PANEL_MUTED)


def metric_card(draw, box, label, value):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=16, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (x1 + 18, y1 + 16), label, 13, False, PANEL_MUTED)
    panel_text(draw, (x1 + 18, y1 + 48), value, 21, True)


def action_row(draw, top=760, highlight_save=False, configured=False):
    save_box = (118, top, 356, top + 62)
    if highlight_save:
        draw.rounded_rectangle((110, top - 8, 364, top + 70), radius=17, outline=PURPLE, width=4)
    button(draw, save_box, "Сохранить настройки", kind="primary", size=13)
    subtle_button(draw, (380, top, 628, top + 62), "Сформировать черновики", disabled=not configured, size=12)
    subtle_button(draw, (652, top, 962, top + 62), "Открыть черновики расходов", size=12)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как настроить\nвыплаты ФОТ?", font=font(53, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Укажите способ оплаты, периодичность и даты будущих выплат команде.",
        (66, 405),
        480,
        28,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Сохранённый календарь подготовит данные для черновиков расходов.",
        (66, 632),
        470,
        27,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "configure-payroll-payouts-illustration.png").convert("RGB")
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
    draw_step_header(img, "2", "ШАГ 2", "Откройте выплаты", "Найдите карточку «Выплаты ФОТ» под показателями.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    panel_text(draw, (108, 360), "Ключевые показатели", 24, True)
    metric_card(draw, (100, 408, 524, 520), "Фонд оплаты труда", "1 285 235,58 ₽")
    metric_card(draw, (548, 408, 980, 520), "Сотрудников в расчёте", "9")
    metric_card(draw, (100, 538, 524, 650), "Среднее начисление", "142 803,95 ₽")
    metric_card(draw, (548, 538, 980, 650), "Среднее за смену", "4 742,57 ₽")
    payment_summary(draw, highlighted=True, top=702)
    draw_bottom_note(img, "Нажмите строку со статусом «Не настроено».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Выберите способ оплаты", "Укажите баланс, с которого будут списываться выплаты.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payment_summary(draw)
    payment_fields(draw, target="method")
    checked_toggle(draw)
    schedule_teaser(draw, top=700)
    draw_bottom_note(img, "В примере выбран способ оплаты «Наличные».")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Выберите периодичность", "Укажите, как часто формировать выплаты ФОТ.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payment_summary(draw)
    payment_fields(draw, target="cadence")
    checked_toggle(draw)
    schedule_teaser(draw, top=700)
    draw_bottom_note(img, "В примере выбрано «По датам месяца».")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Проверьте календарь", "Для каждой выплаты укажите числа расчётного периода.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payment_schedule(draw, highlighted=True, top=390)
    draw.rounded_rectangle((100, 766, 980, 866), radius=17, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(draw, (128, 786), "5 августа", 16, True, PURPLE_LIGHT)
    panel_text(draw, (286, 786), "16–31 июля", 16, False, PANEL_MUTED)
    panel_text(draw, (128, 826), "20 августа", 16, True, PURPLE_LIGHT)
    panel_text(draw, (286, 826), "1–15 августа", 16, False, PANEL_MUTED)
    draw_bottom_note(img, "По умолчанию показаны выплаты 5-го и 20-го числа.")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Включите черновики", "Разрешите Axelio готовить будущие выплаты ФОТ.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payment_summary(draw)
    payment_fields(draw)
    checked_toggle(draw, highlighted=True, y=630)
    draw.rounded_rectangle((100, 735, 980, 860), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (128, 758), "Что произойдёт дальше", 18, True)
    fit_text(
        draw,
        "Подтверждённый черновик создаёт проводку ФОТ, но не добавляет ФОТ второй раз в управленческую сводку.",
        (128, 798),
        800,
        14,
        PANEL_MUTED,
        spacing=5,
    )
    draw_bottom_note(img, "Черновики не влияют на сводку до подтверждения расхода.")
    save(img, "07-step.png")


def build_step_7():
    img = base_canvas()
    draw_step_header(img, "7", "ШАГ 7", "Сохраните настройки", "Нажмите основную кнопку под предпросмотром выплат.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    preview_card(draw, top=370)
    action_row(draw, top=680, highlight_save=True, configured=False)
    draw.rounded_rectangle((100, 786, 980, 868), radius=16, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    fit_text(
        draw,
        "Подтверждённый черновик создаёт проводку ФОТ, но не добавляет ФОТ второй раз в управленческую сводку.",
        (128, 806),
        800,
        13,
        PANEL_MUTED,
        spacing=4,
    )
    draw_bottom_note(img, "«Сформировать черновики» станет доступна после сохранения.")
    save(img, "08-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Выплаты настроены", "Карточка показывает способ оплаты, режим и статус.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payment_summary(draw, configured=True, highlighted=True)
    preview_card(draw, top=490)
    action_row(draw, top=790, configured=True)
    draw_bottom_note(img, "Дальше можно сформировать черновики выплат ФОТ.")
    save(img, "09-result.png")


def verify_outputs():
    files = [
        "01-cover.png",
        "02-step.png",
        "03-step.png",
        "04-step.png",
        "05-step.png",
        "06-step.png",
        "07-step.png",
        "08-step.png",
        "09-result.png",
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
        "Выплаты ФОТ",
        "Способ оплаты, даты выплат и расчётные периоды",
        "Настройте способ оплаты и календарь выплат",
        "Настроить",
        "Не настроено",
        "Способ оплаты",
        "Выберите способ оплаты",
        "Периодичность",
        "Каждый день",
        "Раз в неделю",
        "По датам месяца",
        "Формировать черновики выплат",
        "Даты и периоды выплат",
        "Для каждой даты укажите, начисления за какие числа попадут в черновик.",
        "Добавить выплату",
        "Выплата",
        "Период с",
        "Месяц периода",
        "Текущий",
        "Предыдущий",
        "Удалить",
        "Предпросмотр выплат выбранного месяца",
        "Черновик не влияет на сводку. Списание выбранного баланса произойдёт после подтверждения расхода.",
        "Сохранить настройки",
        "Сформировать черновики",
        "Открыть черновики расходов",
        "Настройки выплат сохранены",
        "Включено",
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
    build_step_7()
    build_result()
    verify_outputs()
    verify_ui_strings()

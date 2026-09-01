from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-08-30-configure-payroll-payouts" / "build_guide.py"
SPEC = spec_from_file_location("axelio_payroll_draft_series", PREVIOUS_PATH)
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
BLUE = SERIES.BLUE

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
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 2), label, font=f, fill=fill)


def ui_badge(draw, box, label, fill="#202c52", text_fill=PANEL_TEXT, outline=PANEL_LINE):
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill, outline=outline, width=1)
    center_text(draw, box, label, size=12, fill=text_fill)


def subtle_button(draw, box, label, size=12, highlighted=False):
    x1, y1, x2, y2 = box
    if highlighted:
        draw.rounded_rectangle((x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius=17, outline=PURPLE, width=4)
    draw.rounded_rectangle(box, radius=12, fill="#111a35", outline=PANEL_LINE, width=2)
    center_text(draw, box, label, size=size, fill=PANEL_TEXT)


def payment_summary(draw, highlighted=False, top=360):
    box = (100, top, 980, top + 90)
    draw.rounded_rectangle(
        box,
        radius=18,
        fill=PANEL_CARD,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (128, top + 18), "Выплаты ФОТ", 21, True)
    panel_text(draw, (128, top + 54), "Наличные · по датам месяца", 14, False, PANEL_MUTED)
    ui_badge(draw, (824, top + 24, 952, top + 64), "Включено", fill="#173a33", text_fill=GREEN)


def metric_card(draw, box, label, value):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=16, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (x1 + 18, y1 + 16), label, 13, False, PANEL_MUTED)
    panel_text(draw, (x1 + 18, y1 + 48), value, 21, True)


def preview_card(draw, top=476, highlighted=False):
    box = (100, top, 980, top + 276)
    draw.rounded_rectangle(
        box,
        radius=19,
        fill=PANEL_CARD,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (128, top + 22), "Предпросмотр выплат выбранного месяца", 20, True)
    fit_text(
        draw,
        "Черновик не влияет на сводку. Списание выбранного баланса произойдёт после подтверждения расхода.",
        (128, top + 58),
        790,
        12,
        PANEL_MUTED,
        spacing=4,
    )
    rows = (
        ("5 сентября 2026 г.", "16 августа 2026 г. — 31 августа 2026 г."),
        ("20 сентября 2026 г.", "1 сентября 2026 г. — 15 сентября 2026 г."),
    )
    for idx, (payment_date, period) in enumerate(rows):
        y = top + 137 + idx * 58
        draw.rounded_rectangle((126, y, 954, y + 48), radius=11, fill=PANEL_CARD_2, outline=PANEL_LINE, width=1)
        panel_text(draw, (146, y + 14), payment_date, 14, True)
        panel_text(draw, (430, y + 14), period, 13, False, PANEL_MUTED)


def action_row(draw, top=786, target=None):
    button(draw, (118, top, 356, top + 62), "Сохранить настройки", kind="primary", size=13)
    subtle_button(draw, (380, top, 628, top + 62), "Сформировать черновики", size=12, highlighted=target == "generate")
    subtle_button(
        draw,
        (652, top, 962, top + 62),
        "Открыть черновики расходов",
        size=12,
        highlighted=target == "open",
    )


def toast_card(draw, top=690):
    draw.rounded_rectangle((640, top, 966, top + 64), radius=15, fill="#173a33", outline="#2d826c", width=2)
    draw.ellipse((660, top + 20, 684, top + 44), fill=GREEN)
    panel_text(draw, (698, top + 20), "Черновики ФОТ готовы: 1", 13, True, GREEN)


def expense_filters(draw, top=442):
    panel_text(draw, (112, top), "Фильтры и черновики", 16, True)
    draw.rounded_rectangle((100, top + 34, 474, top + 92), radius=13, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (120, top + 51), "Только черновики", 15, True)
    draw.polygon(((444, top + 60), (458, top + 60), (451, top + 69)), fill=PANEL_MUTED)
    draw.rounded_rectangle((494, top + 34, 868, top + 92), radius=13, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (514, top + 51), "Выплаты ФОТ", 15, True)
    draw.polygon(((838, top + 60), (852, top + 60), (845, top + 69)), fill=PANEL_MUTED)
    draw.rounded_rectangle((888, top + 34, 966, top + 92), radius=13, fill="#202c52", outline=PANEL_LINE, width=1)
    center_text(draw, (888, top + 34, 966, top + 92), "1", size=20)


def expense_row(draw, top=584):
    box = (96, top, 984, top + 292)
    draw.rounded_rectangle(box, radius=18, fill=PANEL_CARD, outline=PURPLE, width=4)
    panel_text(draw, (122, top + 22), "Выплата ФОТ", 21, True)
    ui_badge(draw, (122, top + 60, 232, top + 94), "Черновик", fill="#3d3215", text_fill="#ffd97a")
    ui_badge(draw, (244, top + 60, 374, top + 94), "Выплата ФОТ")
    ui_badge(draw, (386, top + 60, 590, top + 94), "Сгенерирован 2026-09-01")

    panel_text(draw, (122, top + 112), "2026-09-20", 13, True)
    panel_text(draw, (236, top + 112), "·  Наличные", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 145), "Расчётный период: 2026-09-01 — 2026-09-15", 13, False, PANEL_MUTED)
    draw.rounded_rectangle((118, top + 176, 654, top + 220), radius=10, fill=PANEL_CARD_2, outline=PANEL_LINE, width=1)
    panel_text(draw, (136, top + 190), "Автоматический черновик выплаты ФОТ за 01.09.2026–15.09.2026", 11, False, PANEL_MUTED)
    panel_text(draw, (688, top + 23), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (688, top + 53), "583 766,83 ₽", 23, True)
    button(draw, (688, top + 106, 820, top + 154), "Подтвердить", size=11)
    subtle_button(draw, (832, top + 106, 960, top + 154), "Отменить", size=11)
    button(draw, (832, top + 166, 960, top + 214), "Удалить", kind="danger", size=11)
    fit_text(
        draw,
        "После подтверждения списывает выбранный способ оплаты и не дублирует ФОТ в сводке.",
        (122, top + 238),
        800,
        12,
        PANEL_MUTED,
        spacing=3,
    )


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как сформировать\nчерновики ФОТ?", font=font(49, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Подготовьте выплаты команде по сохранённому календарю.",
        (66, 405),
        480,
        28,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Черновик появится в расходах и не изменит сводку до подтверждения.",
        (66, 632),
        470,
        27,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "generate-payroll-drafts-illustration.png").convert("RGB")
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
    draw_step_header(img, "2", "ШАГ 2", "Откройте выплаты ФОТ", "Раскройте настроенную карточку под показателями.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    panel_text(draw, (108, 360), "Ключевые показатели", 24, True)
    metric_card(draw, (100, 408, 524, 520), "Фонд оплаты труда", "1 267 528,32 ₽")
    metric_card(draw, (548, 408, 980, 520), "Сотрудников в расчёте", "9")
    metric_card(draw, (100, 538, 524, 650), "Среднее начисление", "140 836,48 ₽")
    metric_card(draw, (548, 538, 980, 650), "Среднее за смену", "4 875,11 ₽")
    payment_summary(draw, highlighted=True, top=702)
    draw_bottom_note(img, "Карточка должна показывать способ оплаты и статус «Включено».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Проверьте даты", "Сверьте даты выплат и расчётные периоды.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payment_summary(draw, top=360)
    preview_card(draw, top=482, highlighted=True)
    draw_bottom_note(img, "В примере черновики готовятся на 5 и 20 сентября.")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Сформируйте черновики", "Нажмите вторичную кнопку под предпросмотром.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    preview_card(draw, top=368)
    action_row(draw, top=698, target="generate")
    draw.rounded_rectangle((100, 798, 980, 868), radius=15, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (128, 820), "Черновики ФОТ готовы: 1", 17, True, GREEN)
    draw_bottom_note(img, "Axelio сообщит, сколько черновиков создано или обновлено.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Откройте расходы", "Перейдите к созданным черновикам ФОТ.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    payment_summary(draw, top=360)
    toast_card(draw, top=474)
    draw.rounded_rectangle((100, 570, 980, 674), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (128, 592), "Предпросмотр выплат выбранного месяца", 19, True)
    panel_text(draw, (128, 629), "Черновик не влияет на сводку до подтверждения расхода.", 13, False, PANEL_MUTED)
    action_row(draw, top=748, target="open")
    draw_bottom_note(img, "Откроется «Расходы» с фильтрами «Только черновики» и «Выплаты ФОТ».")
    save(img, "06-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Черновик создан", "Проверьте сумму, дату выплаты и расчётный период.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    panel_text(draw, (106, 352), "Расходы", 25, True)
    panel_text(draw, (106, 390), "Расходы и черновики за выбранный период", 13, False, PANEL_MUTED)
    button(draw, (792, 352, 962, 404), "Добавить расход", kind="primary", size=12)
    expense_filters(draw, top=430)
    expense_row(draw, top=568)
    draw_bottom_note(img, "Не нажимайте «Подтвердить», пока не проверите сумму и период.")
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
    assert ("arrow" + "(") not in Path(__file__).read_text(encoding="utf-8")
    print(f"Verified {len(files)} RGB slides at 1080x1080; fixed step grid: {STEP_GRID}; arrows: 0")


def verify_ui_strings():
    repo = ROOT.parents[2]
    product_source = "\n".join(
        (repo / path).read_text(encoding="utf-8")
        for path in (
            "frontend/app-venue.html",
            "frontend/owner-payroll.js",
            "frontend/owner-expenses.html",
            "frontend/owner-expenses.js",
            "backend/app/services/payroll/payments.py",
            "backend/app/scripts/bootstrap_e2e_data.py",
            "backend/app/services/demo/bootstrap.py",
        )
    )
    required = (
        "Начисления",
        "Выплаты ФОТ",
        "Наличные",
        "по датам месяца",
        "Включено",
        "Предпросмотр выплат выбранного месяца",
        "Черновик не влияет на сводку. Списание выбранного баланса произойдёт после подтверждения расхода.",
        "Сохранить настройки",
        "Сформировать черновики",
        "Открыть черновики расходов",
        "Черновики ФОТ готовы:",
        "Расходы",
        "Расходы и черновики за выбранный период",
        "Добавить расход",
        "Фильтры и черновики",
        "Только черновики",
        "Выплаты ФОТ",
        "Черновик",
        "Сгенерирован",
        "Расчётный период:",
        "Автоматический черновик выплаты ФОТ за",
        "После подтверждения списывает выбранный способ оплаты и не дублирует ФОТ в сводке.",
        "Полная сумма",
        "Подтвердить",
        "Отменить",
        "Удалить",
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

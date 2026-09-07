from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-01-generate-payroll-drafts" / "build_guide.py"
SPEC = spec_from_file_location("axelio_confirm_payroll_series", PREVIOUS_PATH)
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


def ui_badge(draw, box, label, fill="#202c52", text_fill=PANEL_TEXT, outline=PANEL_LINE, size=12):
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill, outline=outline, width=1)
    center_text(draw, box, label, size=size, fill=text_fill)


def subtle_button(draw, box, label, size=12):
    draw.rounded_rectangle(box, radius=12, fill=PANEL_CARD, outline="#33436f", width=1)
    center_text(draw, box, label, size=size, fill=PANEL_TEXT)


def normal_button(draw, box, label, size=12, highlighted=False):
    x1, y1, x2, y2 = box
    if highlighted:
        draw.rounded_rectangle((x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius=17, outline=PURPLE, width=4)
    button(draw, box, label, size=size)


def select_field(draw, box, value, highlighted=False):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(
        box,
        radius=13,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (x1 + 20, y1 + 17), value, 15, True)
    cx = x2 - 24
    cy = (y1 + y2) // 2
    draw.polygon(((cx - 7, cy - 4), (cx + 7, cy - 4), (cx, cy + 5)), fill=PANEL_MUTED)


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
        highlighted = label == "Расходы"
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


def expenses_header(draw):
    panel_text(draw, (106, 350), "Расходы", 25, True)
    panel_text(draw, (106, 388), "Расходы и черновики за выбранный период", 13, False, PANEL_MUTED)
    button(draw, (792, 350, 962, 402), "Добавить расход", kind="primary", size=12)


def filters_card(draw, status, kind="Выплаты ФОТ", highlighted=None, top=430):
    box = (96, top, 984, top + 150)
    draw.rounded_rectangle(box, radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 18), "Фильтры и черновики", 17, True)
    status_box = (118, top + 62, 534, top + 124)
    kind_box = (554, top + 62, 962, top + 124)
    select_field(draw, status_box, status, highlighted=highlighted in {"status", "both"})
    select_field(draw, kind_box, kind, highlighted=highlighted in {"kind", "both"})


def expense_row(draw, top=606, status="draft", target=None, compact=False):
    bottom = top + (260 if compact else 300)
    box = (96, top, 984, bottom)
    draw.rounded_rectangle(box, radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Выплата ФОТ", 21, True)

    if status == "confirmed":
        ui_badge(draw, (122, top + 58, 270, top + 92), "Подтверждён", fill="#173a33", text_fill=GREEN)
    else:
        ui_badge(draw, (122, top + 58, 232, top + 92), "Черновик", fill="#3d3215", text_fill="#ffd97a")
    ui_badge(draw, (282 if status == "confirmed" else 244, top + 58, 418 if status == "confirmed" else 374, top + 92), "Выплата ФОТ")
    ui_badge(
        draw,
        (430 if status == "confirmed" else 386, top + 58, 646 if status == "confirmed" else 602, top + 92),
        "Сгенерирован 2026-09-01",
        size=11,
    )

    data_box = (116, top + 106, 658, top + 198)
    draw.rounded_rectangle(
        data_box,
        radius=12,
        fill=PANEL_CARD_2,
        outline=PURPLE if target == "details" else PANEL_LINE,
        width=4 if target == "details" else 1,
    )
    panel_text(draw, (136, top + 121), "2026-09-20   ·   Наличные", 14, True)
    panel_text(draw, (136, top + 156), "Расчётный период: 2026-09-01 — 2026-09-15", 13, False, PANEL_MUTED)

    panel_text(draw, (692, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (692, top + 52), "583 766,83 ₽", 22, True)

    if status == "confirmed":
        subtle_button(draw, (680, top + 105, 818, top + 153), "В черновик", size=11)
        subtle_button(draw, (830, top + 105, 960, top + 153), "Отменить", size=11)
        button(draw, (830, top + 165, 960, top + 213), "Удалить", kind="danger", size=11)
    else:
        normal_button(draw, (680, top + 105, 818, top + 153), "Подтвердить", size=11, highlighted=target == "confirm")
        subtle_button(draw, (830, top + 105, 960, top + 153), "Отменить", size=11)
        button(draw, (830, top + 165, 960, top + 213), "Удалить", kind="danger", size=11)

    if not compact:
        panel_text(
            draw,
            (122, top + 220),
            "Автоматический черновик выплаты ФОТ за 01.09.2026–15.09.2026",
            11,
            False,
            PANEL_MUTED,
        )
        fit_text(
            draw,
            "После подтверждения списывает выбранный способ оплаты и не дублирует ФОТ в сводке.",
            (122, top + 250),
            790,
            11,
            PANEL_MUTED,
            spacing=3,
        )


def confirmation_state(draw, top=590):
    draw.rounded_rectangle((96, top, 984, top + 270), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, top + 49), "Месяц 2026-09 · только подтверждённые", 13, False, PANEL_TEXT)
    panel_text(draw, (122, top + 76), "выплаты ФОТ · признано", 13, False, PANEL_TEXT)
    panel_text(draw, (310, top + 76), "235 326,35 ₽", 13, True, PANEL_TEXT)
    draw.rounded_rectangle((650, top + 26, 960, top + 88), radius=15, fill="#173a33", outline="#2d826c", width=2)
    draw.ellipse((674, top + 46, 696, top + 68), fill=GREEN)
    panel_text(draw, (710, top + 45), "Статус расхода обновлён", 12, True, GREEN)
    draw.line((122, top + 116, 958, top + 116), fill=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 142), "Записей", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 178), "1", 31, True)
    panel_text(draw, (190, top + 188), "Список обновлён по выбранному статусу.", 14, False, PANEL_MUTED)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как подтвердить\nвыплату ФОТ?", font=font(54, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Проверьте черновик и зафиксируйте выплату сотрудникам.",
        (66, 405),
        480,
        29,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "После подтверждения сумма спишется с выбранного способа оплаты.",
        (66, 632),
        470,
        27,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "confirm-payroll-payout-illustration.png").convert("RGB")
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
    draw.text((235, 877), "Откройте «Расходы»", font=font(33, True), fill=NAVY)
    draw.text((235, 930), "В блоке «Финансы» нужного заведения.", font=font(25), fill=MUTED)
    save(img, "01-cover.png")


def build_step_1():
    img = base_canvas()
    draw_step_header(img, "1", "ШАГ 1", "Откройте расходы", "На странице заведения найдите блок «Финансы».")
    draw_finance_entry(img)
    draw_bottom_note(img, "Нажмите «Расходы» — откроется список документов.")
    save(img, "02-step.png")


def build_step_2():
    img = base_canvas()
    draw_step_header(img, "2", "ШАГ 2", "Покажите черновики ФОТ", "Раскройте фильтры и выберите два значения.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только черновики", highlighted="both", top=438)
    draw.rounded_rectangle((96, 618, 984, 770), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 640), "Есть расходы в черновике", 18, True)
    fit_text(
        draw,
        "Черновиков: 1 · на сумму 583 766,83 ₽. Они не участвуют в прибыли и сводке, пока не подтверждены.",
        (122, 678),
        640,
        13,
        PANEL_MUTED,
        spacing=4,
    )
    subtle_button(draw, (770, 655, 952, 707), "Открыть черновики", size=11)
    draw_bottom_note(img, "Фильтры: «Только черновики» и «Выплаты ФОТ».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Проверьте выплату", "Сверьте дату, способ оплаты и расчётный период.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только черновики", top=426)
    expense_row(draw, top=594, target="details", compact=True)
    draw_bottom_note(img, "Сумма в примере — 583 766,83 руб., способ оплаты — «Наличные».")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Подтвердите расход", "Нажмите обычную вторичную кнопку в строке выплаты.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только черновики", top=426)
    expense_row(draw, top=594, target="confirm", compact=True)
    draw_bottom_note(img, "После подтверждения расход исчезнет из списка черновиков.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Откройте подтверждённые", "После уведомления смените фильтр статуса.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только подтверждённые", highlighted="status", top=426)
    confirmation_state(draw, top=594)
    draw_bottom_note(img, "Выберите «Только подтверждённые», чтобы снова увидеть выплату.")
    save(img, "06-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Выплата подтверждена", "Статус строки изменился, а выбранный баланс списан.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только подтверждённые", top=426)
    expense_row(draw, top=594, status="confirmed", compact=True)
    draw_bottom_note(img, "Статус — «Подтверждён». Доступны «В черновик», «Отменить» и «Удалить».")
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
    assert ("draw_" + "arrow") not in Path(__file__).read_text(encoding="utf-8")
    print(f"Verified {len(files)} RGB slides at 1080x1080; fixed step grid: {STEP_GRID}; arrows: 0")


def verify_ui_strings():
    repo = ROOT.parents[2]
    product_source = "\n".join(
        (repo / path).read_text(encoding="utf-8")
        for path in (
            "frontend/app-venue.html",
            "frontend/owner-expenses.html",
            "frontend/owner-expenses.js",
            "backend/app/routers/venue_expenses.py",
            "backend/app/services/finance/expenses.py",
            "backend/app/services/payroll/payments.py",
        )
    )
    required = (
        "Расходы",
        "Расходы и черновики за выбранный период",
        "Добавить расход",
        "Фильтры и черновики",
        "Только черновики",
        "Только подтверждённые",
        "Выплаты ФОТ",
        "Есть расходы в черновике",
        "Открыть черновики",
        "Выплата ФОТ",
        "Черновик",
        "Подтверждён",
        "Сгенерирован",
        "Расчётный период:",
        "Автоматический черновик выплаты ФОТ за",
        "После подтверждения списывает выбранный способ оплаты и не дублирует ФОТ в сводке.",
        "Полная сумма",
        "Подтвердить",
        "В черновик",
        "Отменить",
        "Удалить",
        "Статус расхода обновлён",
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

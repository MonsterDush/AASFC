from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-09-return-payroll-payout-to-draft" / "build_guide.py"
SPEC = spec_from_file_location("axelio_cancel_payroll_series", PREVIOUS_PATH)
SERIES = module_from_spec(SPEC)
SPEC.loader.exec_module(SERIES)
BASE = SERIES.SERIES

NAVY = SERIES.NAVY
TEXT = SERIES.TEXT
MUTED = SERIES.MUTED
PURPLE = SERIES.PURPLE
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
ui_badge = SERIES.ui_badge
subtle_button = SERIES.subtle_button
expenses_header = SERIES.expenses_header
filters_card = SERIES.filters_card
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


def draft_row(draw, top=594, target=None):
    BASE.expense_row(draw, top=top, status="draft", compact=True)
    if target == "details":
        draw.rounded_rectangle(
            (116, top + 106, 658, top + 198),
            radius=12,
            outline=PURPLE,
            width=4,
        )
    if target == "cancel":
        draw.rounded_rectangle(
            (822, top + 97, 968, top + 161),
            radius=17,
            outline=PURPLE,
            width=4,
        )


def cancelled_row(draw, top=594):
    box = (96, top, 984, top + 260)
    draw.rounded_rectangle(box, radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Выплата ФОТ", 21, True)
    ui_badge(draw, (122, top + 58, 238, top + 92), "Отменён", fill="#462031", text_fill="#ff9aac")
    ui_badge(draw, (250, top + 58, 386, top + 92), "Выплата ФОТ")
    ui_badge(draw, (398, top + 58, 614, top + 92), "Сгенерирован 2026-09-01", size=11)

    details_box = (116, top + 106, 638, top + 198)
    draw.rounded_rectangle(details_box, radius=12, fill=PANEL_CARD_2, outline=PANEL_LINE, width=1)
    panel_text(draw, (136, top + 121), "2026-09-20   ·   Наличные", 14, True)
    panel_text(draw, (136, top + 156), "Расчётный период: 2026-09-01 — 2026-09-15", 13, False, PANEL_MUTED)

    panel_text(draw, (672, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (672, top + 52), "583 766,83 ₽", 22, True)

    BASE.normal_button(draw, (650, top + 105, 788, top + 153), "Подтвердить", size=11)
    subtle_button(draw, (800, top + 105, 960, top + 153), "В черновик", size=11)
    button(draw, (830, top + 165, 960, top + 213), "Удалить", kind="danger", size=11)


def cancelled_state(draw, top=594):
    draw.rounded_rectangle((96, top, 984, top + 270), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    fit_text(
        draw,
        "За 2026-09 расходов нет (только черновики, выплаты ФОТ)",
        (122, top + 49),
        500,
        13,
        PANEL_TEXT,
        spacing=3,
    )
    draw.rounded_rectangle((650, top + 26, 960, top + 88), radius=15, fill="#173a33", outline="#2d826c", width=2)
    draw.ellipse((674, top + 46, 696, top + 68), fill=GREEN)
    panel_text(draw, (710, top + 45), "Статус расхода обновлён", 12, True, GREEN)
    draw.line((122, top + 116, 958, top + 116), fill=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 142), "Записей", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 178), "0", 31, True)
    panel_text(draw, (190, top + 188), "Нет расходов за выбранный период.", 14, False, PANEL_MUTED)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как отменить\nвыплату ФОТ?", font=font(54, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Уберите ошибочный черновик из будущих выплат.",
        (66, 405),
        480,
        29,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Документ останется в истории со статусом «Отменён».",
        (66, 632),
        470,
        27,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "cancel-payroll-payout-illustration.png").convert("RGB")
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
    panel_text(draw, (122, 640), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, 675), "Месяц 2026-09 · только черновики", 14, False, PANEL_TEXT)
    panel_text(draw, (122, 706), "выплаты ФОТ", 14, False, PANEL_TEXT)
    panel_text(draw, (770, 650), "Записей", 12, False, PANEL_MUTED)
    panel_text(draw, (770, 684), "1", 30, True)
    draw_bottom_note(img, "Фильтры: «Только черновики» и «Выплаты ФОТ».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Проверьте выплату", "Сверьте сумму, дату и расчётный период.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только черновики", top=426)
    draft_row(draw, top=594, target="details")
    draw_bottom_note(img, "В примере — 583 766,83 руб. через «Наличные».")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Отмените выплату", "Нажмите вторичную кнопку в строке черновика.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только черновики", top=426)
    draft_row(draw, top=594, target="cancel")
    draw_bottom_note(img, "Кнопка называется «Отменить» — без дополнительного окна.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Проверьте смену статуса", "Выплата исчезнет из списка черновиков.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только черновики", top=426)
    cancelled_state(draw, top=594)
    draw_bottom_note(img, "Уведомление: «Статус расхода обновлён».")
    save(img, "06-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Выплата отменена", "Откройте отменённые и проверьте строку.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    filters_card(draw, "Только отменённые", highlighted="status", top=426)
    cancelled_row(draw, top=594)
    draw_bottom_note(img, "Статус — «Отменён». Доступны «Подтвердить», «В черновик» и «Удалить».")
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
        "Только отменённые",
        "Выплаты ФОТ",
        "Выплата ФОТ",
        "Черновик",
        "Отменён",
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
        "Нет расходов за выбранный период.",
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

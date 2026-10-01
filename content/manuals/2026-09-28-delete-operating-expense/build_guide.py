from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-25-edit-operating-expense" / "build_guide.py"
SPEC = spec_from_file_location("axelio_expense_series", PREVIOUS_PATH)
SERIES = module_from_spec(SPEC)
SPEC.loader.exec_module(SERIES)
BASE = SERIES.BASE

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
expenses_header = SERIES.expenses_header
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


def list_header(draw, *, count, recognized):
    expenses_header(draw)
    draw.rounded_rectangle((96, 438, 984, 548), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 458), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, 492), f"Месяц 2026-09 · все статусы · все виды · признано {recognized}", 12, False)
    panel_text(draw, (806, 458), "Записей", 12, False, PANEL_MUTED)
    panel_text(draw, (806, 489), str(count), 29, True)


def target_row(draw, *, highlight=None):
    top = 570
    draw.rounded_rectangle((96, top, 984, top + 316), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Хозтовары", 21, True)
    ui_badge(draw, (122, top + 58, 252, top + 92), "Подтверждён", fill="#173a33", text_fill="#76e2ba")
    ui_badge(draw, (266, top + 58, 474, top + 92), "Сгенерирован 2026-09-01", size=10)
    panel_text(draw, (122, top + 112), "2026-09-25   ·   Local Partner   ·   Эквайринг", 14, True)
    panel_text(draw, (122, top + 145), "Все смены", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 178), "Текстиль, аромасвечи и расходники для VIP-комнат", 12, False)
    panel_text(draw, (122, top + 222), "ПРИЗНАНО В 2026-09", 10, True, PANEL_MUTED)
    panel_text(draw, (122, top + 247), "2026-09-01 · 6 847,60 ₽", 12, False)
    panel_text(draw, (668, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (668, top + 52), "6 847,60 ₽", 22, True)
    BASE.subtle_button(draw, (624, top + 105, 778, top + 153), "В черновик", size=10)
    BASE.subtle_button(draw, (798, top + 105, 960, top + 153), "Отменить", size=10)
    BASE.normal_button(draw, (650, top + 165, 792, top + 213), "Изменить", size=10)
    button(draw, (808, top + 165, 960, top + 213), "Удалить", kind="danger", size=10)
    targets = {
        "details": (110, top + 101, 630, top + 280),
        "delete": (800, top + 157, 968, top + 221),
    }
    if highlight:
        draw.rounded_rectangle(targets[highlight], radius=17, outline=PURPLE, width=4)


def remaining_row(draw):
    top = 570
    draw.rounded_rectangle((96, top, 984, top + 278), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Барная закупка", 21, True)
    ui_badge(draw, (122, top + 58, 252, top + 92), "Подтверждён", fill="#173a33", text_fill="#76e2ba")
    ui_badge(draw, (266, top + 58, 474, top + 92), "Сгенерирован 2026-09-01", size=10)
    panel_text(draw, (122, top + 112), "2026-09-21   ·   Metro Cash & Carry   ·   Эквайринг", 14, True)
    panel_text(draw, (122, top + 145), "Все смены", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 178), "Дозакупка фруктов, напитков и сиропов под конец месяца", 12, False)
    panel_text(draw, (122, top + 222), "ПРИЗНАНО В 2026-09", 10, True, PANEL_MUTED)
    panel_text(draw, (122, top + 247), "2026-09-01 · 14 596,20 ₽", 12, False)
    panel_text(draw, (668, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (668, top + 52), "14 596,20 ₽", 22, True)
    draw.rounded_rectangle((110, top + 101, 960, top + 166), radius=17, outline=PURPLE, width=4)


def confirm_prompt(draw):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    draw.rounded_rectangle((222, 488, 858, 740), radius=24, fill="#ffffff", outline="#d8d2f5", width=2)
    draw.ellipse((286, 552, 374, 640), fill="#fce3e8")
    draw.line((315, 582, 345, 612), fill="#b53a55", width=8)
    draw.line((345, 582, 315, 612), fill="#b53a55", width=8)
    draw.text((413, 548), "Удалить расход?", font=font(29, True), fill=NAVY)
    draw.text((413, 605), "Системное подтверждение браузера", font=font(18), fill=MUTED)
    draw.rounded_rectangle((208, 474, 872, 754), radius=29, outline=PURPLE, width=4)


def empty_target_state(draw, *, toast_visible=False):
    list_header(draw, count=7, recognized="228 478,75 ₽")
    remaining_row(draw)
    if toast_visible:
        draw.rounded_rectangle((646, 326, 984, 380), radius=14, fill="#173a33", outline="#2d826c", width=2)
        draw.ellipse((669, 343, 689, 363), fill=GREEN)
        panel_text(draw, (704, 341), "Расход удалён", 12, True, GREEN)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 177), "Как удалить\nоперационный\nрасход?", font=font(49, True), fill=NAVY, spacing=3)
    fit_text(draw, "Удалите ошибочный документ вместе с признанием и проводкой.", (66, 430), 485, 27, TEXT, spacing=7)
    fit_text(draw, "Действие необратимо — сначала обязательно проверьте строку.", (66, 642), 485, 25, TEXT, spacing=7)

    draw.rounded_rectangle((624, 305, 1006, 714), radius=46, fill="#17234b")
    draw.rounded_rectangle((690, 366, 938, 654), radius=28, fill="#ffffff")
    draw.rounded_rectangle((724, 414, 898, 442), radius=13, fill="#ddd8f4")
    draw.rounded_rectangle((724, 474, 870, 502), radius=13, fill="#e9e6f8")
    draw.rounded_rectangle((724, 534, 846, 562), radius=13, fill="#e9e6f8")
    draw.ellipse((820, 315, 970, 465), fill="#ef9aaf")
    draw.line((856, 356, 934, 434), fill="#102342", width=15)
    draw.line((934, 356, 856, 434), fill="#102342", width=15)

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
    draw_step_header(img, "2", "ШАГ 2", "Проверьте расход", "Сверьте дату, поставщика, сумму и комментарий.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    list_header(draw, count=8, recognized="235 326,35 ₽")
    target_row(draw, highlight="details")
    draw_bottom_note(img, "Удаление нельзя отменить — убедитесь, что выбрана нужная строка.")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Нажмите «Удалить»", "Используйте красную danger-кнопку в строке расхода.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    list_header(draw, count=8, recognized="235 326,35 ₽")
    target_row(draw, highlight="delete")
    draw_bottom_note(img, "Красный стиль соответствует реальной кнопке удаления.")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Подтвердите действие", "Браузер покажет системный вопрос перед удалением.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    confirm_prompt(draw)
    draw_bottom_note(img, "Точный текст вопроса: «Удалить расход?»")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Проверьте уведомление", "После подтверждения документ исчезнет из списка.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    empty_target_state(draw, toast_visible=True)
    draw_bottom_note(img, "Axelio покажет уведомление «Расход удалён».")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Сверьте итог списка", "Количество записей и признанная сумма пересчитаются.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    empty_target_state(draw)
    draw_bottom_note(img, "В примере осталось 7 записей, признано 228 478,75 руб.")
    save(img, "07-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Расход удалён", "Документ больше не участвует в расходах за месяц.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    empty_target_state(draw, toast_visible=True)
    draw_bottom_note(img, "Расход, его аллокации, признание и проводка удалены.")
    save(img, "08-result.png")


def verify_outputs():
    files = ["01-cover.png", "02-step.png", "03-step.png", "04-step.png", "05-step.png", "06-step.png", "07-step.png", "08-result.png"]
    for filename in files:
        with Image.open(ROOT / filename) as image:
            assert image.size == (1080, 1080), f"{filename}: {image.size}"
            assert image.mode == "RGB", f"{filename}: {image.mode}"
    assert STEP_GRID == SERIES.STEP_GRID
    assert ("draw_" + "arrow") not in Path(__file__).read_text(encoding="utf-8")
    print(f"Verified {len(files)} RGB slides at 1080x1080; fixed step grid: {STEP_GRID}; arrows: 0")


def verify_ui_strings():
    repo = ROOT.parents[2]
    source = "\n".join((repo / path).read_text(encoding="utf-8") for path in (
        "frontend/app-venue.html", "frontend/owner-expenses.html", "frontend/owner-expenses.js"
    ))
    required = (
        "Расходы", "Финансы", "Удалить", "Удалить расход?", "Расход удалён", "Подтверждён",
        "В черновик", "Отменить", "Изменить", "Признано в", "Полная сумма",
    )
    missing = [label for label in required if label not in source]
    assert not missing, f"UI strings not found: {missing}"
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

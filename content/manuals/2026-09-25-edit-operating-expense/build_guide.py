from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-23-cancel-operating-expense" / "build_guide.py"
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


def list_header(draw, recognized):
    expenses_header(draw)
    draw.rounded_rectangle((96, 438, 984, 548), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 458), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, 492), f"Месяц 2026-09 · все статусы · все виды · признано {recognized}", 12, False)
    panel_text(draw, (806, 458), "Записей", 12, False, PANEL_MUTED)
    panel_text(draw, (806, 489), "8", 29, True)


def expense_row(draw, *, updated=False, highlight=None):
    top = 570
    draw.rounded_rectangle((96, top, 984, top + 316), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Хозтовары", 21, True)
    ui_badge(draw, (122, top + 58, 252, top + 92), "Подтверждён", fill="#173a33", text_fill="#76e2ba")
    ui_badge(draw, (266, top + 58, 474, top + 92), "Сгенерирован 2026-09-01", size=10)
    panel_text(draw, (122, top + 112), "2026-09-25   ·   Local Partner   ·   Эквайринг", 14, True)
    panel_text(draw, (122, top + 145), "Все смены", 13, False, PANEL_MUTED)
    comment = (
        "Текстиль, аромасвечи и расходники для VIP-комнат и террасы"
        if updated else "Текстиль, аромасвечи и расходники для VIP-комнат"
    )
    panel_text(draw, (122, top + 178), comment, 12, False)
    amount = "7 247,60 ₽" if updated else "6 847,60 ₽"
    panel_text(draw, (122, top + 222), "ПРИЗНАНО В 2026-09", 10, True, PANEL_MUTED)
    panel_text(draw, (122, top + 247), f"2026-09-01 · {amount}", 12, False)
    panel_text(draw, (668, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (668, top + 52), amount, 22, True)
    BASE.subtle_button(draw, (624, top + 105, 778, top + 153), "В черновик", size=10)
    BASE.subtle_button(draw, (798, top + 105, 960, top + 153), "Отменить", size=10)
    BASE.normal_button(draw, (650, top + 165, 792, top + 213), "Изменить", size=10)
    button(draw, (808, top + 165, 960, top + 213), "Удалить", kind="danger", size=10)
    targets = {
        "details": (110, top + 101, 630, top + 280),
        "edit": (642, top + 157, 800, top + 221),
        "result": (110, top + 101, 960, top + 280),
    }
    if highlight:
        draw.rounded_rectangle(targets[highlight], radius=17, outline=PURPLE, width=4)


def field(draw, box, label, value, *, highlighted=False, multiline=False):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 25), label, 11, True, PANEL_MUTED)
    draw.rounded_rectangle(box, radius=11, fill=PANEL_CARD_2,
                           outline=PURPLE if highlighted else PANEL_LINE,
                           width=4 if highlighted else 2)
    if multiline:
        fit_text(draw, value, (x1 + 14, y1 + 12), x2 - x1 - 28, 12, PANEL_TEXT, spacing=3)
    else:
        panel_text(draw, (x1 + 14, y1 + 15), value, 12, True)


def edit_modal(draw, *, focus):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (124, 397), "Редактировать расход", 20, True)
    draw.ellipse((922, 393, 956, 427), fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (933, 398), "×", 16, True, PANEL_MUTED)

    field(draw, (124, 474, 390, 530), "Категория", "Хозтовары")
    field(draw, (407, 474, 673, 530), "Поставщик", "Local Partner")
    field(draw, (690, 474, 956, 530), "Оплачено через", "Эквайринг")

    field(draw, (124, 582, 390, 638), "Сумма, ₽", "7247.60", highlighted=focus == "amount")
    field(draw, (407, 582, 673, 638), "Дата расхода", "2026-09-25")
    field(draw, (690, 582, 956, 638), "Распределить на месяцев", "1")

    field(draw, (124, 690, 673, 762), "Комментарий",
          "Текстиль, аромасвечи и расходники для VIP-комнат и террасы",
          highlighted=focus == "comment", multiline=True)
    field(draw, (690, 690, 956, 762), "Статус", "Подтверждён")

    button(draw, (124, 804, 318, 856), "Сохранить", kind="primary", size=12)
    BASE.subtle_button(draw, (336, 804, 486, 856), "Отмена", size=12)
    if focus == "save":
        draw.rounded_rectangle((116, 796, 326, 864), radius=16, outline=PURPLE, width=4)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 177), "Как изменить\nоперационный\nрасход?", font=font(49, True), fill=NAVY, spacing=3)
    fit_text(draw, "Исправьте сумму или описание без создания нового документа.", (66, 430), 485, 27, TEXT, spacing=7)
    fit_text(draw, "После сохранения признание за месяц пересчитается автоматически.", (66, 642), 485, 25, TEXT, spacing=7)

    draw.rounded_rectangle((624, 305, 1006, 714), radius=46, fill="#17234b")
    draw.rounded_rectangle((690, 366, 938, 654), radius=28, fill="#ffffff")
    draw.rounded_rectangle((724, 414, 898, 442), radius=13, fill="#ddd8f4")
    draw.rounded_rectangle((724, 474, 870, 502), radius=13, fill="#e9e6f8")
    draw.rounded_rectangle((724, 534, 846, 562), radius=13, fill="#e9e6f8")
    draw.ellipse((820, 315, 970, 465), fill="#f5bd74")
    draw.polygon(((847, 410), (872, 350), (935, 410), (918, 427), (858, 428)), fill="#102342")
    draw.rounded_rectangle((838, 402, 928, 426), radius=8, fill="#102342")

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
    draw_step_header(img, "2", "ШАГ 2", "Выберите нужный расход", "Сверьте дату, поставщика, сумму и комментарий.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    list_header(draw, "235 326,35 ₽")
    expense_row(draw, highlight="details")
    draw_bottom_note(img, "До изменения признано 6 847,60 руб.")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Откройте редактирование", "В строке расхода нажмите «Изменить».")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    list_header(draw, "235 326,35 ₽")
    expense_row(draw, highlight="edit")
    draw_bottom_note(img, "«Изменить» — обычная вторичная кнопка интерфейса.")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Исправьте сумму", "В форме «Редактировать расход» обновите сумму.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    edit_modal(draw, focus="amount")
    draw_bottom_note(img, "В примере новая сумма — 7247.60.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Обновите комментарий", "При необходимости уточните назначение расхода.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    edit_modal(draw, focus="comment")
    draw_bottom_note(img, "Остальные поля можно оставить без изменений.")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Сохраните изменения", "Проверьте поля и нажмите primary-кнопку «Сохранить».")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    edit_modal(draw, focus="save")
    draw_bottom_note(img, "«Отмена» закроет форму без сохранения.")
    save(img, "07-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Расход обновлён", "Новые данные сразу появились в списке.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    list_header(draw, "235 726,35 ₽")
    expense_row(draw, updated=True, highlight="result")
    draw.rounded_rectangle((623, 325, 984, 378), radius=14, fill="#173a33", outline="#2d826c", width=2)
    draw.ellipse((646, 341, 666, 361), fill=GREEN)
    panel_text(draw, (681, 339), "Расход обновлён", 12, True, GREEN)
    draw_bottom_note(img, "Признанная сумма пересчитана до 7 247,60 руб.")
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
        "Расходы", "Финансы", "Изменить", "Редактировать расход", "Категория", "Поставщик",
        "Оплачено через", "Сумма, ₽", "Дата расхода", "Распределить на месяцев", "Статус",
        "Комментарий", "Сохранить", "Отмена", "Расход обновлён", "Подтверждён",
        "Признано в", "Полная сумма",
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

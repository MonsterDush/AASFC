from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-30-create-recurring-expense-rule" / "build_guide.py"
SPEC = spec_from_file_location("axelio_recurring_series", PREVIOUS_PATH)
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
draw_finance_entry = SERIES.draw_finance_entry
recurring_entry = SERIES.recurring_entry

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


def toolbar(draw, *, focus=None):
    panel_text(draw, (122, 397), "Регулярные расходы", 22, True)
    panel_text(draw, (122, 432), "Axelio E2E Lounge", 12, False, PANEL_MUTED)
    draw.rounded_rectangle((122, 468, 300, 516), radius=12, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (144, 482), "2026-10", 12, True)
    BASE.subtle_button(draw, (492, 392, 634, 440), "Открыть расходы", size=8)
    BASE.normal_button(draw, (646, 392, 804, 440), "Сгенерировать за месяц", size=7)
    button(draw, (816, 392, 960, 440), "Добавить правило", kind="primary", size=7)
    targets = {
        "month": (110, 456, 312, 528),
        "generate": (636, 380, 814, 452),
    }
    if focus:
        draw.rounded_rectangle(targets[focus], radius=15, outline=PURPLE, width=4)


def rule_row(draw, *, highlighted=False):
    draw.rounded_rectangle((122, 562, 958, 842), radius=16, fill=PANEL_CARD, outline=PURPLE if highlighted else PANEL_LINE, width=4 if highlighted else 2)
    panel_text(draw, (146, 584), "Аренда склада", 18, True)
    ui_badge(draw, (146, 620, 228, 652), "Фикс", size=9)
    ui_badge(draw, (240, 620, 340, 652), "Активно", fill="#173a33", text_fill="#76e2ba", size=9)
    panel_text(draw, (146, 673), "Аренда · Local Partner", 12, False, PANEL_MUTED)
    panel_text(draw, (146, 705), "Сумма: 135 000,00 ₽", 13, True)
    panel_text(draw, (146, 737), "Период действия: 2026-10-01 → ∞", 11, False)
    panel_text(draw, (146, 769), "День месяца: 5 · Размазать на: 1 мес.", 11, False)
    panel_text(draw, (146, 801), "База/списание: Списывать через СБП", 11, False)
    panel_text(draw, (696, 681), "135 000,00 ₽", 18, True)
    panel_text(draw, (696, 716), "Фиксированный режим", 10, False, PANEL_MUTED)
    BASE.subtle_button(draw, (650, 766, 782, 810), "Сгенерировать", size=7)
    BASE.normal_button(draw, (794, 766, 884, 810), "Изменить", size=7)


def rules_screen(draw, *, focus=None):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    toolbar(draw, focus=focus if focus in {"month", "generate"} else None)
    rule_row(draw, highlighted=focus == "rule")


def generate_action(draw):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 397), "Регулярные расходы", 22, True)
    panel_text(draw, (122, 432), "Axelio E2E Lounge", 12, False, PANEL_MUTED)
    draw.rounded_rectangle((122, 486, 934, 612), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    BASE.subtle_button(draw, (146, 522, 356, 574), "Открыть расходы", size=10)
    BASE.normal_button(draw, (378, 522, 654, 574), "Сгенерировать за месяц", size=10)
    button(draw, (676, 522, 910, 574), "Добавить правило", kind="primary", size=10)
    draw.rounded_rectangle((366, 510, 666, 586), radius=16, outline=PURPLE, width=4)
    draw.rounded_rectangle((122, 654, 934, 802), radius=16, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (146, 680), "Месяц генерации", 10, True, PANEL_MUTED)
    panel_text(draw, (146, 710), "2026-10", 15, True)
    panel_text(draw, (408, 680), "Всего правил", 10, True, PANEL_MUTED)
    panel_text(draw, (408, 710), "1", 22, True)
    panel_text(draw, (650, 680), "Активных", 10, True, PANEL_MUTED)
    panel_text(draw, (650, 710), "1", 22, True)


def generation_result(draw, *, focus_open=False):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 397), "Регулярные расходы", 22, True)
    draw.rounded_rectangle((122, 456, 958, 814), radius=18, fill=PANEL_CARD, outline=PURPLE, width=4)
    panel_text(draw, (146, 480), "Результат последней генерации", 18, True)
    panel_text(draw, (146, 518), "Месяц 2026-10 · создано 1 · пропущено 0", 12, False, PANEL_MUTED)
    BASE.subtle_button(draw, (680, 474, 934, 524), "Открыть расходы месяца", size=9)
    panel_text(draw, (146, 580), "Создано", 13, True)
    draw.rounded_rectangle((146, 620, 934, 724), radius=14, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (170, 642), "Аренда", 15, True)
    panel_text(draw, (170, 678), "2026-10-05 · Черновик", 11, False, PANEL_MUTED)
    panel_text(draw, (766, 653), "135 000,00 ₽", 16, True)
    draw.rounded_rectangle((146, 758, 604, 796), radius=10, fill="#173a33", outline="#2d826c", width=2)
    panel_text(draw, (166, 768), "Создано: 1, обновлено: 0, пропущено: 0", 10, True, GREEN)
    if focus_open:
        draw.rounded_rectangle((668, 462, 946, 536), radius=15, outline=PURPLE, width=4)


def generated_expense(draw):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 397), "Расходы", 22, True)
    panel_text(draw, (122, 432), "октябрь 2026 г.", 12, False, PANEL_MUTED)
    panel_text(draw, (708, 404), "Записей", 10, True, PANEL_MUTED)
    panel_text(draw, (708, 432), "9", 20, True)
    draw.rounded_rectangle((122, 478, 958, 846), radius=16, fill=PANEL_CARD, outline=PURPLE, width=4)
    panel_text(draw, (146, 500), "Аренда", 18, True)
    ui_badge(draw, (146, 536, 252, 568), "Черновик", fill="#3a3018", text_fill="#f4cf70", size=9)
    ui_badge(draw, (264, 536, 378, 568), "Регулярный", size=9)
    ui_badge(draw, (390, 536, 592, 568), "Сгенерирован 2026-10-01", size=8)
    panel_text(draw, (146, 592), "2026-10-05   ·   Local Partner   ·   СБП", 12, True)
    panel_text(draw, (146, 623), "Все смены", 11, False, PANEL_MUTED)
    panel_text(draw, (146, 654), "[REGULAR] Аренда склада · 2026-10 · фикс", 11, False)
    panel_text(draw, (146, 690), "ПРИЗНАНО В 2026-10", 9, True, PANEL_MUTED)
    panel_text(draw, (146, 716), "0,00 ₽", 12, True)
    fit_text(draw, "Документ создан из правила регулярного расхода. После подтверждения он попадёт в расходы и сводку.", (146, 752), 484, 10, PANEL_MUTED, spacing=3)
    panel_text(draw, (700, 510), "ПОЛНАЯ СУММА", 9, True, PANEL_MUTED)
    panel_text(draw, (700, 540), "135 000,00 ₽", 18, True)
    BASE.normal_button(draw, (664, 616, 784, 660), "Подтвердить", size=7)
    button(draw, (796, 616, 906, 660), "Отменить", kind="ghost", size=7)
    BASE.normal_button(draw, (664, 676, 784, 720), "Изменить", size=7)
    button(draw, (796, 676, 906, 720), "Удалить", kind="danger", size=7)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 177), "Как\nсгенерировать\nрасходы\nза месяц?", font=font(47, True), fill=NAVY, spacing=2)
    fit_text(draw, "Запустите активные правила для выбранного месяца одной кнопкой.", (66, 474), 485, 27, TEXT, spacing=7)
    fit_text(draw, "Axelio создаст черновики и покажет результат генерации.", (66, 658), 485, 25, TEXT, spacing=7)
    draw.rounded_rectangle((624, 305, 1006, 714), radius=46, fill="#17234b")
    draw.rounded_rectangle((684, 358, 946, 662), radius=28, fill="#ffffff")
    draw.rounded_rectangle((720, 405, 910, 437), radius=13, fill="#ddd8f4")
    draw.rounded_rectangle((720, 466, 878, 498), radius=13, fill="#e9e6f8")
    draw.rounded_rectangle((720, 527, 850, 559), radius=13, fill="#e9e6f8")
    draw.ellipse((817, 312, 975, 470), fill="#81d6b9")
    draw.text((857, 337), "1", font=font(62, True), fill="#102342")
    rounded_shadow(img, (62, 842, 1018, 1015), radius=28, fill="#ffffff", outline="#d4cdf6", width=2, blur=14)
    draw = ImageDraw.Draw(img)
    draw.ellipse((106, 881, 194, 969), fill=PURPLE)
    draw.text((140, 901), "1", font=font(43, True), fill="white")
    draw.text((235, 877), "Откройте «Расходы»", font=font(33, True), fill=NAVY)
    draw.text((235, 930), "В разделе «Финансы» нужного заведения.", font=font(25), fill=MUTED)
    save(img, "01-cover.png")


def step(number, title, explanation, note, painter, filename):
    img = base_canvas()
    draw_step_header(img, str(number), f"ШАГ {number}", title, explanation)
    draw_ui_frame(img)
    painter(ImageDraw.Draw(img))
    draw_bottom_note(img, note)
    save(img, filename)


def build_all():
    build_cover()
    step(1, "Откройте расходы", "На странице заведения найдите блок «Финансы».",
         "Нажмите «Расходы» — откроется список документов.", lambda d: draw_finance_entry(d._image), "02-step.png")
    step(2, "Откройте регулярные расходы", "Разверните «Справочники и быстрые действия».",
         "В карточке «Регулярные расходы» нажмите «Открыть».", recurring_entry, "03-step.png")
    step(3, "Выберите месяц", "В верхней панели укажите месяц генерации.",
         "В примере выбран октябрь 2026 года: «2026-10».", lambda d: rules_screen(d, focus="month"), "04-step.png")
    step(4, "Проверьте правило", "Убедитесь, что нужное правило активно в выбранном месяце.",
         "Правило «Аренда склада» активно с 1 октября.", lambda d: rules_screen(d, focus="rule"), "05-step.png")
    step(5, "Запустите генерацию", "Нажмите обычную кнопку «Сгенерировать за месяц».",
         "Axelio обработает все подходящие активные правила.", generate_action, "06-step.png")
    step(6, "Проверьте результат", "Откроется блок «Результат последней генерации».",
         "В E2E создан 1 черновик на 135 000,00 руб.", lambda d: generation_result(d, focus_open=False), "07-step.png")
    step(7, "Откройте расходы", "Нажмите «Открыть расходы месяца» в блоке результата.",
         "Ссылка ведёт в список расходов выбранного месяца.", lambda d: generation_result(d, focus_open=True), "08-step.png")

    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Черновик создан", "Новый расход появился в списке за октябрь.")
    draw_ui_frame(img)
    generated_expense(ImageDraw.Draw(img))
    draw_bottom_note(img, "После подтверждения расход попадёт в расходы и сводку.")
    save(img, "09-result.png")


def verify_outputs():
    files = ["01-cover.png"] + [f"{index:02d}-step.png" for index in range(2, 9)] + ["09-result.png"]
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
        "frontend/owner-expenses.html", "frontend/owner-expenses.js",
        "frontend/owner-recurring-expenses.html", "frontend/owner-recurring-expenses.js",
    ))
    required = (
        "Справочники и быстрые действия", "Регулярные расходы", "Открыть", "Сгенерировать за месяц",
        "Месяц генерации", "Результат последней генерации", "Открыть расходы месяца", "Создано",
        "Черновик", "Регулярный", "Сгенерирован", "Признано в", "Полная сумма", "Подтвердить",
        "Отменить", "Изменить", "Удалить",
        "Документ создан из правила регулярного расхода. После подтверждения он попадёт в расходы и сводку.",
    )
    missing = [label for label in required if label not in source]
    assert not missing, f"UI strings not found: {missing}"
    print(f"Verified {len(required)} current UI strings")


if __name__ == "__main__":
    build_all()
    verify_outputs()
    verify_ui_strings()

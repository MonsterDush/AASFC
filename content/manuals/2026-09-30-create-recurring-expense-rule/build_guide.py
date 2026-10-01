from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-28-delete-operating-expense" / "build_guide.py"
SPEC = spec_from_file_location("axelio_manual_series", PREVIOUS_PATH)
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


def field(draw, box, label, value, *, highlighted=False, placeholder=False, multiline=False):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 25), label, 11, True, PANEL_MUTED)
    draw.rounded_rectangle(
        box,
        radius=11,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    color = PANEL_MUTED if placeholder else PANEL_TEXT
    if multiline:
        fit_text(draw, value, (x1 + 14, y1 + 11), x2 - x1 - 28, 12, color, spacing=3)
    else:
        panel_text(draw, (x1 + 14, y1 + 15), value, 12, not placeholder, color)


def recurring_entry(draw):
    draw.rounded_rectangle((96, 370, 984, 886), radius=22, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 397), "Расходы", 22, True)
    BASE.subtle_button(draw, (768, 392, 958, 440), "Добавить расход", size=10)
    panel_text(draw, (122, 470), "Справочники и быстрые действия", 15, True)
    draw.rounded_rectangle((122, 520, 958, 694), radius=18, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    draw.ellipse((150, 559, 214, 623), fill="#33266f")
    panel_text(draw, (172, 573), "₽", 21, True, "#bdb1ff")
    panel_text(draw, (244, 552), "Регулярные расходы", 19, True)
    panel_text(draw, (244, 591), "Создавайте правила и запускайте их по месяцу.", 12, False, PANEL_MUTED)
    BASE.subtle_button(draw, (806, 574, 932, 622), "Открыть", size=11)
    draw.rounded_rectangle((794, 562, 944, 634), radius=15, outline=PURPLE, width=4)


def rules_page(draw, *, highlight_add=False):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 397), "Регулярные расходы", 22, True)
    panel_text(draw, (122, 432), "Axelio E2E Lounge", 12, False, PANEL_MUTED)
    BASE.subtle_button(draw, (492, 392, 634, 440), "Открыть расходы", size=8)
    BASE.normal_button(draw, (646, 392, 804, 440), "Сгенерировать за месяц", size=7)
    button(draw, (816, 392, 960, 440), "Добавить правило", kind="primary", size=7)
    panel_text(draw, (122, 477), "Месяц генерации", 10, True, PANEL_MUTED)
    panel_text(draw, (122, 505), "2026-09", 15, True)
    panel_text(draw, (425, 477), "Всего правил", 10, True, PANEL_MUTED)
    panel_text(draw, (425, 505), "0", 24, True)
    panel_text(draw, (680, 477), "Активных", 10, True, PANEL_MUTED)
    panel_text(draw, (680, 505), "0", 24, True)
    panel_text(draw, (122, 575), "Список правил", 18, True)
    panel_text(draw, (122, 610), "Каждое правило можно запустить вручную, отредактировать или удалить.", 11, False, PANEL_MUTED)
    draw.rounded_rectangle((122, 666, 958, 822), radius=16, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (342, 724), "Нет правил регулярных расходов.", 13, False, PANEL_MUTED)
    if highlight_add:
        draw.rounded_rectangle((806, 380, 970, 452), radius=15, outline=PURPLE, width=4)


def form_shell(draw, title="Добавить правило"):
    draw.rounded_rectangle((96, 365, 984, 890), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    draw.rounded_rectangle((112, 382, 968, 874), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (136, 405), title, 20, True)
    draw.ellipse((912, 400, 946, 434), fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (923, 405), "×", 16, True, PANEL_MUTED)


def form_main(draw):
    form_shell(draw)
    field(draw, (136, 486, 405, 542), "Название", "Аренда склада", highlighted=True)
    field(draw, (423, 486, 692, 542), "Категория", "Аренда", highlighted=True)
    field(draw, (710, 486, 944, 542), "Поставщик", "Local Partner", highlighted=True)
    field(draw, (136, 612, 405, 668), "Оплачивать через", "СБП", highlighted=True)
    panel_text(draw, (136, 724), "Поля и значения повторяют реальную форму Axelio.", 12, False, PANEL_MUTED)


def form_schedule(draw):
    form_shell(draw)
    field(draw, (136, 486, 405, 542), "Дата старта", "2026-10-01", highlighted=True)
    field(draw, (423, 486, 692, 542), "Дата окончания", "", placeholder=True)
    field(draw, (710, 486, 944, 542), "День месяца", "5", highlighted=True)
    field(draw, (136, 612, 405, 668), "Распределить на месяцев", "1", highlighted=True)
    panel_text(draw, (136, 724), "Пустая дата окончания оставляет правило бессрочным.", 12, False, PANEL_MUTED)


def form_amount(draw, *, focus_button=False):
    form_shell(draw)
    field(draw, (136, 486, 405, 542), "Режим", "Фиксированная сумма", highlighted=not focus_button)
    field(draw, (423, 486, 692, 542), "Сумма, ₽", "135000.00", highlighted=not focus_button)
    draw.rounded_rectangle((710, 482, 944, 548), radius=11, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    draw.rounded_rectangle((730, 502, 752, 524), radius=5, fill="#604bd8")
    panel_text(draw, (766, 498), "Правило активно", 12, True)
    field(draw, (136, 626, 944, 706), "Комментарий / описание", "Аренда склада и подсобного помещения", highlighted=not focus_button, multiline=True)
    BASE.normal_button(draw, (136, 772, 292, 826), "Добавить", size=12)
    button(draw, (310, 772, 452, 826), "Отмена", kind="ghost", size=12)
    if focus_button:
        draw.rounded_rectangle((124, 760, 304, 838), radius=16, outline=PURPLE, width=4)


def result_page(draw, *, toast=True):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 397), "Регулярные расходы", 22, True)
    button(draw, (788, 392, 960, 440), "Добавить правило", kind="primary", size=9)
    panel_text(draw, (122, 477), "Месяц генерации", 10, True, PANEL_MUTED)
    panel_text(draw, (122, 505), "2026-09", 15, True)
    panel_text(draw, (425, 477), "Всего правил", 10, True, PANEL_MUTED)
    panel_text(draw, (425, 505), "1", 24, True)
    panel_text(draw, (680, 477), "Активных", 10, True, PANEL_MUTED)
    panel_text(draw, (680, 505), "1", 24, True)
    draw.rounded_rectangle((122, 565, 958, 840), radius=16, fill=PANEL_CARD, outline=PURPLE, width=4)
    panel_text(draw, (146, 586), "Аренда склада", 18, True)
    ui_badge(draw, (146, 622, 228, 654), "Фикс", size=9)
    ui_badge(draw, (240, 622, 340, 654), "Активно", fill="#173a33", text_fill="#76e2ba", size=9)
    panel_text(draw, (146, 674), "Аренда · Local Partner", 12, False, PANEL_MUTED)
    panel_text(draw, (146, 706), "Сумма: 135 000,00 ₽", 13, True)
    panel_text(draw, (146, 738), "Период действия: 2026-10-01 → ∞", 11, False)
    panel_text(draw, (146, 770), "День месяца: 5 · Размазать на: 1 мес.", 11, False)
    panel_text(draw, (146, 802), "База/списание: Списывать через СБП", 11, False)
    panel_text(draw, (690, 680), "135 000,00 ₽", 18, True)
    panel_text(draw, (690, 715), "Фиксированный режим", 10, False, PANEL_MUTED)
    BASE.subtle_button(draw, (634, 764, 758, 808), "Сгенерировать", size=7)
    BASE.normal_button(draw, (770, 764, 858, 808), "Изменить", size=7)
    button(draw, (870, 764, 942, 808), "Удалить", kind="danger", size=7)
    if toast:
        draw.rounded_rectangle((648, 326, 984, 380), radius=14, fill="#173a33", outline="#2d826c", width=2)
        draw.ellipse((669, 343, 689, 363), fill=GREEN)
        panel_text(draw, (704, 341), "Правило добавлено", 12, True, GREEN)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 177), "Как создать\nправило\nрегулярного\nрасхода?", font=font(46, True), fill=NAVY, spacing=2)
    fit_text(draw, "Автоматизируйте аренду и другие повторяющиеся платежи.", (66, 470), 485, 27, TEXT, spacing=7)
    fit_text(draw, "Задайте сумму, день списания и период действия один раз.", (66, 662), 485, 25, TEXT, spacing=7)
    draw.rounded_rectangle((624, 305, 1006, 714), radius=46, fill="#17234b")
    draw.rounded_rectangle((684, 358, 946, 662), radius=28, fill="#ffffff")
    draw.rounded_rectangle((720, 405, 910, 437), radius=13, fill="#ddd8f4")
    draw.rounded_rectangle((720, 466, 878, 498), radius=13, fill="#e9e6f8")
    draw.rounded_rectangle((720, 527, 850, 559), radius=13, fill="#e9e6f8")
    draw.ellipse((817, 312, 975, 470), fill="#a596ff")
    draw.arc((849, 346, 943, 440), 35, 315, fill="#102342", width=13)
    draw.polygon(((930, 352), (949, 355), (939, 374)), fill="#102342")
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
         "Нажмите «Расходы» — откроется список документов.", lambda _draw: draw_finance_entry(_draw._image), "02-step.png")
    step(2, "Откройте регулярные расходы", "Разверните «Справочники и быстрые действия».",
         "В карточке «Регулярные расходы» нажмите «Открыть».", recurring_entry, "03-step.png")
    step(3, "Создайте правило", "На странице «Регулярные расходы» нажмите primary-кнопку.",
         "Точный текст кнопки — «Добавить правило».", lambda d: rules_page(d, highlight_add=True), "04-step.png")
    step(4, "Заполните основные поля", "Укажите название, категорию, поставщика и способ оплаты.",
         "В примере: «Аренда склада», «Аренда», Local Partner и СБП.", form_main, "05-step.png")
    step(5, "Задайте расписание", "Выберите дату старта, день месяца и срок распределения.",
         "Без даты окончания правило действует бессрочно.", form_schedule, "06-step.png")
    step(6, "Укажите сумму", "Оставьте режим «Фиксированная сумма» и заполните описание.",
         "Активное правило будет доступно для генерации расхода.", lambda d: form_amount(d, focus_button=False), "07-step.png")
    step(7, "Сохраните правило", "Проверьте данные и нажмите обычную кнопку «Добавить».",
         "«Отмена» закроет форму без создания правила.", lambda d: form_amount(d, focus_button=True), "08-step.png")

    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Правило добавлено", "Axelio показывает его в списке регулярных расходов.")
    draw_ui_frame(img)
    result_page(ImageDraw.Draw(img), toast=True)
    draw_bottom_note(img, "В E2E: всего правил — 1, активных — 1.")
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
        "Справочники и быстрые действия", "Регулярные расходы", "Открыть", "Добавить правило",
        "Название", "Категория", "Поставщик", "Оплачивать через", "Дата старта", "Дата окончания",
        "День месяца", "Распределить на месяцев", "Фиксированная сумма", "Сумма, ₽",
        "Правило активно", "Комментарий / описание", "Добавить", "Отмена", "Правило добавлено",
        "Сгенерировать", "Изменить", "Удалить", "Активно", "Фиксированный режим",
    )
    missing = [label for label in required if label not in source]
    assert not missing, f"UI strings not found: {missing}"
    print(f"Verified {len(required)} current UI strings")


if __name__ == "__main__":
    build_all()
    verify_outputs()
    verify_ui_strings()

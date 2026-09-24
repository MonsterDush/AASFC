from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-13-cancel-payroll-payout" / "build_guide.py"
SPEC = spec_from_file_location("axelio_operating_expense_series", PREVIOUS_PATH)
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


def center_text(draw, box, label, size=13, bold=True, fill=PANEL_TEXT):
    x1, y1, x2, y2 = box
    f = font(size, bold)
    bbox = draw.textbbox((0, 0), label, font=f)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    draw.text(((x1 + x2 - width) / 2, (y1 + y2 - height) / 2 - 2), label, font=f, fill=fill)


def modal_shell(draw):
    draw.rounded_rectangle((146, 340, 934, 902), radius=22, fill="#111b38", outline="#46578b", width=2)
    draw.line((146, 416, 934, 416), fill=PANEL_LINE, width=2)
    panel_text(draw, (180, 365), "Добавить расход", 21, True)
    BASE.normal_button(draw, (770, 354, 900, 404), "Закрыть", size=11)


def field(draw, label, box, value, kind="input", highlighted=False, value_size=14):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 29), label, 13, True, PANEL_MUTED)
    draw.rounded_rectangle(
        box,
        radius=12,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    panel_text(draw, (x1 + 18, y1 + 16), value, value_size, True)
    if kind == "select":
        cx = x2 - 24
        cy = (y1 + y2) // 2
        draw.polygon(((cx - 7, cy - 4), (cx + 7, cy - 4), (cx, cy + 5)), fill=PANEL_MUTED)


def textarea(draw, label, box, value, highlighted=False):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 29), label, 13, True, PANEL_MUTED)
    draw.rounded_rectangle(
        box,
        radius=12,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlighted else PANEL_LINE,
        width=4 if highlighted else 2,
    )
    fit_text(draw, value, (x1 + 18, y1 + 15), x2 - x1 - 36, 14, PANEL_TEXT, spacing=4)


def draw_list_summary(draw, count="8"):
    draw.rounded_rectangle((96, 438, 984, 560), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 459), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, 493), "Месяц 2026-09 · все статусы · все виды · признано 235 326,35 ₽", 12, False)
    panel_text(draw, (805, 457), "Записей", 12, False, PANEL_MUTED)
    panel_text(draw, (805, 490), count, 30, True)


def draw_form_actions(draw, highlighted=False):
    button(draw, (266, 690, 476, 752), "Добавить", kind="primary", size=13)
    BASE.subtle_button(draw, (496, 690, 676, 752), "Отмена", size=13)
    if highlighted:
        draw.rounded_rectangle((258, 682, 484, 760), radius=18, outline=PURPLE, width=4)


def draft_expense_row(draw, top=515):
    box = (96, top, 984, top + 360)
    draw.rounded_rectangle(box, radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Хозтовары", 21, True)
    ui_badge(draw, (122, top + 58, 232, top + 92), "Черновик", fill="#3d3215", text_fill="#ffd97a")

    panel_text(draw, (122, top + 113), "2026-09-15   ·   Local Partner   ·   Наличные", 14, True)
    panel_text(draw, (122, top + 149), "Дневная смена", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 181), "Расходные материалы для уборки", 14, False)

    draw.rounded_rectangle((116, top + 218, 630, top + 285), radius=12, fill=PANEL_CARD_2, outline=PANEL_LINE, width=1)
    panel_text(draw, (136, top + 233), "ПРИЗНАНО В 2026-09", 10, True, PANEL_MUTED)
    panel_text(draw, (136, top + 257), "В выбранном месяце не признаётся", 12, False, PANEL_MUTED)
    panel_text(draw, (668, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (668, top + 52), "4 500,00 ₽", 22, True)

    BASE.normal_button(draw, (650, top + 105, 792, top + 153), "Подтвердить", size=10)
    BASE.subtle_button(draw, (808, top + 105, 960, top + 153), "Отменить", size=10)
    BASE.normal_button(draw, (650, top + 165, 792, top + 213), "Изменить", size=10)
    button(draw, (808, top + 165, 960, top + 213), "Удалить", kind="danger", size=10)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 170), "Как добавить\nоперационный\nрасход?", font=font(48, True), fill=NAVY, spacing=3)
    fit_text(
        draw,
        "Зафиксируйте оплату и отнесите её к нужной категории.",
        (66, 420),
        480,
        28,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Черновик можно проверить и подтвердить позже.",
        (66, 642),
        470,
        26,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "add-operating-expense-illustration.png").convert("RGB")
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
    draw_step_header(img, "2", "ШАГ 2", "Начните новый расход", "Нажмите основную кнопку в заголовке экрана.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    draw.rounded_rectangle((784, 342, 970, 410), radius=18, outline=PURPLE, width=4)
    draw_list_summary(draw)
    panel_text(draw, (122, 615), "Список расходов", 20, True)
    panel_text(draw, (122, 653), "Полная сумма документа и признание по месяцу показаны отдельно.", 13, False, PANEL_MUTED)
    draw_bottom_note(img, "Кнопка называется «Добавить расход».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Выберите категорию", "Поставщика можно указать ниже или оставить пустым.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    modal_shell(draw)
    field(draw, "Категория", (180, 472, 900, 534), "Хозтовары", kind="select", highlighted=True)
    fit_text(
        draw,
        "Нужной категории нет? Создай её прямо из формы и продолжай ввод расхода без потери данных.",
        (180, 550),
        690,
        11,
        PANEL_MUTED,
        spacing=3,
    )
    BASE.subtle_button(draw, (180, 606, 394, 654), "+ Добавить категорию", size=11)
    field(draw, "Поставщик", (180, 730, 900, 792), "Local Partner", kind="select")
    draw_bottom_note(img, "В примере: категория «Хозтовары», поставщик «Local Partner».")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Укажите способ оплаты", "Выберите, откуда будет оплачен расход.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    modal_shell(draw)
    field(draw, "Оплачено через", (180, 472, 900, 534), "Наличные", kind="select", highlighted=True)
    field(draw, "Сумма, ₽", (180, 630, 900, 692), "4500.00")
    field(draw, "Дата расхода", (180, 788, 900, 850), "2026-09-15")
    draw_bottom_note(img, "В примере выбран способ оплаты «Наличные».")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Введите сумму и дату", "Укажите полную сумму документа и дату расхода.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    modal_shell(draw)
    draw.rounded_rectangle((166, 446, 914, 712), radius=18, outline=PURPLE, width=4)
    field(draw, "Сумма, ₽", (180, 492, 900, 554), "4500.00")
    field(draw, "Дата расхода", (180, 638, 900, 700), "2026-09-15")
    draw_bottom_note(img, "Пример: сумма 4500.00, дата — 2026-09-15.")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Настройте распределение", "Выберите смену и количество месяцев.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    modal_shell(draw)
    draw.rounded_rectangle((166, 446, 914, 724), radius=18, outline=PURPLE, width=4)
    field(draw, "Отнести расход", (180, 492, 900, 554), "Только на дневную смену", kind="select")
    field(draw, "Распределить на месяцев", (180, 638, 900, 700), "1")
    fit_text(
        draw,
        "Общий расход распределяется по всем активным сменам месяца: 60–62 части при включённых дневной и ночной сменах.",
        (180, 770),
        690,
        13,
        PANEL_MUTED,
        spacing=4,
    )
    draw_bottom_note(img, "В примере расход относится только на дневную смену за один месяц.")
    save(img, "07-step.png")


def build_step_7():
    img = base_canvas()
    draw_step_header(img, "7", "ШАГ 7", "Выберите статус", "Черновик можно проверить перед подтверждением.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    modal_shell(draw)
    field(draw, "Статус", (180, 472, 900, 534), "Черновик", kind="select", highlighted=True)
    textarea(draw, "Комментарий", (180, 630, 900, 750), "Расходные материалы для уборки")
    draw_bottom_note(img, "Комментарий и файлы необязательны; статус в примере — «Черновик».")
    save(img, "08-step.png")


def build_step_8():
    img = base_canvas()
    draw_step_header(img, "8", "ШАГ 8", "Сохраните расход", "Нажмите основную кнопку внизу формы.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    modal_shell(draw)
    panel_text(draw, (180, 462), "Файлы к расходу", 13, True, PANEL_MUTED)
    draw.rounded_rectangle((180, 500, 900, 556), radius=12, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    fit_text(
        draw,
        "Поддерживаются PDF, изображения, документы, таблицы, CSV/TXT и архивы. До 20 МБ на файл.",
        (180, 590),
        690,
        12,
        PANEL_MUTED,
        spacing=4,
    )
    draw_form_actions(draw, highlighted=True)
    draw_bottom_note(img, "Кнопка называется «Добавить».")
    save(img, "09-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Расход добавлен", "Новая запись появилась в списке расходов.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    expenses_header(draw)
    draw.rounded_rectangle((650, 414, 960, 476), radius=15, fill="#173a33", outline="#2d826c", width=2)
    draw.ellipse((674, 434, 696, 456), fill=GREEN)
    panel_text(draw, (710, 433), "Расход добавлен", 13, True, GREEN)
    draft_expense_row(draw, top=500)
    draw_bottom_note(img, "Статус — «Черновик». Его можно подтвердить после проверки.")
    save(img, "10-result.png")


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
        "09-step.png",
        "10-result.png",
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
        )
    )
    required = (
        "Расходы",
        "Расходы и черновики за выбранный период",
        "Добавить расход",
        "Закрыть",
        "Категория",
        "Нужной категории нет? Создай её прямо из формы и продолжай ввод расхода без потери данных.",
        "+ Добавить категорию",
        "Поставщик",
        "+ Добавить поставщика",
        "Оплачено через",
        "Сумма, ₽",
        "Дата расхода",
        "Отнести расход",
        "На все смены поровну",
        "Только на дневную смену",
        "Общий расход распределяется по всем активным сменам месяца: 60–62 части при включённых дневной и ночной сменах.",
        "Распределить на месяцев",
        "Статус",
        "Черновик",
        "Подтверждён",
        "Отменён",
        "Комментарий",
        "Файлы к расходу",
        "Поддерживаются PDF, изображения, документы, таблицы, CSV/TXT и архивы. До 20 МБ на файл.",
        "Добавить",
        "Отмена",
        "Расход добавлен",
        "Признано в",
        "Полная сумма",
        "Подтвердить",
        "Отменить",
        "Изменить",
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
    build_step_6()
    build_step_7()
    build_step_8()
    build_result()
    verify_outputs()
    verify_ui_strings()

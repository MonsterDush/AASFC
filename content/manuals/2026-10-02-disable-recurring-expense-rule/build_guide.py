from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-10-01-generate-recurring-expenses" / "build_guide.py"
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


def draw_page_shell(draw, *, active_count=1):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 397), "Регулярные расходы", 22, True)
    panel_text(draw, (122, 432), "Axelio E2E Lounge", 12, False, PANEL_MUTED)
    panel_text(draw, (654, 402), "Всего правил", 9, True, PANEL_MUTED)
    panel_text(draw, (654, 430), "1", 18, True)
    panel_text(draw, (782, 402), "Активных", 9, True, PANEL_MUTED)
    panel_text(draw, (782, 430), str(active_count), 18, True)
    button(draw, (836, 394, 960, 442), "Добавить правило", kind="primary", size=7)


def draw_rule_row(draw, *, active=True, focus_edit=False, focus_state=False):
    draw.rounded_rectangle((122, 500, 958, 818), radius=16, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (146, 524), "Аренда склада", 18, True)
    ui_badge(draw, (146, 560, 228, 592), "Фикс", size=9)
    if active:
        ui_badge(draw, (240, 560, 340, 592), "Активно", fill="#173a33", text_fill="#76e2ba", size=9)
    else:
        ui_badge(draw, (240, 560, 358, 592), "Выключено", fill="#252a38", text_fill="#aeb7cc", size=9)
    panel_text(draw, (146, 622), "Аренда · Local Partner", 12, False, PANEL_MUTED)
    panel_text(draw, (146, 656), "Сумма: 135 000,00 ₽", 13, True)
    panel_text(draw, (146, 690), "Период действия: 2026-10-01 → ∞", 11, False)
    panel_text(draw, (146, 724), "День месяца: 5 · Размазать на: 1 мес.", 11, False)
    panel_text(draw, (146, 758), "База/списание: Списывать через СБП", 11, False)
    panel_text(draw, (696, 622), "135 000,00 ₽", 18, True)
    panel_text(draw, (696, 657), "Фиксированный режим", 10, False, PANEL_MUTED)
    BASE.normal_button(draw, (748, 716, 850, 760), "Изменить", size=7)
    button(draw, (860, 716, 936, 760), "Удалить", kind="danger", size=7)
    if focus_edit:
        draw.rounded_rectangle((736, 704, 862, 772), radius=14, outline=PURPLE, width=4)
    if focus_state:
        draw.rounded_rectangle((232, 552, 368, 600), radius=12, outline=PURPLE, width=4)


def rules_screen(draw, *, active=True, focus_edit=False, focus_state=False):
    draw_page_shell(draw, active_count=1 if active else 0)
    draw_rule_row(draw, active=active, focus_edit=focus_edit, focus_state=focus_state)


def checkbox(draw, box, *, checked):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=5, fill="#6f56d9" if checked else PANEL_CARD_2,
                           outline="#8d78ea" if checked else "#566078", width=2)
    if checked:
        draw.line((x1 + 7, y1 + 15, x1 + 13, y1 + 21), fill="white", width=3)
        draw.line((x1 + 13, y1 + 21, x2 - 6, y1 + 7), fill="white", width=3)


def edit_modal(draw, *, checked=True, focus_checkbox=False, focus_save=False):
    draw.rounded_rectangle((96, 370, 984, 888), radius=22, fill="#080d1d", outline=PANEL_LINE, width=2)
    draw.rounded_rectangle((178, 390, 902, 866), radius=20, fill="#11182b", outline=PANEL_LINE, width=2)
    panel_text(draw, (210, 414), "Редактировать правило", 20, True)
    panel_text(draw, (210, 464), "Название", 9, True, PANEL_MUTED)
    draw.rounded_rectangle((210, 489, 548, 533), radius=10, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (226, 503), "Аренда склада", 11, False)
    panel_text(draw, (572, 464), "Категория", 9, True, PANEL_MUTED)
    draw.rounded_rectangle((572, 489, 870, 533), radius=10, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (588, 503), "Аренда", 11, False)
    panel_text(draw, (210, 558), "Сумма, ₽", 9, True, PANEL_MUTED)
    draw.rounded_rectangle((210, 583, 548, 627), radius=10, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (226, 597), "135000.00", 11, False)
    panel_text(draw, (572, 558), "День месяца", 9, True, PANEL_MUTED)
    draw.rounded_rectangle((572, 583, 870, 627), radius=10, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (588, 597), "5", 11, False)
    checkbox(draw, (216, 666, 244, 694), checked=checked)
    panel_text(draw, (260, 670), "Правило активно", 12, True)
    panel_text(draw, (210, 728), "Комментарий / описание", 9, True, PANEL_MUTED)
    draw.rounded_rectangle((210, 753, 870, 797), radius=10, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (226, 767), "Аренда склада и подсобного помещения", 10, False)
    BASE.normal_button(draw, (602, 812, 726, 850), "Сохранить", size=8)
    button(draw, (738, 812, 846, 850), "Отмена", kind="ghost", size=8)
    if focus_checkbox:
        draw.rounded_rectangle((202, 650, 470, 708), radius=13, outline=PURPLE, width=4)
    if focus_save:
        draw.rounded_rectangle((590, 800, 738, 862), radius=14, outline=PURPLE, width=4)


def result_screen(draw):
    draw_page_shell(draw, active_count=0)
    draw_rule_row(draw, active=False, focus_state=True)
    draw.rounded_rectangle((652, 474, 942, 520), radius=13, fill="#173a33", outline="#2d826c", width=2)
    panel_text(draw, (677, 488), "Правило обновлено", 11, True, GREEN)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 177), "Как\nотключить\nправило\nрасхода?", font=font(49, True), fill=NAVY, spacing=2)
    fit_text(draw, "Остановите будущие начисления, не удаляя само правило.", (66, 493), 485, 27, TEXT, spacing=7)
    fit_text(draw, "Его можно будет отредактировать и снова включить позже.", (66, 666), 485, 25, TEXT, spacing=7)
    draw.rounded_rectangle((624, 305, 1006, 714), radius=46, fill="#17234b")
    draw.rounded_rectangle((684, 358, 946, 662), radius=28, fill="#ffffff")
    draw.rounded_rectangle((720, 408, 910, 440), radius=13, fill="#ddd8f4")
    draw.rounded_rectangle((720, 470, 868, 502), radius=13, fill="#e9e6f8")
    draw.rounded_rectangle((720, 532, 840, 564), radius=13, fill="#e9e6f8")
    draw.ellipse((817, 312, 975, 470), fill="#d8dbe5")
    draw.text((856, 344), "0", font=font(58, True), fill="#102342")
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
    step(3, "Выберите правило", "Найдите правило, которое больше не должно создавать расходы.",
         "В строке «Аренда склада» нажмите «Изменить».", lambda d: rules_screen(d, focus_edit=True), "04-step.png")
    step(4, "Найдите переключатель", "Откроется форма «Редактировать правило».",
         "У активного правила включён пункт «Правило активно».", lambda d: edit_modal(d, checked=True, focus_checkbox=True), "05-step.png")
    step(5, "Снимите отметку", "Выключите пункт «Правило активно».",
         "Остальные поля правила можно оставить без изменений.", lambda d: edit_modal(d, checked=False, focus_checkbox=True), "06-step.png")
    step(6, "Сохраните изменения", "Нажмите обычную кнопку «Сохранить».",
         "Кнопка остаётся вторичной, как в интерфейсе Axelio.", lambda d: edit_modal(d, checked=False, focus_save=True), "07-step.png")

    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Правило выключено", "Axelio сохранил изменения и обновил список правил.")
    draw_ui_frame(img)
    result_screen(ImageDraw.Draw(img))
    draw_bottom_note(img, "Статус — «Выключено», активных правил — 0.")
    save(img, "08-result.png")


def verify_outputs():
    files = ["01-cover.png"] + [f"{index:02d}-step.png" for index in range(2, 8)] + ["08-result.png"]
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
        "Справочники и быстрые действия", "Регулярные расходы", "Открыть", "Изменить",
        "Редактировать правило", "Правило активно", "Сохранить", "Отмена", "Удалить",
        "Всего правил", "Активных", "Правило обновлено", "Активно", "Выключено",
    )
    missing = [label for label in required if label not in source]
    assert not missing, f"UI strings not found: {missing}"
    print(f"Verified {len(required)} current UI strings")


if __name__ == "__main__":
    build_all()
    verify_outputs()
    verify_ui_strings()

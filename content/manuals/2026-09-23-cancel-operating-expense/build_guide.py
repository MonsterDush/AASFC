from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
PREVIOUS_PATH = ROOT.parent / "2026-09-15-add-operating-expense" / "build_guide.py"
SPEC = spec_from_file_location("axelio_confirm_expense_series", PREVIOUS_PATH)
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


def select_field(draw, box, label, value, highlighted=False):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 28), label, 12, True, PANEL_MUTED)
    draw.rounded_rectangle(box, radius=12, fill=PANEL_CARD_2,
                           outline=PURPLE if highlighted else PANEL_LINE,
                           width=4 if highlighted else 2)
    panel_text(draw, (x1 + 16, y1 + 16), value, 13, True)
    cx, cy = x2 - 25, (y1 + y2) // 2
    draw.polygon(((cx - 7, cy - 4), (cx + 7, cy - 4), (cx, cy + 5)), fill=PANEL_MUTED)


def list_header(draw, count, recognized, status="все статусы", kind="все виды"):
    expenses_header(draw)
    draw.rounded_rectangle((96, 438, 984, 558), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 458), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, 492), f"Месяц 2026-09 · {status} · {kind} · признано {recognized}", 12, False)
    panel_text(draw, (806, 458), "Записей", 12, False, PANEL_MUTED)
    panel_text(draw, (806, 489), str(count), 29, True)


def draft_row(draw, top=584, highlight=None):
    draw.rounded_rectangle((96, top, 984, top + 302), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Хозтовары", 21, True)
    ui_badge(draw, (122, top + 58, 232, top + 92), "Черновик", fill="#3d3215", text_fill="#ffd97a")
    ui_badge(draw, (246, top + 58, 454, top + 92), "Сгенерирован 2026-09-01", size=10)
    panel_text(draw, (122, top + 114), "2026-09-25   ·   Local Partner   ·   Эквайринг", 14, True)
    panel_text(draw, (122, top + 148), "Все смены", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 181), "Текстиль, аромасвечи и расходники для VIP-комнат", 13, False)
    panel_text(draw, (122, top + 222), "ПРИЗНАНО В 2026-09", 10, True, PANEL_MUTED)
    panel_text(draw, (122, top + 247), "В выбранном месяце не признаётся", 12, False, PANEL_MUTED)
    panel_text(draw, (668, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (668, top + 52), "6 847,60 ₽", 22, True)
    BASE.normal_button(draw, (650, top + 105, 792, top + 153), "Подтвердить", size=10)
    BASE.subtle_button(draw, (808, top + 105, 960, top + 153), "Отменить", size=10)
    BASE.normal_button(draw, (650, top + 165, 792, top + 213), "Изменить", size=10)
    button(draw, (808, top + 165, 960, top + 213), "Удалить", kind="danger", size=10)
    targets = {"details": (110, top + 105, 630, top + 273), "confirm": (642, top + 97, 800, top + 161)}
    if highlight:
        draw.rounded_rectangle(targets[highlight], radius=17, outline=PURPLE, width=4)


def confirmed_row(draw, top=584, highlight=None):
    draw.rounded_rectangle((96, top, 984, top + 302), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Хозтовары", 21, True)
    ui_badge(draw, (122, top + 58, 252, top + 92), "Подтверждён", fill="#173a33", text_fill="#76e2ba")
    ui_badge(draw, (266, top + 58, 474, top + 92), "Сгенерирован 2026-09-01", size=10)
    panel_text(draw, (122, top + 114), "2026-09-25   ·   Local Partner   ·   Эквайринг", 14, True)
    panel_text(draw, (122, top + 148), "Все смены", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 181), "Текстиль, аромасвечи и расходники для VIP-комнат", 13, False)
    panel_text(draw, (122, top + 221), "ПРИЗНАНО В 2026-09", 10, True, PANEL_MUTED)
    panel_text(draw, (122, top + 246), "2026-09-01 · 6 847,60 ₽", 12, False)
    panel_text(draw, (668, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (668, top + 52), "6 847,60 ₽", 22, True)
    BASE.subtle_button(draw, (624, top + 105, 778, top + 153), "В черновик", size=10)
    BASE.subtle_button(draw, (798, top + 105, 960, top + 153), "Отменить", size=10)
    BASE.normal_button(draw, (650, top + 165, 792, top + 213), "Изменить", size=10)
    button(draw, (808, top + 165, 960, top + 213), "Удалить", kind="danger", size=10)
    targets = {"details": (110, top + 105, 630, top + 273), "draft": (616, top + 97, 786, top + 161), "cancel": (790, top + 97, 968, top + 161)}
    if highlight:
        draw.rounded_rectangle(targets[highlight], radius=17, outline=PURPLE, width=4)


def cancelled_row(draw, top=584):
    draw.rounded_rectangle((96, top, 984, top + 302), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, top + 20), "Хозтовары", 21, True)
    ui_badge(draw, (122, top + 58, 232, top + 92), "Отменён", fill="#462031", text_fill="#ff9aac")
    ui_badge(draw, (246, top + 58, 454, top + 92), "Сгенерирован 2026-09-01", size=10)
    panel_text(draw, (122, top + 114), "2026-09-25   ·   Local Partner   ·   Эквайринг", 14, True)
    panel_text(draw, (122, top + 148), "Все смены", 13, False, PANEL_MUTED)
    panel_text(draw, (122, top + 181), "Текстиль, аромасвечи и расходники для VIP-комнат", 13, False)
    panel_text(draw, (122, top + 222), "ПРИЗНАНО В 2026-09", 10, True, PANEL_MUTED)
    panel_text(draw, (122, top + 247), "В выбранном месяце не признаётся", 12, False, PANEL_MUTED)
    panel_text(draw, (668, top + 22), "ПОЛНАЯ СУММА", 11, True, PANEL_MUTED)
    panel_text(draw, (668, top + 52), "6 847,60 ₽", 22, True)
    BASE.normal_button(draw, (624, top + 105, 778, top + 153), "Подтвердить", size=10)
    BASE.subtle_button(draw, (798, top + 105, 960, top + 153), "В черновик", size=10)
    BASE.normal_button(draw, (650, top + 165, 792, top + 213), "Изменить", size=10)
    button(draw, (808, top + 165, 960, top + 213), "Удалить", kind="danger", size=10)
    draw.rounded_rectangle((112, top + 49, 248, top + 99), radius=15, outline=PURPLE, width=4)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 175), "Как отменить\nоперационный\nрасход?", font=font(48, True), fill=NAVY, spacing=3)
    fit_text(draw, "Уберите ошибочный документ из признания за месяц.", (66, 423), 480, 27, TEXT, spacing=7)
    fit_text(draw, "Расход останется в истории со статусом «Отменён».", (66, 640), 470, 26, TEXT, spacing=7)
    # Code-native neutral confirmation illustration; no text, UI, arrows, devices, or logos.
    draw.rounded_rectangle((624, 305, 1006, 714), radius=46, fill="#17234b")
    draw.rounded_rectangle((694, 381, 928, 644), radius=26, fill="#ffffff")
    draw.rounded_rectangle((729, 433, 894, 458), radius=12, fill="#ddd8f4")
    draw.rounded_rectangle((729, 486, 854, 508), radius=10, fill="#e9e6f8")
    draw.rounded_rectangle((729, 530, 820, 552), radius=10, fill="#e9e6f8")
    draw.ellipse((824, 324, 962, 462), fill="#f5bd74")
    draw.line((858, 358, 932, 432), fill="#102342", width=15)
    draw.line((932, 358, 858, 432), fill="#102342", width=15)
    draw.ellipse((620, 590, 728, 698), fill="#ffcc74")
    draw.ellipse((649, 619, 699, 669), outline="#8a6420", width=6)
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
    img = base_canvas(); draw_step_header(img, "2", "ШАГ 2", "Покажите подтверждённые", "В фильтрах выберите статус и вид расхода."); draw_ui_frame(img)
    draw = ImageDraw.Draw(img); expenses_header(draw)
    select_field(draw, (96, 450, 510, 512), "Статус", "Только подтверждённые", True)
    select_field(draw, (570, 450, 984, 512), "Вид расхода", "Операционные расходы", True)
    draw.rounded_rectangle((96, 548, 984, 668), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 568), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, 602), "Месяц 2026-09 · только подтверждённые · операционные расходы", 12, False)
    panel_text(draw, (806, 568), "Записей", 12, False, PANEL_MUTED); panel_text(draw, (806, 599), "9", 29, True)
    draw_bottom_note(img, "Так проще найти документ перед возвратом в черновик."); save(img, "03-step.png")


def build_step_3():
    img = base_canvas(); draw_step_header(img, "3", "ШАГ 3", "Проверьте расход", "Сверьте сумму, способ оплаты и признание за месяц."); draw_ui_frame(img)
    draw = ImageDraw.Draw(img); list_header(draw, "9", "235 386,36 ₽", "только подтверждённые", "операционные расходы"); confirmed_row(draw, highlight="details")
    draw_bottom_note(img, "Подтверждённый расход уже участвует в признании за месяц."); save(img, "04-step.png")


def build_step_4():
    img = base_canvas(); draw_step_header(img, "4", "ШАГ 4", "Отмените расход", "Нажмите ghost-кнопку в строке расхода."); draw_ui_frame(img)
    draw = ImageDraw.Draw(img); list_header(draw, "9", "235 386,36 ₽", "только подтверждённые", "операционные расходы"); confirmed_row(draw, highlight="cancel")
    draw_bottom_note(img, "«Отменить» — тёмная контурная ghost-кнопка."); save(img, "05-step.png")


def build_step_5():
    img = base_canvas(); draw_step_header(img, "5", "ШАГ 5", "Убедитесь в обновлении", "Расход исчезнет из фильтра «Только подтверждённые»."); draw_ui_frame(img)
    draw = ImageDraw.Draw(img); list_header(draw, "8", "228 538,76 ₽", "только подтверждённые", "операционные расходы")
    draw.rounded_rectangle((96, 592, 984, 788), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    draw.rounded_rectangle((637, 616, 960, 676), radius=15, fill="#173a33", outline="#2d826c", width=2)
    draw.ellipse((660, 635, 682, 657), fill=GREEN); panel_text(draw, (697, 634), "Статус расхода обновлён", 12, True, GREEN)
    panel_text(draw, (122, 708), "Документ больше не отображается в этом фильтре.", 15, False, PANEL_MUTED)
    draw_bottom_note(img, "Уведомление подтверждает смену статуса."); save(img, "06-step.png")


def build_step_6():
    img = base_canvas(); draw_step_header(img, "6", "ШАГ 6", "Покажите отменённые", "Смените фильтр статуса, чтобы увидеть результат."); draw_ui_frame(img)
    draw = ImageDraw.Draw(img); expenses_header(draw)
    select_field(draw, (96, 450, 510, 512), "Статус", "Только отменённые", True)
    select_field(draw, (570, 450, 984, 512), "Вид расхода", "Операционные расходы")
    draw.rounded_rectangle((96, 548, 984, 668), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (122, 568), "СОСТОЯНИЕ СПИСКА", 11, True, PANEL_MUTED)
    panel_text(draw, (122, 602), "Месяц 2026-09 · только отменённые · операционные расходы", 12, False)
    panel_text(draw, (806, 568), "Записей", 12, False, PANEL_MUTED); panel_text(draw, (806, 599), "1", 29, True)
    draw_bottom_note(img, "Теперь расход отображается среди отменённых."); save(img, "07-step.png")


def build_result():
    img = base_canvas(); draw_step_header(img, "✓", "ГОТОВО", "Расход отменён", "Сумма больше не признана в выбранном месяце."); draw_ui_frame(img)
    draw = ImageDraw.Draw(img); list_header(draw, "1", "228 538,76 ₽", "только отменённые", "операционные расходы"); cancelled_row(draw)
    draw_bottom_note(img, "Доступны «Подтвердить», «В черновик», «Изменить» и «Удалить»."); save(img, "08-result.png")


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
    source = "\n".join((repo / path).read_text(encoding="utf-8") for path in ("frontend/app-venue.html", "frontend/owner-expenses.html", "frontend/owner-expenses.js"))
    required = ("Расходы", "Финансы", "Только черновики", "Только подтверждённые", "Операционные расходы", "Черновик", "Подтверждён", "Подтвердить", "В черновик", "Отменить", "Изменить", "Удалить", "Статус расхода обновлён", "Признано в", "Полная сумма")
    missing = [label for label in required if label not in source]
    assert not missing, f"UI strings not found: {missing}"
    print(f"Verified {len(required)} current UI strings")


if __name__ == "__main__":
    build_cover(); build_step_1(); build_step_2(); build_step_3(); build_step_4(); build_step_5(); build_step_6(); build_result()
    verify_outputs(); verify_ui_strings()

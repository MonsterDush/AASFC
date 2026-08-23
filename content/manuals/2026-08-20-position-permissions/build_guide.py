from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
STYLE_PATH = ROOT.parent / "2026-08-13-invite-employee" / "build_guide.py"
SPEC = spec_from_file_location("axelio_manual_style", STYLE_PATH)
STYLE = module_from_spec(SPEC)
SPEC.loader.exec_module(STYLE)

NAVY = STYLE.NAVY
TEXT = STYLE.TEXT
MUTED = STYLE.MUTED
PURPLE = STYLE.PURPLE
PURPLE_LIGHT = STYLE.PURPLE_LIGHT
PANEL = STYLE.PANEL
PANEL_CARD = STYLE.PANEL_CARD
PANEL_CARD_2 = STYLE.PANEL_CARD_2
PANEL_LINE = STYLE.PANEL_LINE
PANEL_TEXT = STYLE.PANEL_TEXT
PANEL_MUTED = STYLE.PANEL_MUTED
BLUE = STYLE.BLUE
GREEN = STYLE.GREEN

font = STYLE.font
base_canvas = STYLE.base_canvas
rounded_shadow = STYLE.rounded_shadow
fit_text = STYLE.fit_text
draw_brand = STYLE.draw_brand
draw_step_header = STYLE.draw_step_header
draw_bottom_note = STYLE.draw_bottom_note
draw_ui_frame = STYLE.draw_ui_frame
panel_text = STYLE.panel_text

# Единая геометрия серии. Все пошаговые карточки используют только эти helpers.
STEP_GRID = {
    "number_circle": (64, 50, 124, 110),
    "step_label": (145, 64),
    "title_start": (64, 137),
    "explanation_start": (64, 230),
    "ui_frame": (60, 315, 1020, 930),
    "bottom_note_y": 950,
}


def button(draw, box, label, kind="normal", highlight=False, size=17):
    x1, y1, x2, y2 = box
    if highlight:
        draw.rounded_rectangle((x1 - 7, y1 - 7, x2 + 7, y2 + 7), radius=17, outline=PURPLE, width=5)
    if kind == "primary":
        fill, outline, text_fill = BLUE, BLUE, "#071227"
    elif kind == "danger":
        fill, outline, text_fill = "#43212c", "#8a4055", "#ffd5df"
    else:
        fill, outline, text_fill = PANEL_CARD_2, PANEL_LINE, PANEL_TEXT
    draw.rounded_rectangle(box, radius=13, fill=fill, outline=outline, width=2)
    f = font(size, True)
    bbox = draw.textbbox((0, 0), label, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 2), label, font=f, fill=text_fill)


def field(draw, box, label, value, highlight=False, dropdown=False, value_size=18):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 28), label, 15, True, PANEL_MUTED)
    draw.rounded_rectangle(
        box,
        radius=14,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlight else PANEL_LINE,
        width=4 if highlight else 2,
    )
    panel_text(draw, (x1 + 15, y1 + 14), value, value_size, False, PANEL_TEXT)
    if dropdown:
        cx, cy = x2 - 21, y1 + 29
        draw.polygon(((cx - 7, cy - 4), (cx + 7, cy - 4), (cx, cy + 5)), fill=PANEL_MUTED)


def chip(draw, box, label, size=13):
    draw.rounded_rectangle(box, radius=18, fill="#202b50", outline=PANEL_LINE, width=1)
    x1, y1, x2, y2 = box
    f = font(size, True)
    bbox = draw.textbbox((0, 0), label, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 1), label, font=f, fill=PANEL_TEXT)


def toggle(draw, box, checked=False, highlight=False):
    x1, y1, x2, y2 = box
    if highlight:
        draw.rounded_rectangle((x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius=21, outline=PURPLE, width=4)
    fill = BLUE if checked else "#222d50"
    outline = BLUE if checked else PANEL_LINE
    draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=fill, outline=outline, width=2)
    r = (y2 - y1) - 12
    knob_x = x2 - r - 6 if checked else x1 + 6
    draw.ellipse((knob_x, y1 + 6, knob_x + r, y1 + 6 + r), fill="#f5f7ff")


def toast(draw, label):
    draw.rounded_rectangle((112, 370, 968, 435), radius=16, fill="#193d38", outline=GREEN, width=3)
    panel_text(draw, (142, 390), label, 24, True, "#d9ffeb")


def save(img, name):
    img.convert("RGB").save(ROOT / name, quality=95)


def modal_shell(img, top=360, bottom=866, title="Изменить должность"):
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((104, top, 976, bottom), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (132, top + 25), title, 27, True)
    panel_text(d, (132, top + 63), "Меняй должность/условия для выбранного сотрудника.", 16, False, PANEL_MUTED)
    button(d, (825, top + 20, 944, top + 76), "Закрыть", size=15)
    return d


def draw_edit_fields(img, highlight_template=False, highlight_apply=False):
    d = modal_shell(img)
    field(d, (132, 500, 544, 560), "Название должности", "Старший менеджер")
    field(d, (568, 500, 944, 560), "Сотрудник", "София · @axelio_demo_sofia · STAFF", dropdown=True, value_size=15)
    field(d, (132, 630, 630, 692), "Шаблон прав", "Базовый сотрудник · system", highlight=highlight_template, dropdown=True, value_size=17)
    button(d, (132, 727, 345, 787), "Применить шаблон", highlight=highlight_apply, size=15)
    d.rounded_rectangle((372, 716, 944, 823), radius=14, fill=PANEL, outline=PANEL_LINE, width=2)
    panel_text(d, (394, 734), "Видит свой график, начисления и собственные", 15, False, PANEL_MUTED)
    panel_text(d, (394, 760), "корректировки без управленческих прав.", 15, False, PANEL_MUTED)
    chip(d, (394, 790, 506, 818), "Зарплаты · 1", size=10)
    chip(d, (515, 790, 608, 818), "Смены · 1", size=10)
    chip(d, (617, 790, 760, 818), "Штрафы и споры · 1", size=9)
    return d


def build_cover():
    img = base_canvas()
    d = ImageDraw.Draw(img)
    draw_brand(img)
    d.multiline_text((62, 178), "Как настроить\nправа должности?", font=font(58, True), fill=NAVY, spacing=5)
    fit_text(
        d,
        "Права определяют, какие разделы и действия доступны сотруднику с этой должностью.",
        (66, 404),
        470,
        29,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        d,
        "Можно применить готовый шаблон или настроить разрешения вручную.",
        (66, 616),
        470,
        29,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "permissions-illustration.png").convert("RGB")
    art = art.crop((70, 90, 1180, 1200)).resize((450, 450), Image.Resampling.LANCZOS)
    mask = Image.new("L", art.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, 450, 450), radius=44, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    img.paste(art, (615, 305), mask)

    rounded_shadow(img, (62, 842, 1018, 1015), radius=28, fill="#ffffff", outline="#d4cdf6", width=2, blur=14)
    d = ImageDraw.Draw(img)
    d.ellipse((106, 881, 194, 969), fill=PURPLE)
    d.text((140, 901), "1", font=font(43, True), fill="white")
    d.text((235, 877), "Откройте нужное заведение", font=font(35, True), fill=NAVY)
    d.text((235, 930), "В блоке «Разделы» нажмите «Должности».", font=font(25), fill=MUTED)
    save(img, "01-cover.png")


def build_step_1():
    img = base_canvas()
    draw_step_header(img, "1", "ШАГ 1", "Откройте «Должности»", "На странице заведения найдите блок «Разделы».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    panel_text(d, (118, 380), "Axelio E2E Lounge", 21, True)
    panel_text(d, (118, 420), "Здесь собраны основные разделы, настройки и команда заведения.", 17, False, PANEL_MUTED)
    panel_text(d, (118, 485), "Разделы", 31, True)
    panel_text(d, (118, 529), "Быстрый переход к основным разделам.", 20, False, PANEL_MUTED)
    labels = ["Должности", "Приглашения", "График", "Отчёты"]
    xs = [118, 332, 546, 760]
    for x, label in zip(xs, labels):
        highlighted = label == "Должности"
        box = (x, 590, x + 186, 665)
        d.rounded_rectangle(
            box,
            radius=16,
            fill=PANEL_CARD,
            outline=PURPLE if highlighted else PANEL_LINE,
            width=5 if highlighted else 2,
        )
        f = font(18, True)
        tw = d.textbbox((0, 0), label, font=f)[2]
        d.text((x + 93 - tw / 2, 615), label, font=f, fill=PANEL_TEXT)
    draw_bottom_note(img, "Нажмите «Должности» — откроется список ролей команды.")
    save(img, "02-step.png")


def build_step_2():
    img = base_canvas()
    draw_step_header(img, "2", "ШАГ 2", "Откройте нужную должность", "В списке найдите сотрудника и нажмите «Изменить».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    panel_text(d, (112, 374), "Должности", 26, True)
    panel_text(d, (112, 412), "должности, профили зарплаты и права", 17, False, PANEL_MUTED)
    d.rounded_rectangle((112, 460, 968, 855), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (140, 490), "Список должностей", 27, True)
    d.rounded_rectangle((140, 550, 940, 812), radius=18, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (166, 578), "Старший менеджер", 24, True)
    chip(d, (408, 568, 528, 607), "1 сотрудник", size=13)
    button(d, (711, 563, 912, 618), "+ Добавить сотрудника", size=14)
    d.rounded_rectangle((166, 646, 914, 776), radius=15, fill="#151f3e", outline=PANEL_LINE, width=2)
    panel_text(d, (188, 668), "София · @axelio_demo_sofia · STAFF", 18, True)
    chip(d, (188, 708, 376, 744), "Профиль: Администратор", size=12)
    chip(d, (388, 708, 490, 744), "Отчёты: да", size=12)
    chip(d, (500, 708, 596, 744), "График: нет", size=12)
    button(d, (688, 676, 800, 742), "Изменить", highlight=True, size=14)
    button(d, (812, 676, 914, 742), "Архивировать", kind="danger", size=12)
    draw_bottom_note(img, "Откроется форма «Изменить должность».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Выберите шаблон прав", "Готовый шаблон включает подходящий набор разрешений.")
    draw_edit_fields(img, highlight_template=True)
    draw_bottom_note(img, "Для примера выбран «Базовый сотрудник · system».")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Примените шаблон", "Нажмите «Применить шаблон» — переключатели обновятся.")
    draw_edit_fields(img, highlight_apply=True)
    draw_bottom_note(img, "Axelio обновит переключатели прав в форме ниже.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Проверьте набор прав", "Axelio покажет описание шаблона и число разрешений.")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    toast(d, "Шаблон применён")
    d.rounded_rectangle((112, 475, 968, 848), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    field(d, (140, 540, 638, 602), "Шаблон прав", "Базовый сотрудник · system", dropdown=True, value_size=17)
    button(d, (140, 632, 353, 692), "Применить шаблон", size=15)
    d.rounded_rectangle((140, 708, 940, 832), radius=14, fill=PANEL, outline=PURPLE, width=4)
    panel_text(d, (162, 726), "Видит свой график, начисления и собственные корректировки", 16, False, PANEL_MUTED)
    panel_text(d, (162, 753), "без управленческих прав.", 16, False, PANEL_MUTED)
    chip(d, (162, 790, 281, 823), "Зарплаты · 1", size=12)
    chip(d, (292, 790, 391, 823), "Смены · 1", size=12)
    chip(d, (402, 790, 562, 823), "Штрафы и споры · 1", size=11)
    draw_bottom_note(img, "После применения права можно изменить вручную.")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Настройте отдельные права", "При необходимости включите или отключите разрешения вручную.")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((105, 370, 975, 862), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (136, 402), "Смены", 28, True)
    panel_text(d, (136, 443), "Просмотр графика и управление сменами", 17, False, PANEL_MUTED)
    button(d, (772, 394, 852, 449), "Все", size=14)
    button(d, (864, 394, 944, 449), "Ничего", size=14)
    d.rounded_rectangle((136, 500, 944, 633), radius=16, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(d, (160, 523), "Просмотр смен", 21, True)
    panel_text(d, (160, 560), "Видеть список смен и расписание", 16, False, PANEL_MUTED)
    toggle(d, (840, 538, 914, 579), checked=True)
    d.rounded_rectangle((136, 660, 944, 793), radius=16, fill=PANEL_CARD_2, outline=PURPLE, width=4)
    panel_text(d, (160, 683), "Управление сменами", 21, True)
    panel_text(d, (160, 720), "Создавать/редактировать смены и промежутки", 16, False, PANEL_MUTED)
    toggle(d, (840, 698, 914, 739), checked=False, highlight=True)
    draw_bottom_note(img, "«Все» и «Ничего» меняют только права внутри выбранной группы.")
    save(img, "07-step.png")


def build_step_7():
    img = base_canvas()
    draw_step_header(img, "7", "ШАГ 7", "Сохраните изменения", "Нажмите «Сохранить» внизу формы.")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((104, 360, 976, 866), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (132, 388), "Изменить должность", 27, True)
    d.rounded_rectangle((132, 456, 944, 706), radius=15, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(d, (158, 480), "Смены", 24, True)
    panel_text(d, (158, 518), "Просмотр графика и управление сменами", 16, False, PANEL_MUTED)
    d.rounded_rectangle((158, 560, 918, 624), radius=13, fill=PANEL, outline=PANEL_LINE, width=2)
    panel_text(d, (180, 578), "Просмотр смен", 18, True)
    toggle(d, (826, 571, 894, 612), checked=True)
    d.rounded_rectangle((158, 638, 918, 690), radius=13, fill=PANEL, outline=PANEL_LINE, width=2)
    panel_text(d, (180, 653), "Управление сменами", 18, True)
    toggle(d, (826, 644, 894, 682), checked=False)
    button(d, (132, 776, 296, 840), "Сохранить", kind="primary", highlight=True, size=18)
    button(d, (312, 776, 449, 840), "Отмена", size=18)
    button(d, (764, 776, 944, 840), "Архивировать", kind="danger", size=15)
    draw_bottom_note(img, "Синяя кнопка «Сохранить» завершает настройку прав.")
    save(img, "08-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Изменения сохранены", "Новый набор прав сохранён для выбранного сотрудника.")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    toast(d, "Изменения сохранены")
    panel_text(d, (112, 476), "Список должностей", 28, True)
    d.rounded_rectangle((112, 526, 968, 762), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (142, 554), "Старший менеджер", 25, True)
    chip(d, (408, 545, 528, 584), "1 сотрудник", size=13)
    button(d, (720, 542, 938, 600), "+ Добавить сотрудника", size=14)
    d.rounded_rectangle((142, 620, 938, 730), radius=15, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(d, (164, 642), "София · @axelio_demo_sofia · STAFF", 18, True)
    chip(d, (164, 682, 352, 716), "Профиль: Администратор", size=12)
    chip(d, (360, 682, 462, 716), "Отчёты: да", size=12)
    chip(d, (470, 682, 566, 716), "График: нет", size=12)
    button(d, (690, 643, 805, 706), "Изменить", size=14)
    button(d, (816, 643, 930, 706), "Архивировать", kind="danger", size=12)
    d.rounded_rectangle((112, 797, 968, 860), radius=15, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(d, (142, 817), "Следующая инструкция: Как настроить профиль зарплаты?", 21, True, PURPLE_LIGHT)
    draw_bottom_note(img, "Сотрудник получит доступ только к отмеченным разделам и действиям.")
    save(img, "09-result.png")


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
        "09-result.png",
    ]
    for filename in files:
        with Image.open(ROOT / filename) as image:
            assert image.size == (1080, 1080), f"{filename}: {image.size}"
    assert STEP_GRID["ui_frame"] == (60, 315, 1020, 930)
    assert STEP_GRID["title_start"] == (64, 137)
    assert STEP_GRID["explanation_start"] == (64, 230)
    style_source = STYLE_PATH.read_text(encoding="utf-8")
    for token in (
        "d.ellipse((64, 50, 124, 110)",
        'd.text((145, 64), label',
        'd.text((64, 137), title',
        'd.text((64, 230), subtitle',
        'fit_text(d, text, (116, 950)',
        'rounded_shadow(img, (60, 315, 1020, 930)',
    ):
        assert token in style_source, f"Series grid token missing: {token}"
    print(f"Verified {len(files)} slides at 1080x1080; fixed step grid: {STEP_GRID}")


def verify_ui_strings():
    repo = ROOT.parents[2]
    product_source = "\n".join(
        (repo / path).read_text(encoding="utf-8")
        for path in (
            "frontend/app-venue.html",
            "frontend/positions.js",
            "frontend/positions/position-editor.js",
            "frontend/positions/position-list.js",
            "frontend/positions/permission-controller.js",
            "backend/app/core/permissions_registry.py",
        )
    )
    required = (
        "Должности",
        "Список должностей",
        "+ Добавить сотрудника",
        "Изменить",
        "Архивировать",
        "Изменить должность",
        "Меняй должность/условия для выбранного сотрудника.",
        "Шаблон прав",
        "Применить шаблон",
        "Шаблон применён",
        "Включить все",
        "Выключить все",
        "Все",
        "Ничего",
        "Просмотр смен",
        "Видеть список смен и расписание",
        "Управление сменами",
        "Создавать/редактировать смены и промежутки",
        "Сохранить",
        "Отмена",
        "Изменения сохранены",
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
    build_result()
    verify_outputs()
    verify_ui_strings()

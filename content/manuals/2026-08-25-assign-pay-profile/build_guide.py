from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
SERIES_PATH = ROOT.parent / "2026-08-20-pay-profile" / "build_guide.py"
SPEC = spec_from_file_location("axelio_pay_profile_series", SERIES_PATH)
SERIES = module_from_spec(SPEC)
SPEC.loader.exec_module(SERIES)

NAVY = SERIES.NAVY
TEXT = SERIES.TEXT
MUTED = SERIES.MUTED
PURPLE = SERIES.PURPLE
PURPLE_LIGHT = SERIES.PURPLE_LIGHT
PANEL = SERIES.PANEL
PANEL_CARD = SERIES.PANEL_CARD
PANEL_CARD_2 = SERIES.PANEL_CARD_2
PANEL_LINE = SERIES.PANEL_LINE
PANEL_TEXT = SERIES.PANEL_TEXT
PANEL_MUTED = SERIES.PANEL_MUTED
BLUE = SERIES.BLUE
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
field = SERIES.field
toast = SERIES.toast

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


def checkbox(draw, xy, label, checked=True, highlight=False, size=16):
    x, y = xy
    if highlight:
        draw.rounded_rectangle((x - 8, y - 8, x + 280, y + 44), radius=13, outline=PURPLE, width=4)
    fill = BLUE if checked else PANEL_CARD_2
    draw.rounded_rectangle((x, y, x + 28, y + 28), radius=5, fill=fill, outline=BLUE if checked else PANEL_LINE, width=2)
    if checked:
        draw.line((x + 7, y + 14, x + 12, y + 20), fill="white", width=4)
        draw.line((x + 12, y + 20, x + 22, y + 8), fill="white", width=4)
    panel_text(draw, (x + 42, y + 3), label, size, True)


def modal_shell(img):
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((104, 355, 976, 876), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(draw, (132, 380), "Новое назначение", 27, True)
    panel_text(draw, (132, 419), "Если даты пустые, профиль считается действующим без ограничений", 15, False, PANEL_MUTED)
    button(draw, (825, 374, 944, 430), "Закрыть", size=15)
    return draw


def assignment_form(img, highlight_employee=False, highlight_dates=False, highlight_save=False, filled_dates=True):
    draw = modal_shell(img)
    if highlight_dates:
        draw.rounded_rectangle((121, 604, 955, 756), radius=18, outline=PURPLE, width=4)
    field(
        draw,
        (132, 515, 944, 575),
        "Сотрудник",
        "София",
        highlight=highlight_employee,
        dropdown=True,
        value_size=18,
    )
    start_value = "25.08.2026" if filled_dates else "дд.мм.гггг"
    field(draw, (132, 650, 525, 710), "Дата начала", start_value, value_size=18)
    field(draw, (552, 650, 944, 710), "Дата окончания", "дд.мм.гггг", value_size=18)
    checkbox(draw, (132, 756), "Назначение активно", checked=True)
    button(draw, (660, 804, 790, 856), "Отмена", size=16)
    button(draw, (806, 804, 944, 856), "Сохранить", kind="primary", highlight=highlight_save, size=16)
    return draw


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
        highlighted = label == "Профили зарплаты"
        box = (x, y, x + width, y + 72)
        draw.rounded_rectangle(
            box,
            radius=15,
            fill=PANEL_CARD,
            outline=PURPLE if highlighted else PANEL_LINE,
            width=5 if highlighted else 2,
        )
        label_font = font(16 if highlighted else 17, True)
        text_width = draw.textbbox((0, 0), label, font=label_font)[2]
        draw.text((x + width / 2 - text_width / 2, y + 23), label, font=label_font, fill=PANEL_TEXT)


def build_cover():
    img = base_canvas()
    draw = ImageDraw.Draw(img)
    draw_brand(img)
    draw.multiline_text((62, 178), "Как назначить\nпрофиль зарплаты?", font=font(54, True), fill=NAVY, spacing=5)
    fit_text(
        draw,
        "Назначение связывает сотрудника с правилами начисления на выбранный период.",
        (66, 402),
        470,
        28,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        draw,
        "Если даты не указаны, профиль действует без ограничений.",
        (66, 620),
        470,
        29,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "assign-pay-profile-illustration.png").convert("RGB")
    art = art.crop((70, 100, 1180, 1210)).resize((450, 450), Image.Resampling.LANCZOS)
    mask = Image.new("L", art.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, 450, 450), radius=44, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    img.paste(art, (615, 305), mask)

    rounded_shadow(img, (62, 842, 1018, 1015), radius=28, fill="#ffffff", outline="#d4cdf6", width=2, blur=14)
    draw = ImageDraw.Draw(img)
    draw.ellipse((106, 881, 194, 969), fill=PURPLE)
    draw.text((140, 901), "1", font=font(43, True), fill="white")
    draw.text((235, 877), "Откройте нужный профиль", font=font(33, True), fill=NAVY)
    draw.text((235, 930), "В разделе «Профили зарплаты».", font=font(25), fill=MUTED)
    save(img, "01-cover.png")


def build_step_1():
    img = base_canvas()
    draw_step_header(img, "1", "ШАГ 1", "Откройте профили зарплаты", "На странице заведения найдите блок «Финансы».")
    draw_finance_entry(img)
    draw_bottom_note(img, "Нажмите «Профили зарплаты» — откроется список шаблонов начислений.")
    save(img, "02-step.png")


def build_step_2():
    img = base_canvas()
    draw_step_header(img, "2", "ШАГ 2", "Выберите нужный профиль", "Нажмите «Открыть» в строке с нужным набором начислений.")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    panel_text(draw, (112, 374), "Профили зарплаты", 26, True)
    panel_text(draw, (112, 415), "шаблоны начислений для сотрудников", 16, False, PANEL_MUTED)
    draw.rounded_rectangle((112, 485, 968, 838), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (140, 515), "Список профилей", 27, True)
    draw.rounded_rectangle((140, 606, 940, 784), radius=17, fill="#151f3e", outline=PANEL_LINE, width=2)
    panel_text(draw, (166, 634), "Бар и зал", 22, True)
    panel_text(draw, (166, 674), "Почасовая ставка + фикс за смену для бара и сервиса", 15, False, PANEL_MUTED)
    panel_text(draw, (166, 714), "Компонентов: 2 · Назначений: 4", 14, False, PANEL_MUTED)
    button(draw, (610, 632, 704, 691), "Открыть", highlight=True, size=14)
    button(draw, (714, 632, 812, 691), "Изменить", size=13)
    button(draw, (822, 632, 922, 691), "Отключить", kind="danger", size=12)
    button(draw, (822, 706, 922, 765), "Удалить", kind="danger", size=12)
    draw_bottom_note(img, "В карточке профиля будут блоки «Компоненты» и «Назначения».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Добавьте назначение", "В блоке «Назначения» нажмите «+ Назначить».")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((108, 365, 972, 850), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(draw, (136, 392), "Бар и зал", 26, True)
    panel_text(draw, (136, 432), "Почасовая ставка + фикс за смену для бара и сервиса", 16, False, PANEL_MUTED)
    panel_text(draw, (136, 471), "Активный профиль · Компонентов: 2 · Назначений: 4", 15, False, PANEL_MUTED)
    draw.rounded_rectangle((136, 535, 944, 806), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (160, 560), "Назначения", 24, True)
    button(draw, (742, 548, 915, 607), "+ Назначить", kind="primary", highlight=True, size=16)
    fit_text(
        draw,
        "Назначения определяют, какой профиль действует у сотрудника в выбранный период.",
        (160, 632),
        690,
        16,
        PANEL_MUTED,
        spacing=5,
    )
    draw.rounded_rectangle((160, 724, 916, 778), radius=13, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(draw, (180, 738), "Даниил", 16, True)
    panel_text(draw, (535, 741), "2026-08-01 → без даты окончания", 13, False, PANEL_MUTED)
    draw_bottom_note(img, "Откроется форма «Новое назначение».")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Выберите сотрудника", "В поле «Сотрудник» укажите человека из команды заведения.")
    assignment_form(img, highlight_employee=True, filled_dates=False)
    draw_bottom_note(img, "В списке отображаются активные участники заведения.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Задайте период", "Укажите «Дата начала» и при необходимости «Дата окончания».")
    assignment_form(img, highlight_dates=True)
    draw_bottom_note(img, "Если даты пустые, профиль считается действующим без ограничений.")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Сохраните назначение", "Оставьте «Назначение активно» включённым и нажмите «Сохранить».")
    assignment_form(img, highlight_save=True)
    draw_bottom_note(img, "После сохранения сотрудник появится в блоке «Назначения».")
    save(img, "07-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Профиль назначен", "Сотрудник появился в блоке «Назначения».")
    draw_ui_frame(img)
    draw = ImageDraw.Draw(img)
    toast(draw, "Назначение создано")
    draw.rounded_rectangle((112, 470, 968, 766), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(draw, (142, 496), "Бар и зал", 25, True)
    panel_text(draw, (142, 536), "Активный профиль · Компонентов: 2 · Назначений: 5", 15, False, PANEL_MUTED)
    panel_text(draw, (142, 592), "Назначения", 22, True)
    draw.rounded_rectangle((142, 634, 938, 728), radius=15, fill=PANEL_CARD_2, outline=PURPLE, width=4)
    panel_text(draw, (164, 650), "София", 20, True)
    panel_text(draw, (164, 686), "2026-08-25 → без даты окончания", 15, False, PANEL_MUTED)
    button(draw, (690, 653, 796, 709), "Изменить", size=13)
    button(draw, (806, 653, 906, 709), "Удалить", kind="danger", size=12)
    draw.rounded_rectangle((112, 797, 968, 860), radius=15, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(draw, (142, 817), "Следующая инструкция: Как проверить начисления сотрудника?", 20, True, PURPLE_LIGHT)
    draw_bottom_note(img, "Теперь профиль участвует в расчёте сотрудника с указанной даты.")
    save(img, "08-result.png")


def verify_outputs():
    files = [
        "01-cover.png",
        "02-step.png",
        "03-step.png",
        "04-step.png",
        "05-step.png",
        "06-step.png",
        "07-step.png",
        "08-result.png",
    ]
    for filename in files:
        with Image.open(ROOT / filename) as image:
            assert image.size == (1080, 1080), f"{filename}: {image.size}"
    assert STEP_GRID == SERIES.STEP_GRID
    print(f"Verified {len(files)} slides at 1080x1080; fixed step grid: {STEP_GRID}")


def verify_ui_strings():
    repo = ROOT.parents[2]
    product_source = "\n".join(
        (repo / path).read_text(encoding="utf-8")
        for path in (
            "frontend/app-venue.html",
            "frontend/owner-pay-profiles.js",
            "frontend/owner-pay-profile.js",
            "frontend/owner-pay-profile/assignment-controller.js",
        )
    )
    required = (
        "Профили зарплаты",
        "Открыть",
        "Назначения",
        "+ Назначить",
        "Назначения определяют, какой профиль действует у сотрудника в выбранный период.",
        "Новое назначение",
        "Если даты пустые, профиль считается действующим без ограничений",
        "Сотрудник",
        "Выбери сотрудника",
        "Дата начала",
        "Дата окончания",
        "Назначение активно",
        "Отмена",
        "Сохранить",
        "Назначение создано",
        "Изменить",
        "Удалить",
        "без даты окончания",
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
    build_result()
    verify_outputs()
    verify_ui_strings()

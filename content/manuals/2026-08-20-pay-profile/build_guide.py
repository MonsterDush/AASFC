from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
SERIES_PATH = ROOT.parent / "2026-08-20-position-permissions" / "build_guide.py"
SPEC = spec_from_file_location("axelio_manual_series", SERIES_PATH)
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
series_panel_text = SERIES.panel_text
button = SERIES.button
field = SERIES.field
chip = SERIES.chip
toggle = SERIES.toggle
toast = SERIES.toast

STEP_GRID = {
    "number_circle": (64, 50, 124, 110),
    "step_label": (145, 64),
    "title_start": (64, 137),
    "explanation_start": (64, 230),
    "ui_frame": (60, 315, 1020, 930),
    "bottom_note_y": 950,
}

UI_RUBLE_FONT = "/System/Library/Fonts/SFNS.ttf"


def panel_text(draw, xy, text, size=22, bold=False, fill=PANEL_TEXT):
    """Keep the series font, but use a glyph-complete UI fallback for ₽."""
    if "₽" not in text:
        return series_panel_text(draw, xy, text, size, bold, fill)
    ui_font = ImageFont.truetype(UI_RUBLE_FONT, size)
    draw.text(xy, text, font=ui_font, fill=fill)


def save(img, name):
    img.convert("RGB").save(ROOT / name, quality=95)


def checkbox(draw, xy, label, checked=True, highlight=False, size=17):
    x, y = xy
    if highlight:
        draw.rounded_rectangle((x - 8, y - 8, x + 250, y + 44), radius=13, outline=PURPLE, width=4)
    fill = BLUE if checked else PANEL_CARD_2
    draw.rounded_rectangle((x, y, x + 28, y + 28), radius=5, fill=fill, outline=BLUE if checked else PANEL_LINE, width=2)
    if checked:
        draw.line((x + 7, y + 14, x + 12, y + 20), fill="white", width=4)
        draw.line((x + 12, y + 20, x + 22, y + 8), fill="white", width=4)
    panel_text(draw, (x + 42, y + 3), label, size, True)


def textarea(draw, box, label, value, highlight=False, value_size=17):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 28), label, 15, True, PANEL_MUTED)
    draw.rounded_rectangle(
        box,
        radius=14,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlight else PANEL_LINE,
        width=4 if highlight else 2,
    )
    fit_text(draw, value, (x1 + 15, y1 + 14), x2 - x1 - 30, value_size, PANEL_TEXT, spacing=5)


def modal_shell(img, title, hint, top=360, bottom=866):
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((104, top, 976, bottom), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (132, top + 24), title, 27, True)
    panel_text(d, (132, top + 62), hint, 16, False, PANEL_MUTED)
    button(d, (825, top + 19, 944, top + 75), "Закрыть", size=15)
    return d


def profile_form(img, highlight_title=False, highlight_save=False):
    d = modal_shell(img, "Новый профиль", "После создания откроется карточка профиля")
    field(d, (132, 515, 944, 577), "Название", "Бариста — смена", highlight=highlight_title, value_size=19)
    textarea(d, (132, 650, 944, 740), "Описание", "Фиксированная ставка для бариста", value_size=17)
    checkbox(d, (132, 775), "Профиль активен", checked=True)
    button(d, (660, 790, 790, 844), "Отмена", size=16)
    button(d, (806, 790, 944, 844), "Сохранить", kind="primary", highlight=highlight_save, size=16)
    return d


def component_base(img, highlight_type=False, highlight_fields=False, highlight_save=False):
    d = modal_shell(img, "Новый компонент", "Поддержаны ставки, проценты и KPI-бонусы", top=350, bottom=878)
    d.rounded_rectangle((124, 455, 956, 812), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (148, 476), "Основа компонента", 20, True)
    panel_text(d, (148, 508), "Сначала выбери тип и базовые параметры.", 15, False, PANEL_MUTED)
    if highlight_fields:
        d.rounded_rectangle((137, 550, 943, 800), radius=17, outline=PURPLE, width=4)
    field(d, (150, 580, 525, 640), "Тип", "Фикс за смену", highlight=highlight_type, dropdown=True, value_size=18)
    field(d, (552, 580, 930, 640), "Название компонента", "Фикс за смену", value_size=18)
    field(d, (150, 720, 525, 780), "Сумма, ₽ / смена", "1000", value_size=18)
    field(d, (552, 720, 730, 780), "Порядок", "0", value_size=18)
    checkbox(d, (760, 738), "Компонент активен", checked=True, size=14)
    button(d, (650, 820, 786, 868), "Отмена", size=15)
    button(d, (802, 820, 944, 868), "Сохранить", kind="primary", highlight=highlight_save, size=15)
    return d


def build_cover():
    img = base_canvas()
    d = ImageDraw.Draw(img)
    draw_brand(img)
    d.multiline_text((62, 178), "Как настроить\nпрофиль зарплаты?", font=font(54, True), fill=NAVY, spacing=5)
    fit_text(
        d,
        "Профиль зарплаты — это набор правил: оклад, ставка за час или смену, проценты и KPI-бонусы.",
        (66, 402),
        470,
        28,
        fill=TEXT,
        spacing=8,
    )
    fit_text(
        d,
        "После настройки профиль можно назначить сотрудникам.",
        (66, 646),
        470,
        29,
        fill=TEXT,
        spacing=8,
    )

    art = Image.open(ROOT / "assets" / "pay-profile-illustration.png").convert("RGB")
    art = art.crop((70, 95, 1180, 1205)).resize((450, 450), Image.Resampling.LANCZOS)
    mask = Image.new("L", art.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, 450, 450), radius=44, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    img.paste(art, (615, 305), mask)

    rounded_shadow(img, (62, 842, 1018, 1015), radius=28, fill="#ffffff", outline="#d4cdf6", width=2, blur=14)
    d = ImageDraw.Draw(img)
    d.ellipse((106, 881, 194, 969), fill=PURPLE)
    d.text((140, 901), "1", font=font(43, True), fill="white")
    d.text((235, 877), "Откройте «Профили зарплаты»", font=font(33, True), fill=NAVY)
    d.text((235, 930), "В блоке «Финансы» нужного заведения.", font=font(25), fill=MUTED)
    save(img, "01-cover.png")


def build_step_1():
    img = base_canvas()
    draw_step_header(img, "1", "ШАГ 1", "Откройте профили зарплаты", "На странице заведения найдите блок «Финансы».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    panel_text(d, (118, 380), "Axelio E2E Lounge", 21, True)
    panel_text(d, (118, 420), "Здесь собраны основные разделы, настройки и команда заведения.", 17, False, PANEL_MUTED)
    panel_text(d, (118, 486), "Финансы", 30, True)
    panel_text(d, (118, 530), "Сводка, зарплаты, расходы и аналитика дня.", 19, False, PANEL_MUTED)
    labels = [
        ("Сводка", 118, 590),
        ("Профили зарплаты", 332, 590),
        ("Начисления", 606, 590),
        ("Экономика дня", 808, 590),
        ("Планы", 118, 690),
        ("Нормативы", 332, 690),
        ("Расходы", 546, 690),
        ("Штрафы", 760, 690),
    ]
    widths = {"Профили зарплаты": 246, "Экономика дня": 164}
    for label, x, y in labels:
        w = widths.get(label, 186)
        highlighted = label == "Профили зарплаты"
        box = (x, y, x + w, y + 72)
        d.rounded_rectangle(box, radius=15, fill=PANEL_CARD, outline=PURPLE if highlighted else PANEL_LINE, width=5 if highlighted else 2)
        f = font(16 if label == "Профили зарплаты" else 17, True)
        tw = d.textbbox((0, 0), label, font=f)[2]
        d.text((x + w / 2 - tw / 2, y + 23), label, font=f, fill=PANEL_TEXT)
    draw_bottom_note(img, "Нажмите «Профили зарплаты» — откроется список шаблонов начислений.")
    save(img, "02-step.png")


def build_step_2():
    img = base_canvas()
    draw_step_header(img, "2", "ШАГ 2", "Добавьте новый профиль", "Нажмите «+ Добавить профиль» вверху списка.")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    panel_text(d, (112, 374), "Профили зарплаты", 26, True)
    fit_text(d, "Здесь настраиваются шаблоны начислений: оклад, почасовая ставка и фикс за смену.", (112, 413), 700, 16, PANEL_MUTED, spacing=5)
    d.rounded_rectangle((112, 490, 968, 848), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (140, 516), "Список профилей", 27, True)
    button(d, (715, 504, 936, 563), "+ Добавить профиль", kind="primary", highlight=True, size=16)
    d.rounded_rectangle((140, 610, 940, 786), radius=17, fill="#151f3e", outline=PANEL_LINE, width=2)
    panel_text(d, (166, 635), "Бар и зал", 22, True)
    panel_text(d, (166, 674), "Почасовая ставка + фикс за смену для бара и сервиса", 15, False, PANEL_MUTED)
    panel_text(d, (166, 712), "Компонентов: 2 · Назначений: 4", 14, False, PANEL_MUTED)
    button(d, (610, 632, 704, 691), "Открыть", size=14)
    button(d, (714, 632, 812, 691), "Изменить", size=13)
    button(d, (822, 632, 922, 691), "Отключить", kind="danger", size=12)
    button(d, (822, 706, 922, 765), "Удалить", kind="danger", size=12)
    draw_bottom_note(img, "Откроется форма «Новый профиль».")
    save(img, "03-step.png")


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Укажите название профиля", "Описание поможет команде понять, для кого этот профиль.")
    profile_form(img, highlight_title=True)
    draw_bottom_note(img, "Оставьте «Профиль активен» включённым, если он уже будет использоваться.")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Сохраните профиль", "Нажмите «Сохранить» — откроется карточка профиля.")
    profile_form(img, highlight_save=True)
    draw_bottom_note(img, "После сохранения Axelio сразу откроет карточку нового профиля.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Добавьте компонент", "В блоке «Компоненты» нажмите «+ Добавить».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((108, 368, 972, 846), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (136, 394), "Бариста — смена", 26, True)
    panel_text(d, (136, 434), "Фиксированная ставка для бариста", 16, False, PANEL_MUTED)
    panel_text(d, (136, 474), "Активный профиль · Компонентов: 0 · Назначений: 0", 15, False, PANEL_MUTED)
    d.rounded_rectangle((136, 535, 944, 804), radius=18, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (160, 560), "Компоненты", 24, True)
    button(d, (765, 548, 915, 607), "+ Добавить", kind="primary", highlight=True, size=16)
    fit_text(d, "Доступны: оклад, почасовая ставка, фикс за смену, проценты по выручке и KPI-бонусы по закрытым отчётам.", (160, 634), 690, 16, PANEL_MUTED, spacing=5)
    panel_text(d, (160, 748), "Компоненты ещё не добавлены", 17, False, PANEL_MUTED)
    draw_bottom_note(img, "Компонент — это отдельное правило начисления внутри профиля.")
    save(img, "06-step.png")


def build_step_6():
    img = base_canvas()
    draw_step_header(img, "6", "ШАГ 6", "Выберите тип начисления", "Для примера используем «Фикс за смену».")
    component_base(img, highlight_type=True)
    draw_bottom_note(img, "Список также содержит оклад, почасовую ставку, проценты и KPI-бонус.")
    save(img, "07-step.png")


def build_step_7():
    img = base_canvas()
    draw_step_header(img, "7", "ШАГ 7", "Укажите название и сумму", "Введите сумму в рублях за одну смену.")
    component_base(img, highlight_fields=True)
    draw_bottom_note(img, "«Порядок» задаёт положение компонента в списке; по умолчанию — 0.")
    save(img, "08-step.png")


def build_step_8():
    img = base_canvas()
    draw_step_header(img, "8", "ШАГ 8", "Сохраните компонент", "Проверьте краткую схему расчёта и нажмите «Сохранить».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((104, 360, 976, 866), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (132, 386), "Новый компонент", 27, True)
    panel_text(d, (132, 424), "Поддержаны ставки, проценты и KPI-бонусы", 16, False, PANEL_MUTED)
    d.rounded_rectangle((132, 492, 944, 682), radius=16, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (158, 517), "КАК БУДЕТ РАБОТАТЬ КОМПОНЕНТ", 14, True, PANEL_MUTED)
    panel_text(d, (158, 558), "Фикс за смену", 23, True)
    panel_text(d, (158, 602), "1 000,00 ₽", 19, False, PANEL_MUTED)
    d.rounded_rectangle((132, 714, 944, 758), radius=13, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(d, (154, 725), "Компонент активен", 17, True)
    toggle(d, (842, 718, 914, 754), checked=True)
    button(d, (650, 790, 786, 842), "Отмена", size=16)
    button(d, (802, 790, 944, 842), "Сохранить", kind="primary", highlight=True, size=16)
    draw_bottom_note(img, "Если ставки различаются по дням, их можно настроить в отдельном блоке формы.")
    save(img, "09-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Профиль настроен", "Компонент появился в карточке профиля.")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    toast(d, "Компонент создан")
    d.rounded_rectangle((112, 474, 968, 760), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (142, 500), "Бариста — смена", 25, True)
    panel_text(d, (142, 540), "Активный профиль · Компонентов: 1 · Назначений: 0", 15, False, PANEL_MUTED)
    panel_text(d, (142, 596), "Компоненты", 22, True)
    d.rounded_rectangle((142, 636, 938, 728), radius=15, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(d, (164, 652), "Фикс за смену", 20, True)
    panel_text(d, (164, 684), "Фикс за смену · 1 000,00 ₽ / смена", 15, False, PANEL_MUTED)
    button(d, (690, 652, 796, 708), "Изменить", size=13)
    button(d, (806, 652, 906, 708), "Отключить", kind="danger", size=12)
    d.rounded_rectangle((112, 797, 968, 860), radius=15, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(d, (142, 817), "Следующая инструкция: Как назначить профиль сотруднику?", 21, True, PURPLE_LIGHT)
    draw_bottom_note(img, "Теперь профиль можно назначить сотруднику или связать с должностью.")
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
            "frontend/owner-pay-profile/component-form.js",
            "frontend/owner-pay-profile/component-controller.js",
            "frontend/owner-pay-profile/component-list.js",
        )
    )
    required = (
        "Профили зарплаты",
        "+ Добавить профиль",
        "Новый профиль",
        "После создания откроется карточка профиля",
        "Название",
        "Описание",
        "Профиль активен",
        "Отмена",
        "Сохранить",
        "Компоненты",
        "+ Добавить",
        "Компоненты ещё не добавлены",
        "Новый компонент",
        "Поддержаны ставки, проценты и KPI-бонусы",
        "Тип",
        "Фикс за смену",
        "Название компонента",
        "Сумма, ₽ / смена",
        "Порядок",
        "Компонент активен",
        "Как будет работать компонент",
        "Компонент создан",
        "Изменить",
        "Отключить",
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

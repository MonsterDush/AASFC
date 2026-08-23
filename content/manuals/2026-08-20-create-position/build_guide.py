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


def field(draw, box, label, value, highlight=False, dropdown=False, value_size=20):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 29), label, 16, True, PANEL_MUTED)
    draw.rounded_rectangle(
        box,
        radius=15,
        fill=PANEL_CARD_2,
        outline=PURPLE if highlight else PANEL_LINE,
        width=4 if highlight else 2,
    )
    panel_text(draw, (x1 + 16, y1 + 15), value, value_size, False, PANEL_TEXT)
    if dropdown:
        cx, cy = x2 - 22, y1 + 30
        draw.polygon(((cx - 7, cy - 4), (cx + 7, cy - 4), (cx, cy + 5)), fill=PANEL_MUTED)


def chip(draw, box, label, fill="#202b50", outline=PANEL_LINE, text_fill=PANEL_TEXT, size=14):
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=1)
    x1, y1, x2, y2 = box
    f = font(size, True)
    tw = draw.textbbox((0, 0), label, font=f)[2]
    draw.text(((x1 + x2 - tw) / 2, y1 + 8), label, font=f, fill=text_fill)


def save(img, name):
    img.convert("RGB").save(ROOT / name, quality=95)


def build_cover():
    img = base_canvas()
    d = ImageDraw.Draw(img)
    draw_brand(img)
    d.multiline_text((62, 182), "Как создать\nдолжность?", font=font(72, True), fill=NAVY, spacing=6)
    fit_text(
        d,
        "Должность объединяет сотрудника, профиль зарплаты и права доступа.",
        (66, 405),
        500,
        31,
        fill=TEXT,
        spacing=9,
    )
    fit_text(
        d,
        "Одну должность можно назначить нескольким сотрудникам.",
        (66, 610),
        500,
        31,
        fill=TEXT,
        spacing=9,
    )

    art = Image.open(ROOT / "assets" / "position-illustration.png").convert("RGB")
    art = art.crop((85, 70, 1185, 1190)).resize((500, 510), Image.Resampling.LANCZOS)
    mask = Image.new("L", art.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, 500, 510), radius=46, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    img.paste(art, (565, 270), mask)

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
    panel_text(d, (118, 424), "Разделы", 31, True)
    panel_text(d, (118, 468), "Быстрый переход к основным разделам.", 20, False, PANEL_MUTED)
    labels = ["Должности", "Приглашения", "График", "Отчёты"]
    xs = [118, 332, 546, 760]
    for x, label in zip(xs, labels):
        highlighted = label == "Должности"
        box = (x, 535, x + 186, 610)
        d.rounded_rectangle(
            box,
            radius=16,
            fill=PANEL_CARD,
            outline=PURPLE if highlighted else PANEL_LINE,
            width=5 if highlighted else 2,
        )
        f = font(18, True)
        tw = d.textbbox((0, 0), label, font=f)[2]
        d.text((x + 93 - tw / 2, 560), label, font=f, fill=PANEL_TEXT)
    d.rounded_rectangle((118, 670, 946, 825), radius=19, fill=PANEL_CARD)
    panel_text(d, (147, 700), "Здесь настраиваются роли команды", 24, True)
    fit_text(d, "Создавайте должности, назначайте сотрудников, зарплату и права.", (147, 746), 720, 21, PANEL_MUTED, spacing=6)
    draw_bottom_note(img, "Нажмите «Должности» — откроется список ролей команды.")
    save(img, "02-step.png")


def draw_positions_list(img, highlight_create=False):
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    panel_text(d, (112, 374), "Должности", 26, True)
    panel_text(d, (112, 412), "должности, профили зарплаты и права", 17, False, PANEL_MUTED)
    d.rounded_rectangle((112, 460, 968, 855), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (140, 490), "Список должностей", 27, True)
    panel_text(d, (140, 528), "Шаблон должности остаётся в списке, даже если сотрудник ещё не назначен.", 16, False, PANEL_MUTED)
    button(d, (770, 478, 936, 540), "+ Создать", kind="primary", highlight=highlight_create, size=17)
    d.rounded_rectangle((140, 585, 938, 806), radius=18, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (166, 609), "Бармен", 23, True)
    chip(d, (266, 600, 384, 638), "1 сотрудник", size=13)
    button(d, (705, 596, 908, 648), "+ Добавить сотрудника", size=14)
    d.rounded_rectangle((166, 666, 912, 777), radius=15, fill="#151f3e", outline=PANEL_LINE, width=2)
    panel_text(d, (187, 687), "Мария · @axelio_demo_maria · STAFF", 18, True)
    chip(d, (187, 724, 351, 758), "Профиль: Бар и зал", size=12)
    chip(d, (360, 724, 459, 758), "Отчёты: нет", size=12)
    chip(d, (468, 724, 558, 758), "График: нет", size=12)
    button(d, (698, 688, 805, 751), "Изменить", size=14)
    button(d, (816, 688, 912, 751), "Архивировать", kind="danger", size=12)
    return d


def build_step_2():
    img = base_canvas()
    draw_step_header(img, "2", "ШАГ 2", "Нажмите «+ Создать»", "Кнопка находится в блоке «Список должностей».")
    draw_positions_list(img, highlight_create=True)
    draw_bottom_note(img, "Откроется форма «Создать должность».")
    save(img, "03-step.png")


def draw_modal_top(img, mode):
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((104, 360, 976, 866), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (132, 386), "Создать должность", 27, True)
    panel_text(d, (132, 424), "Одна должность может быть у нескольких сотрудников (например «Бармен»).", 16, False, PANEL_MUTED)
    button(d, (825, 382, 944, 438), "Закрыть", size=15)
    field(d, (132, 508, 544, 570), "Название должности", "Бариста", highlight=mode == "required")
    field(d, (568, 508, 944, 570), "Сотрудник", "Анна · @axelio_demo_anna · STAFF", highlight=mode == "required", dropdown=True, value_size=16)
    field(d, (132, 665, 544, 727), "Профиль зарплаты", "Бар и зал · компонентов: 2", highlight=mode == "optional", dropdown=True, value_size=17)
    field(d, (568, 665, 944, 727), "Начисление", "Бар и зал", value_size=18)
    field(d, (132, 806, 544, 860), "Шаблон прав", "Базовый сотрудник · system", highlight=mode == "optional", dropdown=True, value_size=16)
    return d


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Заполните основные поля", "Укажите название должности и выберите сотрудника.")
    draw_modal_top(img, "required")
    draw_bottom_note(img, "Подсказка в поле поможет выбрать уже используемое название.")
    save(img, "04-step.png")


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Дополните настройки", "Выберите профиль зарплаты и шаблон прав.")
    d = draw_modal_top(img, "optional")
    button(d, (570, 790, 765, 850), "Применить шаблон", highlight=True, size=15)
    draw_bottom_note(img, "Профиль можно оставить без назначения и добавить позже.")
    save(img, "05-step.png")


def build_step_5():
    img = base_canvas()
    draw_step_header(img, "5", "ШАГ 5", "Сохраните должность", "Проверьте настройки и нажмите «Сохранить».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((104, 360, 976, 866), radius=20, fill="#111a35", outline=PANEL_LINE, width=2)
    panel_text(d, (132, 386), "Создать должность", 27, True)
    d.rounded_rectangle((132, 450, 944, 528), radius=14, fill=PANEL, outline=PANEL_LINE, width=2)
    panel_text(d, (154, 467), "Видит свой график, начисления и собственные корректировки", 17, False, PANEL_MUTED)
    panel_text(d, (154, 495), "без управленческих прав.", 17, False, PANEL_MUTED)
    chip(d, (132, 555, 253, 592), "Зарплаты · 1", size=13)
    chip(d, (265, 555, 368, 592), "Смены · 1", size=13)
    chip(d, (380, 555, 546, 592), "Штрафы и споры · 1", size=12)
    d.rounded_rectangle((132, 626, 944, 724), radius=15, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(d, (158, 650), "Права можно проверить ниже в форме", 20, True)
    panel_text(d, (158, 684), "Шаблон уже применён к переключателям.", 17, False, PANEL_MUTED)
    button(d, (132, 777, 296, 840), "Сохранить", kind="primary", highlight=True, size=18)
    button(d, (312, 777, 449, 840), "Отмена", size=18)
    panel_text(d, (560, 799), "Можно назначать несколько людей на одну должность", 15, False, PANEL_MUTED)
    draw_bottom_note(img, "«Сохранить» — основное действие; «Отмена» не создаёт должность.")
    save(img, "06-step.png")


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Должность создана", "Она появилась в «Списке должностей».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((112, 370, 968, 435), radius=16, fill="#193d38", outline=GREEN, width=3)
    panel_text(d, (142, 390), "Должность создана", 24, True, "#d9ffeb")
    panel_text(d, (112, 480), "Список должностей", 28, True)
    d.rounded_rectangle((112, 530, 968, 758), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (142, 558), "Бариста", 25, True)
    chip(d, (251, 548, 373, 588), "1 сотрудник", size=13)
    button(d, (720, 545, 938, 601), "+ Добавить сотрудника", size=14)
    d.rounded_rectangle((142, 620, 938, 728), radius=15, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    panel_text(d, (164, 642), "Анна · @axelio_demo_anna · STAFF", 18, True)
    chip(d, (164, 681, 330, 715), "Профиль: Бар и зал", size=12)
    chip(d, (338, 681, 438, 715), "Отчёты: нет", size=12)
    chip(d, (446, 681, 538, 715), "График: нет", size=12)
    button(d, (700, 643, 810, 706), "Изменить", size=14)
    button(d, (821, 643, 930, 706), "Архивировать", kind="danger", size=12)
    d.rounded_rectangle((112, 797, 968, 860), radius=15, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(d, (142, 817), "Следующая инструкция: Как настроить права должности?  →", 21, True, PURPLE_LIGHT)
    draw_bottom_note(img, "Теперь должность можно назначать другим сотрудникам.")
    save(img, "07-result.png")


if __name__ == "__main__":
    build_cover()
    build_step_1()
    build_step_2()
    build_step_3()
    build_step_4()
    build_step_5()
    build_result()
    print(f"Built 7 slides in {ROOT}")

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
SIZE = 1080

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

NAVY = "#071227"
TEXT = "#10172b"
MUTED = "#596179"
PURPLE = "#8767f5"
PURPLE_LIGHT = "#efeaff"
GRID = "#e9e9f4"
CARD = "#ffffff"
PANEL = "#080d1d"
PANEL_CARD = "#111a35"
PANEL_CARD_2 = "#151f3e"
PANEL_LINE = "#2d3a65"
PANEL_TEXT = "#f4f5fb"
PANEL_MUTED = "#bdc5da"
BLUE = "#5286d8"
GREEN = "#62c58e"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def rounded_shadow(base: Image.Image, box, radius=24, fill=CARD, outline="#d8d2f5", width=2, blur=18):
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x1 + 3, y1 + 10, x2 + 3, y2 + 10), radius=radius, fill=(72, 51, 150, 30))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def base_canvas() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), "#fbfaff")
    d = ImageDraw.Draw(img)
    for x in range(0, SIZE + 1, 40):
        d.line((x, 0, x, SIZE), fill=GRID, width=1)
    for y in range(0, SIZE + 1, 40):
        d.line((0, y, SIZE, y), fill=GRID, width=1)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((560, 10, 1190, 640), fill=(151, 111, 255, 24))
    gd.ellipse((-180, 660, 460, 1260), fill=(151, 111, 255, 17))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(85)))
    return img


def fit_text(draw, text, xy, max_width, size, fill=TEXT, bold=False, spacing=10):
    words = text.split()
    lines = []
    line = ""
    f = font(size, bold)
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=f)[2] <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    draw.multiline_text(xy, "\n".join(lines), font=f, fill=fill, spacing=spacing)
    return lines


def draw_brand(img: Image.Image):
    d = ImageDraw.Draw(img)
    logo = Image.open(ROOT.parent.parent.parent / "frontend" / "logo.png").convert("RGBA")
    logo.thumbnail((68, 68), Image.Resampling.LANCZOS)
    img.alpha_composite(logo, (58, 48))
    d.text((136, 63), "AXELIO", font=font(34, True), fill=NAVY)
    d.ellipse((313, 77, 326, 90), fill=PURPLE)
    d.text((349, 67), "БЫСТРЫЙ СТАРТ", font=font(24, True), fill="#6d748c")


def draw_step_header(img: Image.Image, n: str, label: str, title: str, subtitle: str):
    d = ImageDraw.Draw(img)
    d.ellipse((64, 50, 124, 110), fill=PURPLE)
    if n == "✓":
        d.line((78, 80, 90, 92), fill="white", width=7)
        d.line((90, 92, 111, 68), fill="white", width=7)
    else:
        n_font = font(30, True)
        n_box = d.textbbox((0, 0), n, font=n_font)
        d.text((94 - (n_box[2] - n_box[0]) / 2, 80 - (n_box[3] - n_box[1]) / 2 - 2), n, font=n_font, fill="white")
    d.text((145, 64), label, font=font(27, True), fill=PURPLE)
    d.text((64, 137), title, font=font(56, True), fill=NAVY)
    d.text((64, 230), subtitle, font=font(29), fill=TEXT)


def draw_bottom_note(img: Image.Image, text: str):
    d = ImageDraw.Draw(img)
    d.ellipse((76, 963, 94, 981), fill=PURPLE)
    fit_text(d, text, (116, 950), 860, 27, fill=MUTED, spacing=5)


def draw_ui_frame(img: Image.Image):
    rounded_shadow(img, (60, 315, 1020, 930), radius=28, fill="#ffffff", outline="#d4cdf6", width=2, blur=14)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((82, 337, 998, 905), radius=24, fill=PANEL)


def panel_text(draw, xy, text, size=22, bold=False, fill=PANEL_TEXT):
    draw.text(xy, text, font=font(size, bold), fill=fill)


def field(draw, box, label, value, highlight=False, dropdown=False, value_fill=PANEL_TEXT):
    x1, y1, x2, y2 = box
    panel_text(draw, (x1, y1 - 32), label, 17, True, PANEL_MUTED)
    outline = PURPLE if highlight else PANEL_LINE
    width = 4 if highlight else 2
    draw.rounded_rectangle(box, radius=16, fill=PANEL_CARD_2, outline=outline, width=width)
    panel_text(draw, (x1 + 18, y1 + 16), value, 22, False, value_fill)
    if dropdown:
        cx, cy = x2 - 24, y1 + 31
        draw.polygon(((cx - 8, cy - 4), (cx + 8, cy - 4), (cx, cy + 5)), fill=PANEL_MUTED)


def draw_button(draw, box, label, highlight=False):
    x1, y1, x2, y2 = box
    if highlight:
        draw.rounded_rectangle((x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius=18, outline=PURPLE, width=5)
    draw.rounded_rectangle(box, radius=14, fill=BLUE)
    panel_text(draw, (x1 + 20, y1 + 17), label, 21, True, "#071227")


def arrow(draw, start, end, width=8, head_length=24, head_width=20):
    """Draw an arrow whose head follows the actual line direction."""
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if not length:
        return
    ux, uy = dx / length, dy / length
    bx, by = x2 - ux * head_length, y2 - uy * head_length
    px, py = -uy * head_width / 2, ux * head_width / 2
    draw.line((x1, y1, bx, by), fill=PURPLE, width=width)
    draw.polygon(((x2, y2), (bx + px, by + py), (bx - px, by - py)), fill=PURPLE)


def build_cover():
    img = base_canvas()
    d = ImageDraw.Draw(img)
    draw_brand(img)
    d.multiline_text((62, 182), "Как пригласить\nсотрудника?", font=font(72, True), fill=NAVY, spacing=6)
    fit_text(d, "Приглашение добавляет человека в команду заведения и открывает ему доступ к Axelio.", (66, 405), 500, 31, fill=TEXT, spacing=9)
    fit_text(d, "Можно пригласить по Telegram или номеру телефона.", (66, 610), 500, 31, fill=TEXT, spacing=9)

    art = Image.open(ROOT / "assets" / "invite-illustration.png").convert("RGB")
    art = art.crop((145, 150, 1160, 1170)).resize((500, 500), Image.Resampling.LANCZOS)
    mask = Image.new("L", art.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, 500, 500), radius=46, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    img.paste(art, (565, 275), mask)

    rounded_shadow(img, (62, 842, 1018, 1015), radius=28, fill="#ffffff", outline="#d4cdf6", width=2, blur=14)
    d = ImageDraw.Draw(img)
    d.ellipse((106, 881, 194, 969), fill=PURPLE)
    d.text((140, 901), "1", font=font(43, True), fill="white")
    d.text((235, 877), "Откройте нужное заведение", font=font(35, True), fill=NAVY)
    d.text((235, 930), "В блоке «Разделы» нажмите «Приглашения».", font=font(25), fill=MUTED)
    img.convert("RGB").save(ROOT / "01-cover.png", quality=95)


def build_step_1():
    img = base_canvas()
    draw_step_header(img, "1", "ШАГ 1", "Откройте «Приглашения»", "На странице заведения найдите блок «Разделы».")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    panel_text(d, (118, 380), "Axelio E2E Lounge", 21, True)
    panel_text(d, (118, 424), "Разделы", 31, True)
    panel_text(d, (118, 468), "Быстрый переход к основным разделам.", 20, False, PANEL_MUTED)
    labels = ["Должности", "Приглашения", "График", "Отчёты"]
    xs = [118, 332, 546, 760]
    for x, label in zip(xs, labels):
        hi = label == "Приглашения"
        box = (x, 535, x + 186, 610)
        d.rounded_rectangle(box, radius=16, fill=PANEL_CARD, outline=PURPLE if hi else PANEL_LINE, width=5 if hi else 2)
        tw = d.textbbox((0, 0), label, font=font(18, True))[2]
        panel_text(d, (x + 93 - tw / 2, 560), label, 18, True)
    d.rounded_rectangle((118, 670, 946, 825), radius=19, fill=PANEL_CARD)
    panel_text(d, (147, 700), "Здесь находятся настройки команды заведения", 24, True)
    fit_text(d, "Откройте раздел, чтобы создать приглашение и посмотреть участников.", (147, 746), 720, 21, PANEL_MUTED, spacing=6)
    arrow(d, (620, 735), (425, 605))
    draw_bottom_note(img, "Нажмите «Приглашения» — откроется страница команды.")
    img.convert("RGB").save(ROOT / "02-step.png", quality=95)


def draw_invite_form(img: Image.Image, mode: str):
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    panel_text(d, (116, 374), "Пригласить участника в Axelio E2E Lounge", 27, True)
    panel_text(d, (116, 413), "Axelio E2E Lounge", 18, False, PANEL_MUTED)
    field(d, (116, 488, 496, 553), "Способ приглашения", "Telegram", highlight=mode == "channel", dropdown=True)
    field(d, (520, 488, 964, 553), "Ник в Telegram", "@anna_test", highlight=mode == "contact")
    field(d, (116, 625, 620, 690), "Имя или заметка", "Анна / бариста", highlight=mode == "contact")
    field(d, (644, 625, 964, 690), "Роль", "Персонал", highlight=mode == "role", dropdown=True)
    draw_button(d, (116, 777, 395, 842), "Создать приглашение", highlight=mode == "role")
    if mode == "channel":
        d.rounded_rectangle((116, 564, 496, 715), radius=17, fill="#182341", outline=PURPLE, width=3)
        panel_text(d, (139, 590), "Telegram", 22, True)
        panel_text(d, (139, 649), "Телефон", 22, False)
        d.ellipse((454, 594, 470, 610), fill=PURPLE)
    return d


def build_step_2():
    img = base_canvas()
    draw_step_header(img, "2", "ШАГ 2", "Выберите способ", "Пригласить можно по Telegram или номеру телефона.")
    d = draw_invite_form(img, "channel")
    arrow(d, (662, 742), (468, 664))
    draw_bottom_note(img, "Выберите канал, по которому сотрудник получит ссылку.")
    img.convert("RGB").save(ROOT / "03-step.png", quality=95)


def build_step_3():
    img = base_canvas()
    draw_step_header(img, "3", "ШАГ 3", "Укажите контакт", "Введите ник в Telegram или номер сотрудника.")
    d = draw_invite_form(img, "contact")
    draw_bottom_note(img, "«Имя или заметка» поможет не перепутать приглашения.")
    img.convert("RGB").save(ROOT / "04-step.png", quality=95)


def build_step_4():
    img = base_canvas()
    draw_step_header(img, "4", "ШАГ 4", "Создайте приглашение", "Для сотрудника оставьте роль «Персонал».")
    d = draw_invite_form(img, "role")
    arrow(d, (575, 813), (397, 813))
    draw_bottom_note(img, "Роль «Владелец» даёт расширенный доступ к заведению.")
    img.convert("RGB").save(ROOT / "05-step.png", quality=95)


def build_result():
    img = base_canvas()
    draw_step_header(img, "✓", "ГОТОВО", "Приглашение создано", "Отправьте сотруднику готовую ссылку.")
    draw_ui_frame(img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((112, 370, 968, 438), radius=16, fill="#193d38", outline=GREEN, width=3)
    panel_text(d, (142, 390), "Приглашение создано", 24, True, "#d9ffeb")
    panel_text(d, (699, 394), "Открыть приглашение", 18, True, "#d9ffeb")
    panel_text(d, (112, 486), "Приглашения в ожидании", 28, True)
    panel_text(d, (112, 527), "Ссылки, которые ещё не были приняты участниками.", 19, False, PANEL_MUTED)
    d.rounded_rectangle((112, 574, 968, 758), radius=20, fill=PANEL_CARD, outline=PANEL_LINE, width=2)
    panel_text(d, (143, 604), "@anna_test", 26, True)
    d.rounded_rectangle((143, 646, 263, 684), radius=19, fill="#202b50", outline=PANEL_LINE, width=1)
    panel_text(d, (160, 656), "Telegram", 16, True)
    d.rounded_rectangle((275, 646, 390, 684), radius=19, fill="#202b50", outline=PANEL_LINE, width=1)
    panel_text(d, (295, 656), "Персонал", 16, True)
    d.rounded_rectangle((143, 695, 286, 733), radius=19, fill="#3a3324", outline="#8c7540", width=1)
    panel_text(d, (162, 705), "Ожидает входа", 16, True, "#f6dea2")
    panel_text(d, (315, 704), "Открыть приглашение", 16, True, "#a992ff")
    copy_box = (592, 605, 808, 669)
    d.rounded_rectangle(copy_box, radius=14, fill=PANEL_CARD_2, outline=PANEL_LINE, width=2)
    copy_label = "Скопировать ссылку"
    copy_font = font(16, True)
    copy_width = d.textbbox((0, 0), copy_label, font=copy_font)[2]
    d.text((700 - copy_width / 2, 627), copy_label, font=copy_font, fill=PANEL_TEXT)
    d.rounded_rectangle((822, 605, 938, 669), radius=14, fill="#43212c", outline="#8a4055", width=2)
    panel_text(d, (841, 627), "Отменить", 16, True, "#ffd5df")
    d.rounded_rectangle((112, 797, 968, 860), radius=15, fill="#211a3e", outline=PURPLE, width=2)
    panel_text(d, (142, 817), "Следующая инструкция: Как создать должность?  →", 21, True, PURPLE_LIGHT)
    draw_bottom_note(img, "После принятия сотрудник появится в разделе «Участники».")
    img.convert("RGB").save(ROOT / "06-result.png", quality=95)


if __name__ == "__main__":
    build_cover()
    build_step_1()
    build_step_2()
    build_step_3()
    build_step_4()
    build_result()
    print(f"Built 6 slides in {ROOT}")

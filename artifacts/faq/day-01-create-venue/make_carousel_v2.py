from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw-local"
OUT = ROOT / "carousel-v2"
BACKGROUND = OUT / "background.png"
LOGO = ROOT.parents[2] / "frontend" / "logo.png"

WIDTH = 1080
HEIGHT = 1350

PAPER = "#F5F1EA"
INK = "#111827"
NAVY = "#0C1324"
PANEL = "#111A30"
MUTED = "#687184"
WHITE = "#F7F8FB"
ACCENT = "#D95763"
ACCENT_SOFT = "#F7D9DC"

FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size, index=index)


REGULAR = 0
BOLD = 1
MEDIUM = 10


def fit_background() -> Image.Image:
    return ImageOps.fit(
        Image.open(BACKGROUND).convert("RGB"),
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS,
    ).convert("RGBA")


def prepare_logo(max_size: tuple[int, int]) -> Image.Image:
    logo = Image.open(LOGO).convert("RGBA")
    pixels = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, _ = pixels[x, y]
            if r > 242 and g > 242 and b > 242:
                pixels[x, y] = (255, 255, 255, 0)
    logo.thumbnail(max_size, Image.Resampling.LANCZOS)
    return logo


def rounded_image(source: Image.Image, size: tuple[int, int], radius: int = 24) -> Image.Image:
    fitted = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    result = Image.new("RGBA", size, (0, 0, 0, 0))
    result.paste(fitted, (0, 0), mask)
    return result


def add_shadow(canvas: Image.Image, box: tuple[int, int, int, int], radius: int = 30) -> None:
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", (x2 - x1 + 80, y2 - y1 + 80), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (40, 30, x2 - x1 + 40, y2 - y1 + 30),
        radius=radius,
        fill=(17, 24, 39, 85),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    canvas.alpha_composite(shadow, (x1 - 40, y1 - 30))


def header(canvas: Image.Image, section: str = "БЫСТРЫЙ СТАРТ") -> None:
    draw = ImageDraw.Draw(canvas)
    logo = prepare_logo((50, 50))
    canvas.alpha_composite(logo, (58, 48))
    draw.text((122, 56), "AXELIO", font=font(27, BOLD), fill=INK)
    draw.ellipse((236, 68, 244, 76), fill=ACCENT)
    draw.text((261, 58), section, font=font(20, MEDIUM), fill=MUTED)


def route_chip(draw: ImageDraw.ImageDraw, y: int, text: str) -> None:
    route_font = font(23, MEDIUM)
    bbox = draw.textbbox((0, 0), text, font=route_font)
    width = min(WIDTH - 116, bbox[2] - bbox[0] + 50)
    draw.rounded_rectangle((58, y, 58 + width, y + 58), radius=18, fill=(255, 255, 255, 205), outline="#B6BCC7", width=2)
    draw.ellipse((78, y + 21, 92, y + 35), fill=ACCENT)
    draw.text((108, y + 15), text, font=route_font, fill=INK)


def draw_step_number(draw: ImageDraw.ImageDraw, number: int, x: int, y: int, size: int = 54) -> None:
    draw.ellipse((x, y, x + size, y + size), fill=ACCENT)
    text = str(number)
    number_font = font(round(size * 0.47), BOLD)
    box = draw.textbbox((0, 0), text, font=number_font)
    draw.text(
        (x + (size - (box[2] - box[0])) / 2, y + (size - (box[3] - box[1])) / 2 - box[1] - 1),
        text,
        font=number_font,
        fill=WHITE,
    )


def open_venue_menu(source: Image.Image) -> Image.Image:
    """Add a faithful documentation overlay for the native select popup.

    Native browser select menus are OS surfaces and are not captured by the
    browser screenshot API. This overlay uses the two actual product options
    and is clearly presented as an instructional annotation.
    """
    image = source.convert("RGBA")
    draw = ImageDraw.Draw(image)

    x1, y1, x2, y2 = 748, 258, 1106, 370
    shadow = Image.new("RGBA", (x2 - x1 + 36, y2 - y1 + 36), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((18, 12, x2 - x1 + 18, y2 - y1 + 12), radius=17, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    image.alpha_composite(shadow, (x1 - 18, y1 - 12))

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=15, fill="#121B31", outline="#43506A", width=2)
    draw.text((x1 + 22, y1 + 16), "Axelio E2E Lounge", font=font(17, MEDIUM), fill="#BFC7D6")
    draw.line((x1 + 14, y1 + 53, x2 - 14, y1 + 53), fill="#2A3650", width=2)
    draw.rounded_rectangle((x1 + 8, y1 + 61, x2 - 8, y2 - 8), radius=10, fill="#3C1E29")
    draw.text((x1 + 22, y1 + 76), "Управление заведениями", font=font(18, BOLD), fill="#FFFFFF")
    draw.ellipse((x2 - 34, y1 + 82, x2 - 24, y1 + 92), fill=ACCENT)
    draw.rounded_rectangle((x1 - 4, y1 - 4, x2 + 4, y2 + 4), radius=18, outline=ACCENT, width=4)
    return image


def add_highlight(
    image: Image.Image,
    box: tuple[int, int, int, int],
    label: str,
    label_y_offset: int = -38,
) -> Image.Image:
    result = image.convert("RGBA")
    draw = ImageDraw.Draw(result)
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=15, outline=ACCENT, width=5)
    label_font = font(15, BOLD)
    text_box = draw.textbbox((0, 0), label, font=label_font)
    label_width = text_box[2] - text_box[0] + 24
    label_y = max(8, y1 + label_y_offset)
    draw.rounded_rectangle((x1, label_y, x1 + label_width, label_y + 31), radius=9, fill=ACCENT)
    draw.text((x1 + 12, label_y + 7), label, font=label_font, fill=WHITE)
    return result


def add_outline(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    result = image.convert("RGBA")
    ImageDraw.Draw(result).rounded_rectangle(box, radius=15, outline=ACCENT, width=5)
    return result


def render_cover() -> None:
    canvas = fit_background()
    draw = ImageDraw.Draw(canvas)
    header(canvas)

    draw.text((58, 165), "Как создать", font=font(86, BOLD), fill=INK)
    draw.text((58, 257), "заведение", font=font(86, BOLD), fill=INK)
    route_chip(draw, 382, "Настройки / Управление заведениями")
    draw.text((59, 470), "Три понятных действия — без повторного переименования", font=font(25, REGULAR), fill=MUTED)

    panel_box = (42, 560, 1038, 1040)
    add_shadow(canvas, panel_box, radius=34)
    draw.rounded_rectangle(panel_box, radius=34, fill=NAVY)

    sources = [
        open_venue_menu(Image.open(RAW / "01-settings-current.png")),
        add_highlight(Image.open(RAW / "02-venues.png"), (949, 56, 1119, 142), "СОЗДАТЬ"),
        add_highlight(Image.open(RAW / "03-create-form.png"), (191, 361, 1089, 417), "НАЗВАНИЕ"),
    ]
    labels = ["Откройте управление", "Нажмите «Создать»", "Введите название"]

    card_width = 292
    card_height = 280
    gap = 20
    start_x = 62
    for index, (source, label) in enumerate(zip(sources, labels), start=1):
        x = start_x + (index - 1) * (card_width + gap)
        y = 660
        draw_step_number(draw, index, x, 584, size=44)
        draw.text((x + 58, 592), label, font=font(18, MEDIUM), fill=WHITE)
        draw.rounded_rectangle((x, y, x + card_width, y + card_height), radius=22, fill=PANEL, outline="#2A3550", width=2)
        crop = rounded_image(source, (card_width - 24, 151), radius=16)
        canvas.alpha_composite(crop, (x + 12, y + 16))
        helper = [
            "Настройки / Заведение",
            "Кнопка вверху справа",
            "Название / Создать",
        ][index - 1]
        draw.text((x + 16, y + 198), helper, font=font(16, MEDIUM), fill=WHITE)
        draw.text((x + 16, y + 229), f"Шаг {index} из 3", font=font(15, REGULAR), fill="#8F9AAF")

    draw.text((58, 1100), "После создания — сразу к базовой настройке", font=font(31, MEDIUM), fill=INK)
    draw.text((58, 1146), "Без повторного ввода названия.", font=font(28, REGULAR), fill=ACCENT)
    draw.text((58, 1282), "Создание заведения в Axelio", font=font(21, MEDIUM), fill=MUTED)
    OUT.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUT / "00-cover.png", quality=97)


def render_slide(
    number: int,
    title_lines: tuple[str, str],
    route: str,
    source: Image.Image,
    instruction_lines: tuple[str, str],
    target: str,
) -> None:
    canvas = fit_background()
    draw = ImageDraw.Draw(canvas)
    header(canvas)

    draw_step_number(draw, number, 58, 148, size=62)
    draw.text((145, 142), title_lines[0], font=font(58, BOLD), fill=INK)
    draw.text((145, 205), title_lines[1], font=font(58, BOLD), fill=INK)
    route_chip(draw, 298, route)

    panel_box = (42, 405, 1038, 1030)
    add_shadow(canvas, panel_box, radius=32)
    draw.rounded_rectangle(panel_box, radius=32, fill=NAVY)
    screenshot = rounded_image(source, (948, 533), radius=22)
    canvas.alpha_composite(screenshot, (66, 451))
    draw.rounded_rectangle((66, 451, 1014, 984), radius=22, outline="#313D58", width=2)

    draw.ellipse((58, 1100, 76, 1118), fill=ACCENT)
    draw.text((98, 1078), instruction_lines[0], font=font(27, MEDIUM), fill=INK)
    draw.text((98, 1120), instruction_lines[1], font=font(27, REGULAR), fill=MUTED)
    draw.text((58, 1282), f"{number} / 3", font=font(20, MEDIUM), fill=MUTED)

    canvas.convert("RGB").save(OUT / target, quality=97)


def render_slides() -> None:
    step_one = open_venue_menu(Image.open(RAW / "01-settings-current.png"))
    step_two = add_highlight(Image.open(RAW / "02-venues.png"), (949, 56, 1119, 142), "СОЗДАТЬ")
    step_three = add_highlight(Image.open(RAW / "03-create-form.png"), (191, 361, 1089, 417), "ВВЕДИТЕ НАЗВАНИЕ")
    step_three = add_outline(step_three, (920, 442, 1089, 497))

    render_slide(
        1,
        ("Откройте управление", "заведениями"),
        "Настройки / Заведение",
        step_one,
        ("Нажмите на шестерёнку «Настройки».", "В списке выберите «Управление заведениями»."),
        "01-open-management.png",
    )
    render_slide(
        2,
        ("Создайте новое", "заведение"),
        "Управление заведениями",
        step_two,
        ("Нажмите «Создать заведение».", "Кнопка находится в правом верхнем углу."),
        "02-create-venue.png",
    )
    render_slide(
        3,
        ("Введите название", "заведения"),
        "Создание заведения",
        step_three,
        ("Укажите название заведения.", "Затем нажмите «Создать заведение»."),
        "03-enter-name.png",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    render_cover()
    render_slides()


if __name__ == "__main__":
    main()

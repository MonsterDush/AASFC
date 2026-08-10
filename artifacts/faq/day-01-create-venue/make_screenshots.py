from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw-local"
OUT = ROOT / "screenshots"

HEADER_HEIGHT = 72
ACCENT = "#D85A63"
BG = "#080B12"
WHITE = "#F4F6FA"

FONT = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size, index=index)


TITLE_FONT = font(27, 1)
NUMBER_FONT = font(22, 1)
LABEL_FONT = font(14, 10)


STEPS = [
    {
        "source": "01-settings.png",
        "target": "01-settings.png",
        "title": "Настройки / Заведение",
        "highlights": [
            ((1078, 660, 1138, 714), "НАСТРОЙКИ"),
            ((744, 200, 1119, 263), "ВЫБЕРИТЕ «УПРАВЛЕНИЕ ЗАВЕДЕНИЯМИ»"),
        ],
    },
    {
        "source": "02-venues.png",
        "target": "02-create-venue.png",
        "title": "Нажмите «Создать заведение»",
        "highlights": [((949, 56, 1119, 142), "СОЗДАТЬ")],
    },
    {
        "source": "03-create-form.png",
        "target": "03-enter-name.png",
        "title": "Введите название и создайте заведение",
        "highlights": [
            ((191, 361, 1089, 417), "НАЗВАНИЕ"),
            ((920, 442, 1089, 497), "ГОТОВО"),
        ],
    },
]


def add_label(draw: ImageDraw.ImageDraw, x: int, y: int, text: str) -> None:
    box = draw.textbbox((0, 0), text, font=LABEL_FONT)
    width = box[2] - box[0] + 20
    height = 28
    draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill=ACCENT)
    draw.text((x + 10, y + 6), text, font=LABEL_FONT, fill=WHITE)


def render_step(number: int, spec: dict) -> None:
    source = Image.open(RAW / spec["source"]).convert("RGB")
    canvas = Image.new("RGB", (source.width, source.height + HEADER_HEIGHT), BG)
    canvas.paste(source, (0, HEADER_HEIGHT))
    draw = ImageDraw.Draw(canvas)

    draw.rectangle((0, 0, source.width, HEADER_HEIGHT), fill=BG)
    draw.rounded_rectangle((22, 17, 60, 55), radius=10, fill=ACCENT)
    number_text = str(number)
    number_box = draw.textbbox((0, 0), number_text, font=NUMBER_FONT)
    draw.text((41 - (number_box[2] - number_box[0]) / 2, 23), number_text, font=NUMBER_FONT, fill=WHITE)
    draw.text((86, 22), spec["title"], font=TITLE_FONT, fill=WHITE)

    for raw_box, label in spec["highlights"]:
        x1, y1, x2, y2 = raw_box
        shifted = (x1, y1 + HEADER_HEIGHT, x2, y2 + HEADER_HEIGHT)
        draw.rounded_rectangle(shifted, radius=13, outline=ACCENT, width=5)
        label_y = max(HEADER_HEIGHT + 5, shifted[1] - 31)
        add_label(draw, shifted[0], label_y, label)

    OUT.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT / spec["target"], quality=96)


def main() -> None:
    for index, spec in enumerate(STEPS, start=1):
        render_step(index, spec)


if __name__ == "__main__":
    main()

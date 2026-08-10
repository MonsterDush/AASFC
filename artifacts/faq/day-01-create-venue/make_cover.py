from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
BACKGROUND = ROOT / "cover" / "cover-background-v2.png"
SCREENSHOT = ROOT / "raw-local" / "02-venues.png"
LOGO = ROOT.parents[2] / "frontend" / "logo.png"
OUTPUT = ROOT / "cover" / "cover.png"

WIDTH = 1080
HEIGHT = 1350
ACCENT = "#D85A63"
WHITE = "#F4F6FA"
MUTED = "#AEB7C8"
BG = "#080B12"
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size, index=index)


def prepare_logo() -> Image.Image:
    logo = Image.open(LOGO).convert("RGBA")
    pixels = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, _ = pixels[x, y]
            if r > 244 and g > 244 and b > 244:
                pixels[x, y] = (255, 255, 255, 0)
            elif g > r * 1.15 and b > r * 1.15:
                pixels[x, y] = (36, 199, 213, 255)
            else:
                pixels[x, y] = (244, 246, 250, 255)
    logo.thumbnail((58, 58), Image.Resampling.LANCZOS)
    return logo


def rounded_screenshot(source: Image.Image, size: tuple[int, int], radius: int = 24) -> Image.Image:
    screenshot = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    result = Image.new("RGBA", size, (0, 0, 0, 0))
    result.paste(screenshot, (0, 0), mask)
    return result


def main() -> None:
    background = ImageOps.fit(
        Image.open(BACKGROUND).convert("RGB"),
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS,
    ).convert("RGBA")
    draw = ImageDraw.Draw(background)

    logo = prepare_logo()
    background.alpha_composite(logo, (72, 62))
    draw.text((145, 72), "AXELIO", font=font(28, 1), fill=WHITE)

    draw.text((72, 184), "БАЗОВАЯ НАСТРОЙКА", font=font(22, 10), fill=ACCENT)
    draw.rectangle((72, 224, 146, 230), fill=ACCENT)

    title_font = font(78, 1)
    draw.text((72, 264), "КАК СОЗДАТЬ", font=title_font, fill=WHITE)
    draw.text((72, 348), "ЗАВЕДЕНИЕ", font=title_font, fill=WHITE)
    draw.text((74, 465), "Настройки / Управление заведениями", font=font(31), fill=MUTED)

    shot_x, shot_y = 72, 610
    shot_width, shot_height = 936, 387
    shadow = Image.new("RGBA", (shot_width + 48, shot_height + 48), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((24, 18, shot_width + 24, shot_height + 18), radius=28, fill=(0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    background.alpha_composite(shadow, (shot_x - 24, shot_y - 18))

    source_screenshot = Image.open(SCREENSHOT).crop((120, 0, 1160, 430))
    screenshot = rounded_screenshot(source_screenshot, (shot_width, shot_height))
    background.alpha_composite(screenshot, (shot_x, shot_y))
    draw.rounded_rectangle(
        (shot_x, shot_y, shot_x + shot_width, shot_y + shot_height),
        radius=24,
        outline=(216, 90, 99, 210),
        width=3,
    )

    # The red outline points to the actual creation action inside the real local interface.
    scale_x = shot_width / 1040
    scale_y = shot_height / 430
    button_box = (
        shot_x + round((949 - 120) * scale_x),
        shot_y + round(56 * scale_y),
        shot_x + round((1119 - 120) * scale_x),
        shot_y + round(142 * scale_y),
    )
    draw.rounded_rectangle(button_box, radius=12, outline=ACCENT, width=5)

    draw.text((72, 1068), "ВВЕДИТЕ НАЗВАНИЕ — И МОЖНО НАЧИНАТЬ", font=font(24, 10), fill=WHITE)
    draw.rectangle((72, 1114, 1008, 1116), fill=(216, 90, 99, 90))

    background.convert("RGB").save(OUTPUT, quality=97)


if __name__ == "__main__":
    main()

"""ASCII artwork theme."""

from PIL import Image, ImageDraw

from layout import load_theme_font


ASCII_LEVELS = ("W", "#", "%", "?", "*", "+", ";", ":", ",", ".", " ")


def create_ascii_title(title):
    title_image = Image.new("RGBA", (250, 140), (255, 255, 255, 0))
    font = load_theme_font(12)
    drawing = ImageDraw.Draw(title_image)
    horizontal_offset = 80
    line_y = 1
    border = "##############################"

    def text_height(text):
        box = drawing.textbbox((0, 0), text, font=font)
        return box[3] - box[1]

    drawing.text(
        (horizontal_offset, line_y),
        border,
        font=font,
        fill=(128, 255, 128, 255),
    )
    line_y += text_height(border) + 2
    for title_line in title.split(" - "):
        drawing.text(
            (horizontal_offset, line_y),
            "#",
            font=font,
            fill=(128, 255, 128, 255),
        )
        drawing.text(
            (horizontal_offset + 12, line_y),
            title_line,
            font=font,
            fill=(0, 0, 0, 255),
        )
        drawing.text(
            (horizontal_offset + 11, line_y - 1),
            title_line,
            font=font,
            fill=(255, 255, 255, 255),
        )
        line_y += text_height(title_line) + 2
    drawing.text(
        (horizontal_offset, line_y),
        border,
        font=font,
        fill=(128, 255, 128, 255),
    )
    return title_image.resize((1000, 560), Image.Resampling.NEAREST)


def create_ascii_background(icon, _temporary_path=None):
    grayscale = icon.convert("L").resize((120, 120), Image.Resampling.BILINEAR)
    background = Image.new("RGB", (1920, 1080), (0, 0, 0))
    font = load_theme_font(12)
    drawing = ImageDraw.Draw(background)
    for x_position in range(120):
        for y_position in range(120):
            intensity = grayscale.getpixel((x_position, y_position))
            character = ASCII_LEVELS[10 - intensity // 25]
            drawing.text(
                (210 + x_position * 9, y_position * 9),
                character,
                font=font,
                fill=(192, 192, 192, 255),
            )
    return background

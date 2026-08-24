"""Dot painting artwork theme."""

from PIL import Image, ImageDraw

from layout import create_dot_title


def create_dotpainting_title(title):
    return create_dot_title(title, horizontal_offset=80)


def create_dotpainting_background(icon, _temporary_path=None):
    source = icon.resize((120, 120), Image.Resampling.BILINEAR)
    background = Image.new("RGB", (1920, 1080), (0, 0, 0))
    drawing = ImageDraw.Draw(background)
    for x_position in range(120):
        for y_position in range(120):
            pixel = source.getpixel((x_position, y_position))
            drawing.ellipse(
                (
                    (x_position * 9 - 3, y_position * 9 - 3),
                    (x_position * 9 + 4, y_position * 9 + 4),
                ),
                fill=pixel,
            )
    return background

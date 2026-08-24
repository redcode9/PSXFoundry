"""OpenCV-backed artwork themes."""

import cv2
from PIL import Image

from layout import create_dot_title


def create_styled_title(title):
    return create_dot_title(title, horizontal_offset=100)


def _place_artwork(artwork):
    background = Image.new("RGB", (1920, 1080), (0, 0, 0))
    background.paste(artwork, box=(100, 0))
    return background


def create_oil_painting_background(icon, temporary_path):
    resized_icon = icon.resize((1000, 1000), Image.Resampling.BILINEAR)
    resized_icon.save(temporary_path, format="BMP")
    source = cv2.imread(temporary_path, cv2.IMREAD_COLOR)
    result = cv2.xphoto.oilPainting(source, 7, 1)
    cv2.imwrite(temporary_path, result)
    return _place_artwork(Image.open(temporary_path))


def create_watercolor_background(icon, temporary_path):
    resized_icon = icon.resize((1000, 1000), Image.Resampling.BILINEAR)
    resized_icon.save(temporary_path, format="BMP")
    source = cv2.imread(temporary_path, cv2.IMREAD_COLOR)
    result = cv2.stylization(source, sigma_s=60, sigma_r=0.6)
    cv2.imwrite(temporary_path, result)
    return _place_artwork(Image.open(temporary_path))


def create_color_sketch_background(icon, temporary_path):
    icon.save(temporary_path, format="BMP")
    source = cv2.imread(temporary_path, cv2.IMREAD_COLOR)
    _, result = cv2.pencilSketch(
        source,
        sigma_s=150,
        sigma_r=0.20,
        shade_factor=0.02,
    )
    cv2.imwrite(temporary_path, result)
    artwork = Image.open(temporary_path).resize(
        (1000, 1000),
        Image.Resampling.NEAREST,
    )
    return _place_artwork(artwork)

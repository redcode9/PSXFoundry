#!/usr/bin/env python

import sys

from PIL import Image, ImageDraw, ImageFont


def load_theme_font(size):
    font_name = "arial.ttf" if sys.platform == "win32" else "DejaVuSansMono.ttf"
    try:
        return ImageFont.truetype(font_name, size)
    except OSError:
        return ImageFont.load_default()


def create_dot_title(title, horizontal_offset):
    source = Image.new("RGB", (250, 140), (0, 0, 0))
    font = load_theme_font(12)
    drawing = ImageDraw.Draw(source)
    line_y = 1
    border = "##############################"

    def text_height(text):
        box = drawing.textbbox((0, 0), text, font=font)
        return box[3] - box[1]

    drawing.text(
        (horizontal_offset, line_y),
        border,
        font=font,
        fill=(255, 128, 128, 255),
    )
    line_y += text_height(border) + 2
    for title_line in title.split(" - "):
        drawing.text(
            (horizontal_offset, line_y),
            "#",
            font=font,
            fill=(255, 128, 128, 255),
        )
        drawing.text(
            (horizontal_offset + 11, line_y),
            title_line,
            font=font,
            fill=(255, 255, 255, 255),
        )
        line_y += text_height(title_line) + 2
    drawing.text(
        (horizontal_offset, line_y),
        border,
        font=font,
        fill=(255, 128, 128, 255),
    )

    result = Image.new("RGBA", (1000, 560), (255, 255, 255, 0))
    drawing = ImageDraw.Draw(result)
    for x_position in range(250):
        for y_position in range(140):
            pixel = source.getpixel((x_position, y_position))
            if pixel != (0, 0, 0):
                drawing.ellipse(
                    (
                        (x_position * 4, y_position * 4),
                        (x_position * 4 + 3, y_position * 4 + 3),
                    ),
                    fill=pixel,
                )
    return result

def image_has_transparency(image):
    if image.info.get("transparency") is not None:
        return True
    if image.mode == "P":
        transparent = image.info.get("transparency", -1)
        for _, index in image.getcolors():
            if index == transparent:
                return True
    elif image.mode == "RGBA":
        return image.getextrema()[3][0] < 255
    return False


if __name__ == "__main__":
    import argparse
    import importlib

    from gamedb import games

    popfe = importlib.import_module("pop-fe")
    parser = argparse.ArgumentParser()
    parser.add_argument('--gameid', help='Game ID.')
    parser.add_argument('--pic0-scaling', help='Scaing factor to use for PIC0')
    parser.add_argument('--pic0-offset', help='Offset factor to use for PIC0')
    parser.add_argument('files', nargs='*')
    args = parser.parse_args()

    if args.pic0_scaling:
        games[args.gameid]['pic0-scaling'] = float(args.pic0_scaling)
    if args.pic0_offset:
        games[args.gameid]['pic0-offset'] = eval(args.pic0_offset)

    if 'pic0-scaling' in games[args.gameid]:
        print('pic0 scaling:', games[args.gameid]['pic0-scaling'])
    else:
        print('pic0 scaling: DEFAULT 0.9')
        
    if 'pic0-offset' in games[args.gameid]:
        print('pic0 offset:', games[args.gameid]['pic0-offset'])
    else:
        print('pic0 offset: DEFAULT (0.1, 0.1)')
        
    p1 = popfe.get_pic1_from_game(args.gameid, None, 'nothing')
    p0 = popfe.get_pic0_from_game(args.gameid, None, 'nothing')

    # PS3
    pic0 = p0.resize((1000,560), Image.Resampling.LANCZOS)
    pic1 = p1.resize((1920,1080), Image.Resampling.LANCZOS)
    if image_has_transparency(pic0):
        Image.Image.paste(pic1, pic0,
                          box=(760,425,1760,985), mask=pic0)
    else:
        Image.Image.paste(pic1, pic0,
                          box=(760,425,1760,985))

    pic1 = pic1.convert('RGBA')
    img1 = ImageDraw.Draw(pic1)
    img1.rectangle([(760,425),(1760,985)], outline ="red") 
    pic1.show()

    # PSP
    pic0 = p0.resize((280,170), Image.Resampling.LANCZOS)
    pic1 = p1.resize((480,272), Image.Resampling.LANCZOS)
    if image_has_transparency(pic0):
        Image.Image.paste(pic1, pic0,
                          box=(190,100,470,270), mask=pic0)
    else:
        Image.Image.paste(pic1, pic0,
                          box=(190,100,470,270))

    img1 = ImageDraw.Draw(pic1)
    img1.rectangle([(190,100),(470,270)], outline ="red") 
    pic1.show()
    
    # PIC0 at  760, 425   1760, 985
    # ICON at  49, 43      66, 60
    # +        'pic0-scaling': 0.6,
    # +        'pic0-offset': (100,100),
    

import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Cached TrueType fonts for presentation-grade anti-aliased HUD typography
_FONT_PATH_BOLD = "C:\\Windows\\Fonts\\segoeuib.ttf"
_FONT_PATH_REG = "C:\\Windows\\Fonts\\segoeui.ttf"
if not os.path.exists(_FONT_PATH_BOLD):
    _FONT_PATH_BOLD = "C:\\Windows\\Fonts\\arialbd.ttf"
    _FONT_PATH_REG = "C:\\Windows\\Fonts\\arial.ttf"

_FONTS = {}

def get_hud_font(size: int = 12, bold: bool = True) -> ImageFont.ImageFont:
    key = (size, bold)
    if key not in _FONTS:
        try:
            path = _FONT_PATH_BOLD if bold else _FONT_PATH_REG
            _FONTS[key] = ImageFont.truetype(path, size)
        except Exception:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]

def draw_modern_pill_badge(
    img: np.ndarray,
    x: int,
    y: int,
    text: str,
    accent_rgb: tuple = (16, 185, 129),
    bg_rgba: tuple = (10, 15, 24, 215),
    radius: int = 6,
    font_size: int = 12
) -> None:
    """
    Renders an ultra-modern, crisp, anti-aliased rounded glassmorphic pill badge
    using TrueType fonts (Segoe UI / Arial) instead of 1960s vector Hershey strokes.
    """
    font = get_hud_font(size=font_size, bold=True)
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_x = 9
    pad_y = 5
    pill_w = tw + pad_x * 2 + 12
    pill_h = th + pad_y * 2 + 2

    h, w = img.shape[:2]
    x1 = max(0, min(w - pill_w, int(x)))
    y1 = max(0, min(h - pill_h, int(y)))
    x2 = min(w, x1 + pill_w)
    y2 = min(h, y1 + pill_h)

    if x2 <= x1 or y2 <= y1:
        return

    # Extract sub-region
    crop = img[y1:y2, x1:x2]
    pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGBA))

    overlay = Image.new("RGBA", pil_crop.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 1. Rounded glass background + sleek border
    draw.rounded_rectangle(
        [0, 0, pill_w - 1, pill_h - 1],
        radius=radius,
        fill=bg_rgba,
        outline=(*accent_rgb, 230),
        width=1
    )

    # 2. Glowing indicator dot
    dot_cy = pill_h // 2
    draw.ellipse([pad_x - 3, dot_cy - 3, pad_x + 3, dot_cy + 3], fill=(*accent_rgb, 255))

    # 3. Anti-aliased TrueType text
    draw.text((pad_x + 9, pad_y - 1), text, font=font, fill=(255, 255, 255, 255))

    # 4. Composite & put back
    pil_crop = Image.alpha_composite(pil_crop, overlay)
    img[y1:y2, x1:x2] = cv2.cvtColor(np.array(pil_crop), cv2.COLOR_RGBA2BGR)

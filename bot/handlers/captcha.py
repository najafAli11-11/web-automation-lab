import base64
import io
import math
import re

from PIL import Image, ImageDraw

from bot.handlers.locate import first, is_present, all_matches
from bot import selectors as S


def _mse(img_a, img_b):
    pa = list(img_a.getdata())
    pb = list(img_b.getdata())
    return sum((a - b) ** 2 for a, b in zip(pa, pb)) / len(pa)


def _draw_shape(draw, shape, cx, cy, size):
    half = size // 2
    if shape == "circle":
        draw.ellipse([cx - half, cy - half, cx + half, cy + half], outline=0, width=2)
    elif shape == "square":
        draw.rectangle([cx - half, cy - half, cx + half, cy + half], outline=0, width=2)
    elif shape == "triangle":
        draw.polygon([(cx, cy - half), (cx - half, cy + half), (cx + half, cy + half)], outline=0, width=2)
    elif shape == "star":
        pts = []
        for i in range(5):
            angle = i * 72 - 90
            outer_x = cx + int(half * math.cos(math.radians(angle)))
            outer_y = cy + int(half * math.sin(math.radians(angle)))
            pts.append((outer_x, outer_y))
            angle += 36
            inner_x = cx + int(half * 0.4 * math.cos(math.radians(angle)))
            inner_y = cy + int(half * 0.4 * math.sin(math.radians(angle)))
            pts.append((inner_x, inner_y))
        draw.polygon(pts, outline=0, width=2)
    elif shape == "diamond":
        draw.polygon([(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)], outline=0, width=2)
    elif shape == "cross":
        w = max(2, half // 2)
        draw.rectangle([cx - w, cy - half, cx + w, cy + half], outline=0, width=2)
        draw.rectangle([cx - half, cy - w, cx + half, cy + w], outline=0, width=2)
    elif shape == "arrow":
        draw.polygon([(cx - half, cy + half), (cx, cy - half), (cx + half, cy + half)], outline=0, width=2)
        draw.line([(cx, cy - half), (cx, cy)], fill=0, width=2)
    elif shape == "heart":
        r = half // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=2)
        draw.ellipse([cx - r + r // 2, cy - r, cx + r + r // 2, cy + r], outline=0, width=2)
        draw.polygon([(cx - r - 1, cy + r // 2), (cx + r + r // 2 + 1, cy + r // 2), (cx + r // 4, cy + half + 2)], outline=0, width=2)


_SHAPES = ["circle", "square", "triangle", "star", "diamond", "cross", "arrow", "heart"]


def _template(shape, size=70):
    img = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(img)
    _draw_shape(draw, shape, size // 2, size // 2, 36)
    return img


_TEMPLATES = {s: _template(s) for s in _SHAPES}


def _classify(tile_img):
    tile_gray = tile_img.convert("L")
    best_shape = None
    best_score = float("inf")
    for shape, tmpl in _TEMPLATES.items():
        score = _mse(tile_gray, tmpl)
        if score < best_score:
            best_score = score
            best_shape = shape
    return best_shape, best_score


_SHAPE_NAMES = {
    "circle": "a circle", "square": "a square", "triangle": "a triangle",
    "star": "a star", "diamond": "a diamond", "cross": "a cross",
    "arrow": "an arrow", "heart": "a heart",
}
_NAME_TO_SHAPE = {v: k for k, v in _SHAPE_NAMES.items()}


def detect(page):
    return is_present(page, S.CAPTCHA_FORM)


def solve(page, reporter=None):
    tiles = all_matches(page, S.CAPTCHA_TILES)
    if len(tiles) != 9:
        raise ValueError(f"expected 9 grid tiles, got {len(tiles)}")

    body_text = first(page, ["body"]).inner_text()
    target_name = None
    for name in _SHAPE_NAMES.values():
        if name in body_text:
            target_name = name
            break
    if not target_name:
        m = re.search(r"Select all tiles containing\s+(.+?):", body_text)
        if m:
            target_name = m.group(1).strip()
        else:
            raise ValueError(f"could not find target shape in page: {body_text[:200]!r}")
    target_shape = _NAME_TO_SHAPE[target_name]

    tile_imgs = []
    for tile in tiles:
        img_el = tile.locator("img")
        src = img_el.get_attribute("src")
        if not src or not src.startswith("data:image/png;base64,"):
            raise ValueError("tile image not base64")
        b64 = src.split(",", 1)[1]
        data = base64.b64decode(b64)
        img = Image.open(io.BytesIO(data))
        tile_imgs.append(img)

    to_click = []
    for i, img in enumerate(tile_imgs):
        shape, score = _classify(img)
        if shape == target_shape:
            to_click.append(i)

    for idx in to_click:
        tiles[idx].click()

    first(page, S.CAPTCHA_SUBMIT).click()
    page.wait_for_load_state()

    if reporter:
        reporter.log_event(
            "solve_captcha",
            scenario="captcha_gate",
            strategy="template_match",
            outcome="resolved",
            detail={"target": target_shape, "tiles_clicked": to_click},
        )
    return target_shape

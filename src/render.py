"""投稿用の画像カード（1080x1350）を作る。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1080, 1350
BLUE = (85, 170, 223)
DEEP = (36, 120, 190)
PALE = (234, 245, 252)
TEXT = (40, 48, 60)
GRAY = (120, 130, 140)
WHITE = (255, 255, 255)

CARD = (60, 190, 1020, 1190)  # 白いカードの範囲
PAD = 64

FONTS = {
    "bold": [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
        ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 0),
    ],
    "regular": [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
        ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 0),
    ],
}

KICKERS = {"朝": "一緒に働きませんか", "昼": "加盟店オーナーの視点", "夜": "ファンとしての本音"}
HEADER = "とある加盟店オーナーが語る どこでもMUSEE"

# 行頭に来てはいけない文字（前の行にぶら下げる）
NO_LINE_START = set("、。，．・ー」』）)!?！？ぁぃぅぇぉっゃゅょァィゥェォッャュョ％%")

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _font_cache:
        for path, index in FONTS[weight]:
            if Path(path).exists():
                _font_cache[key] = ImageFont.truetype(path, size, index=index)
                break
        else:
            raise FileNotFoundError("日本語フォントが見つかりません（fonts-noto-cjk を入れてください）")
    return _font_cache[key]


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            if line and f.getlength(line + ch) > max_w and ch not in NO_LINE_START:
                lines.append(line)
                line = ch
            else:
                line += ch
        lines.append(line)
    return lines


def fit(text: str, weight: str, size: int, min_size: int, max_w: int, max_lines: int):
    """max_lines に収まるまで文字を小さくする。"""
    while True:
        f = font(weight, size)
        lines = wrap(text, f, max_w)
        if len(lines) <= max_lines or size <= min_size:
            return f, lines[:max_lines]
        size -= 4


def draw_lines(d: ImageDraw.ImageDraw, lines, f, x, y, fill, spacing=1.45, center=False, width=0) -> int:
    lh = int(f.size * spacing)
    for line in lines:
        lx = x + (width - f.getlength(line)) / 2 if center else x
        d.text((lx, y), line, font=f, fill=fill)
        y += lh
    return y


def sparkle(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    k = r * 0.22
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
               (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=fill)


def pill(d: ImageDraw.ImageDraw, text: str, x: int, y: int) -> int:
    f = font("bold", 32)
    w = int(f.getlength(text)) + 56
    d.rounded_rectangle((x, y, x + w, y + 60), radius=30, fill=BLUE)
    d.text((x + 28, y + 10), text, font=f, fill=WHITE)
    return y + 60


def paste_photo(img: Image.Image, photo_path: Path, box) -> None:
    x0, y0, x1, y1 = box
    photo = ImageOps.fit(Image.open(photo_path).convert("RGB"), (x1 - x0, y1 - y0))
    mask = Image.new("L", photo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *photo.size), radius=36, fill=255)
    img.paste(photo, (x0, y0), mask)


def _content(d: ImageDraw.ImageDraw, kind: str, headline: str, body: str,
             x: int, y: int, inner_w: int, bottom: int) -> int:
    """見出しと本文を描き、描き終わりの y を返す。"""
    if kind == "number":
        f, lines = fit(headline, "bold", 150, 80, inner_w, 2)
        y = draw_lines(d, lines, f, x, y, DEEP, spacing=1.2, center=True, width=inner_w) + 20
        bf, blines = fit(body, "bold", 48, 32, inner_w, max(1, (bottom - y) // 70))
        return draw_lines(d, blines, bf, x, y, TEXT, center=True, width=inner_w)
    if kind == "qa":
        qf = font("bold", 64)
        d.text((x, y), "Q.", font=qf, fill=BLUE)
        f, lines = fit(headline, "bold", 56, 40, inner_w - 100, 3)
        y = max(draw_lines(d, lines, f, x + 100, y + 4, TEXT, spacing=1.4), y + 80) + 24
        d.line((x, y, x + inner_w, y), fill=PALE, width=4)
        y += 36
        d.text((x, y), "A.", font=qf, fill=DEEP)
        bf, blines = fit(body, "regular", 42, 30, inner_w - 100, max(1, (bottom - y) // 64))
        return draw_lines(d, blines, bf, x + 100, y + 10, TEXT, spacing=1.6)
    if kind == "voice":
        d.text((x - 8, y - 30), "“", font=font("bold", 160), fill=BLUE)
        y += 90
        f, lines = fit(headline, "bold", 60, 40, inner_w, 5)
        y = draw_lines(d, lines, f, x, y, TEXT, spacing=1.5) + 30
        bf, blines = fit(body, "regular", 36, 28, inner_w, 3)
        return draw_lines(d, blines, bf, x, y, GRAY)
    # message
    f, lines = fit(headline, "bold", 84, 48, inner_w, 4)
    y = draw_lines(d, lines, f, x, y, DEEP, spacing=1.35) + 36
    bf, blines = fit(body, "regular", 44, 30, inner_w, max(1, (bottom - y) // 70))
    return draw_lines(d, blines, bf, x, y, TEXT, spacing=1.6)


def render(kind: str, slot: str, headline: str, body: str, note: str,
           display_name: str = "", photo: Path | None = None) -> Image.Image:
    img = Image.new("RGB", (W, H), PALE)
    d = ImageDraw.Draw(img)

    # ヘッダー
    d.rectangle((0, 0, W, 140), fill=BLUE)
    sparkle(d, 92, 70, 26, WHITE)
    d.text((134, 48), HEADER, font=font("bold", 40), fill=WHITE)

    x0, y0, x1, y1 = CARD
    d.rounded_rectangle(CARD, radius=40, fill=WHITE)
    inner_w = x1 - x0 - PAD * 2
    x = x0 + PAD
    y = y0 + PAD

    if photo is not None and photo.exists():
        paste_photo(img, photo, (x0, y0, x1, y0 + 440))
        y = y0 + 440 + 40

    y = pill(d, KICKERS.get(slot, "どこでもMUSEE"), x, y) + 44

    # 注記はカード下部に固定
    note_f = font("regular", 24)
    note_lines = wrap(note, note_f, inner_w) if note else []
    note_top = y1 - PAD - len(note_lines) * int(24 * 1.45)
    bottom = note_top - 30

    # 一度仮に描いて高さを測り、本文ブロックを上下中央に置く
    scratch = ImageDraw.Draw(Image.new("RGB", (W, H)))
    end = _content(scratch, kind, headline, body, x, y, inner_w, bottom)
    off = max(0, (bottom - end) // 2)
    _content(d, kind, headline, body, x, y + off, inner_w, bottom + off)

    if note_lines:
        draw_lines(d, note_lines, note_f, x, note_top, GRAY)

    if display_name:
        nf = font("bold", 34)
        d.text(((W - nf.getlength(display_name)) / 2, 1240), display_name, font=nf, fill=DEEP)
    return img

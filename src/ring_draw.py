# -*- coding: utf-8 -*-
"""High-DPI antialiased ring renderer (PIL supersampling)."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageTk


def _color_for_pct(pct: float | None) -> tuple[int, int, int]:
    if pct is None:
        return (156, 163, 175)
    if pct >= 95:
        return (239, 68, 68)
    if pct >= 80:
        return (245, 158, 11)
    if pct >= 50:
        return (234, 179, 8)
    return (34, 197, 94)


def render_ring_photo(
    size: int,
    pct: float | None,
    *,
    error: bool = False,
    bg: tuple[int, int, int, int] = (17, 24, 39, 245),
) -> ImageTk.PhotoImage:
    size = max(24, int(size))
    ss = 4  # supersample factor
    big = size * ss
    img = Image.new("RGBA", (big, big), bg)
    draw = ImageDraw.Draw(img)

    pad = max(3, big // 10)
    width = max(4 * ss, big // 8)
    track = (75, 85, 99, 255)
    color = (156, 163, 175, 255) if error else (*_color_for_pct(pct), 255)

    bbox = (pad, pad, big - pad - 1, big - pad - 1)
    draw.arc(bbox, start=0, end=359.99, fill=track, width=width)

    if pct is not None and not error:
        # ImageDraw: 0бу=3 o'clock, positive=clockwise. We want from 12 o'clock clockwise.
        span = max(0.0, min(100.0, pct)) / 100.0 * 360.0
        if span < 0.8:
            span = 0.8
        start = -90
        end = start + span
        draw.arc(bbox, start=start, end=end, fill=color, width=width)

    if error:
        text = "!"
    elif pct is None:
        text = "-"
    elif pct >= 100:
        text = "99+"
    else:
        text = str(int(round(pct)))

    # Smaller + bold; nudge slightly above geometric center.
    font_size = max(8 * ss, big // 4 - (3 * ss if len(text) > 2 else 0))
    font = None
    for name in (
        "segoeuib.ttf",  # Segoe UI Bold
        "SegoeUI-Bold.ttf",
        "arialbd.ttf",
        "segoeui.ttf",
    ):
        try:
            font = ImageFont.truetype(name, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    # textbbox origin can be non-zero; compensate so glyph box is truly centered.
    nudge_up = int(0.8 * ss)  # slight optical lift; keep lower than before
    x = (big - tw) / 2 - bbox[0]
    y = (big - th) / 2 - bbox[1] - nudge_up
    draw.text((x, y), text, fill=(249, 250, 251, 255), font=font)

    out = img.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(out)

# -*- coding: utf-8 -*-
"""Right-click peek card: show the other account's quota near the ring."""

from __future__ import annotations

import ctypes
import tkinter as tk
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageTk

from .ring_draw import color_for_pct
from .usage_api import UsageSnapshot

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_LAYERED = 0x00080000
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
LWA_ALPHA = 0x00000002


@dataclass
class PeekAccount:
    label: str
    snap: UsageSnapshot
    is_current: bool = False


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        ("segoeuib.ttf", "SegoeUI-Bold.ttf", "arialbd.ttf")
        if bold
        else ("segoeui.ttf", "Segoe UI.ttf", "arial.ttf", "msyh.ttc", "msyh.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:.0f}%"


def _draw_mini_ring(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    width: int,
    pct: float | None,
    *,
    error: bool = False,
) -> None:
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    track = (55, 65, 81, 255)
    draw.arc(bbox, 0, 359.99, fill=track, width=width)
    if error or pct is None:
        return
    color = (*color_for_pct(pct), 255)
    span = max(0.8, min(100.0, pct) / 100.0 * 360.0)
    draw.arc(bbox, -90, -90 + span, fill=color, width=width)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def render_peek_card(
    accounts: list[PeekAccount],
    *,
    scale: float = 1.0,
) -> ImageTk.PhotoImage:
    """Compact chip: ring + label / email / plan only."""
    s = max(1.0, min(float(scale), 1.75))
    pad = int(12 * s)
    gap = int(10 * s)
    ring_r = int(30 * s)
    card_w = int(236 * s)

    others = [a for a in accounts if not a.is_current] or accounts[:1]
    acc = others[0]
    snap = acc.snap
    pct = None if snap.error else snap.percent_for("total")
    accent = (239, 68, 68) if snap.error else color_for_pct(pct)

    label_font = _font(int(13 * s), bold=True)
    body_font = _font(int(11 * s))
    # Larger center % so it reads clearly inside the ring.
    pct_font = _font(int(16 * s), bold=True)
    small_font = _font(int(10 * s))

    body_h = ring_r * 2
    card_h = pad * 2 + body_h

    img = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        (2, 3, card_w - 1, card_h - 1),
        radius=int(12 * s),
        fill=(0, 0, 0, 50),
    )
    draw.rounded_rectangle(
        (0, 0, card_w - 2, card_h - 3),
        radius=int(12 * s),
        fill=(15, 23, 42, 250),
        outline=(51, 65, 85, 230),
        width=max(1, int(round(s))),
    )

    y = pad
    cx = pad + ring_r
    cy = y + ring_r
    _draw_mini_ring(
        draw, cx, cy, ring_r - int(2 * s), max(3, int(4 * s)), pct, error=bool(snap.error)
    )

    if snap.error:
        glyph = "!"
    elif pct is None:
        glyph = "-"
    else:
        glyph = str(int(round(pct)))
    # textbbox origin can be non-zero ¡ª compensate for true optical center.
    bbox = draw.textbbox((0, 0), glyph, font=pct_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx_num = cx - tw / 2 - bbox[0]
    ty_num = cy - th / 2 - bbox[1]
    draw.text((tx_num, ty_num), glyph, font=pct_font, fill=(248, 250, 252, 255))

    tx = pad + ring_r * 2 + gap
    draw.text((tx, y + int(4 * s)), acc.label or "account", font=label_font, fill=(248, 250, 252, 255))
    email = (snap.email or "").strip() or "(no email)"
    if len(email) > 22:
        email = email[:19] + "..."
    draw.text((tx, y + int(24 * s)), email, font=body_font, fill=(148, 163, 184, 255))
    plan = (snap.plan or "").strip() or "-"
    plan_tag = f" {plan} "
    pw, ph = _text_size(draw, plan_tag, small_font)
    tag_x, tag_y = tx, y + int(44 * s)
    draw.rounded_rectangle(
        (tag_x, tag_y, tag_x + pw + int(8 * s), tag_y + ph + int(4 * s)),
        radius=int(5 * s),
        fill=(30, 41, 59, 255),
    )
    draw.text((tag_x + int(4 * s), tag_y + int(1 * s)), plan_tag, font=small_font, fill=(*accent, 255))

    return ImageTk.PhotoImage(img)


class AccountPeekPopup:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._win: tk.Toplevel | None = None
        self._photo = None
        self._leave_after: str | None = None
        self._visible = False
        self._hover_ring = False
        self._hover_peek = False

    @property
    def visible(self) -> bool:
        return self._visible

    def _cancel_leave(self) -> None:
        if self._leave_after is not None:
            try:
                self.root.after_cancel(self._leave_after)
            except Exception:
                pass
            self._leave_after = None

    def notify_ring_enter(self) -> None:
        self._hover_ring = True
        self._cancel_leave()

    def notify_ring_leave(self) -> None:
        self._hover_ring = False
        self._schedule_hide()

    def _on_peek_enter(self, _event=None) -> None:
        self._hover_peek = True
        self._cancel_leave()

    def _on_peek_leave(self, _event=None) -> None:
        self._hover_peek = False
        self._schedule_hide()

    def _schedule_hide(self) -> None:
        self._cancel_leave()
        self._leave_after = self.root.after(120, self._hide_if_away)

    def _hide_if_away(self) -> None:
        self._leave_after = None
        if not self._hover_ring and not self._hover_peek:
            self.hide()

    def hide(self) -> None:
        self._visible = False
        self._hover_peek = False
        self._cancel_leave()
        if self._win is not None:
            try:
                self._win.withdraw()
            except tk.TclError:
                pass

    def show(
        self,
        *,
        anchor_x: int,
        anchor_y: int,
        anchor_size: int,
        accounts: list[PeekAccount],
        scale: float = 1.0,
    ) -> None:
        if not accounts:
            return
        self._photo = render_peek_card(accounts, scale=scale)

        if self._win is None:
            self._win = tk.Toplevel(self.root)
            self._win.title("CUR-USAGE-PEEK")
            self._win.overrideredirect(True)
            self._win.configure(bg="#0f172a")
            self._label = tk.Label(self._win, bd=0, highlightthickness=0, bg="#0f172a")
            self._label.pack(fill="both", expand=True)
            self._label.bind("<Enter>", self._on_peek_enter)
            self._label.bind("<Leave>", self._on_peek_leave)
            self._win.bind("<Enter>", self._on_peek_enter)
            self._win.bind("<Leave>", self._on_peek_leave)
            self._label.bind("<Button-1>", lambda _e: self.hide())
            self._win.bind("<Escape>", lambda _e: self.hide())

        self._label.configure(image=self._photo)
        self._win.update_idletasks()
        w = self._photo.width()
        h = self._photo.height()

        x = int(anchor_x + anchor_size + 8)
        y = int(anchor_y + (anchor_size - h) // 2)
        try:
            sw = int(self.root.winfo_screenwidth())
            sh = int(self.root.winfo_screenheight())
        except tk.TclError:
            sw, sh = 1920, 1080
        if x + w > sw - 8:
            x = int(anchor_x - w - 8)
        if y < 8:
            y = 8
        if y + h > sh - 8:
            y = max(8, sh - h - 8)

        self._win.geometry(f"{w}x{h}+{x}+{y}")
        try:
            self._win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._win.deiconify()
        self._win.update_idletasks()

        hwnd = int(user32.GetParent(int(self._win.winfo_id())) or self._win.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)

        self._visible = True
        self._hover_ring = True
        self._cancel_leave()

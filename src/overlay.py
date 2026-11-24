# -*- coding: utf-8 -*-
"""Screen-space overlays (Electron rejects SetParent children)."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import tkinter as tk

from .ring_draw import render_ring_photo
from .usage_api import UsageSnapshot
from .windows_track import CursorWindow

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


def _norm_dir(path: str) -> str:
    try:
        return str(Path(os.path.expandvars(path)).resolve()).lower()
    except OSError:
        return path.replace("/", "\\").lower()


class RingOverlay:
    def __init__(self, root: tk.Tk, *, click_through: bool) -> None:
        self.click_through = click_through
        self.size = 40
        self._photo = None

        self.win = tk.Toplevel(root)
        self.win.title("CUR-USAGE-RING")
        self.win.overrideredirect(True)
        self.win.configure(bg="#111827")
        self.label = tk.Label(self.win, bd=0, highlightthickness=0, bg="#111827")
        self.label.pack(fill="both", expand=True)

        self.win.update_idletasks()
        self._hwnd = int(user32.GetParent(int(self.win.winfo_id())) or self.win.winfo_id())
        self._apply_styles()
        self.hide()

    def _apply_styles(self) -> None:
        style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED
        if self.click_through:
            style |= WS_EX_TRANSPARENT
        user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)

    def hide(self) -> None:
        self.win.withdraw()

    def show_at(self, x: int, y: int, size: int) -> None:
        self.size = int(size)
        # Force mapped before SetWindowPos
        self.win.deiconify()
        self.win.geometry(f"{self.size}x{self.size}+{int(x)}+{int(y)}")
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.win.update_idletasks()
        user32.SetWindowPos(
            self._hwnd,
            HWND_TOPMOST,
            int(x),
            int(y),
            int(self.size),
            int(self.size),
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        user32.ShowWindow(self._hwnd, 4)  # SW_SHOWNOACTIVATE

    def render(self, snap: UsageSnapshot | None, metric: str = "total") -> None:
        pct = snap.percent_for(metric) if snap and not snap.error else None
        err = bool(snap and snap.error)
        self._photo = render_ring_photo(self.size, pct, error=err)
        self.label.configure(image=self._photo)


class OverlayManager:
    def __init__(
        self,
        root: tk.Tk,
        *,
        overlay_size: int,
        activity_bar_width: int,
        bottom_offset: int,
        click_through: bool,
        metric: str,
        foreground_only: bool = True,
    ) -> None:
        self.root = root
        self.overlay_size = overlay_size
        self.activity_bar_width = activity_bar_width
        self.bottom_offset = bottom_offset
        self.metric = metric
        # Default True: two maximized Cursor windows share screen coords.
        self.foreground_only = foreground_only
        self._click_through = click_through
        self._overlay: RingOverlay | None = None

    def sync(
        self,
        windows: list[CursorWindow],
        usage_by_dir: dict[str, UsageSnapshot],
        foreground_hwnd: int | None = None,
    ) -> None:
        visible = [w for w in windows if w.visible_client]
        if not visible:
            if self._overlay:
                self._overlay.hide()
            return

        target: CursorWindow | None = None
        if self.foreground_only:
            if foreground_hwnd:
                target = next((w for w in visible if w.hwnd == foreground_hwnd), None)
            if target is None:
                # No Cursor focused — hide, don't show stale/wrong account.
                if self._overlay:
                    self._overlay.hide()
                return
        else:
            target = visible[0]

        if self._overlay is None:
            self._overlay = RingOverlay(self.root, click_through=self._click_through)

        scale = target.dpi / 96.0
        size = max(36, int(round(self.overlay_size * scale)))
        bar_w = max(size + 4, int(round(self.activity_bar_width * scale)))
        bottom = int(round(self.bottom_offset * scale))

        x = target.client_left + max(0, (bar_w - size) // 2)
        y = target.client_top + max(0, target.client_height - bottom - size)

        key = _norm_dir(target.user_data_dir)
        raw = target.user_data_dir.replace("/", "\\").lower()
        snap = usage_by_dir.get(key) or usage_by_dir.get(raw)

        self._overlay.size = size
        self._overlay.render(snap, self.metric)
        self._overlay.show_at(x, y, size)

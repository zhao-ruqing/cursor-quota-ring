# -*- coding: utf-8 -*-
"""Screen-space overlays (Electron rejects SetParent children)."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import tkinter as tk

from .peek_popup import AccountPeekPopup, PeekAccount
from .ring_draw import render_ring_photo
from .usage_api import UsageSnapshot
from .windows_track import (
    CursorWindow,
    foreground_hwnd,
    is_cursor_exposed,
    monitor_id,
    root_hwnd,
    window_owns_foreground,
    _is_cursor_pid,
    _window_title,
    user32,
)

user32_raw = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
LWA_ALPHA = 0x00000002


def _norm_dir(path: str) -> str:
    try:
        return str(Path(os.path.expandvars(path)).resolve()).lower()
    except OSError:
        return path.replace("/", "\\").lower()


class RingOverlay:
    def __init__(
        self,
        root: tk.Tk,
        *,
        click_through: bool,
        on_right_click=None,
        on_enter=None,
        on_leave=None,
    ) -> None:
        self.click_through = click_through
        self.on_right_click = on_right_click
        self.on_enter = on_enter
        self.on_leave = on_leave
        self.size = 40
        self._photo = None
        self._last_pct: float | None | object = object()
        self._last_err = False
        self._last_size = -1
        self._pos: tuple[int, int, int] | None = None  # x, y, size
        self._mode: str | None = None  # "agents" | "editor"
        self._mapped = False
        self.current_key: str = ""
        self.current_snap: UsageSnapshot | None = None
        self.dpi_scale: float = 1.0

        self.win = tk.Toplevel(root)
        self.win.title("CUR-USAGE-RING")
        self.win.overrideredirect(True)
        self.win.configure(bg="#111827")
        self.label = tk.Label(self.win, bd=0, highlightthickness=0, bg="#111827", cursor="hand2")
        self.label.pack(fill="both", expand=True)

        if not click_through:
            # ButtonRelease is more reliable with WS_EX_NOACTIVATE topmost windows.
            self.label.bind("<ButtonRelease-3>", self._handle_right_click)
            self.win.bind("<ButtonRelease-3>", self._handle_right_click)
            self.label.bind("<Button-3>", self._handle_right_click)
            self.win.bind("<Button-3>", self._handle_right_click)
            self.label.bind("<Enter>", self._handle_enter)
            self.win.bind("<Enter>", self._handle_enter)
            self.label.bind("<Leave>", self._handle_leave)
            self.win.bind("<Leave>", self._handle_leave)

        # Withdrawn until we have a real screen position (avoids 0,0 flash).
        self.win.withdraw()
        self.win.update_idletasks()
        self._hwnd = 0
        self._refresh_hwnd()
        self._apply_styles()

    def _handle_right_click(self, _event=None) -> None:
        if self.on_right_click:
            self.on_right_click(self)

    def _handle_enter(self, _event=None) -> None:
        if self.on_enter:
            self.on_enter(self)

    def _handle_leave(self, _event=None) -> None:
        if self.on_leave:
            self.on_leave(self)

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def _refresh_hwnd(self) -> int:
        try:
            wid = int(self.win.winfo_id())
        except tk.TclError:
            return self._hwnd
        parent = int(user32_raw.GetParent(wid) or 0)
        self._hwnd = parent or wid
        return self._hwnd

    def _apply_styles(self) -> None:
        hwnd = self._refresh_hwnd()
        if not hwnd:
            return
        style = user32_raw.GetWindowLongW(hwnd, GWL_EXSTYLE)
        # NOACTIVATE: clicks must not steal focus from Cursor (or ring would hide).
        style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED
        if self.click_through:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32_raw.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        # WS_EX_LAYERED without an alpha makes the window invisible on Win10/11.
        user32_raw.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)

    def _set_pos(self, x: int, y: int, size: int) -> None:
        """Move/show via Tk geometry first, then pin with Win32 (correct hwnd)."""
        try:
            self.win.geometry(f"{size}x{size}+{x}+{y}")
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        if not self._mapped:
            try:
                self.win.deiconify()
            except tk.TclError:
                pass
        try:
            self.win.update_idletasks()
        except tk.TclError:
            pass

        hwnd = self._refresh_hwnd()
        self._apply_styles()
        flags = SWP_NOACTIVATE | SWP_SHOWWINDOW
        if hwnd:
            user32_raw.SetWindowPos(hwnd, HWND_TOPMOST, x, y, size, size, flags)
            user32_raw.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            user32_raw.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
        try:
            wid = int(self.win.winfo_id())
        except tk.TclError:
            wid = 0
        if wid and wid != hwnd:
            user32_raw.SetWindowPos(wid, HWND_TOPMOST, x, y, size, size, flags)
            user32_raw.SetLayeredWindowAttributes(wid, 0, 255, LWA_ALPHA)
        self._mapped = True

    def hide(self) -> None:
        self._mapped = False
        self._pos = None
        try:
            self.win.withdraw()
        except tk.TclError:
            pass

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def show_at(self, x: int, y: int, size: int, *, mode: str | None = None) -> None:
        x, y, size = int(x), int(y), int(size)
        if mode is not None:
            self._mode = mode
        self.size = size
        # Always re-apply position. Skipping caused stale agent/editor offsets
        # when the focused Cursor window changed but coords looked "unchanged".
        self._pos = (x, y, size)
        self._set_pos(x, y, size)

    def render(self, snap: UsageSnapshot | None, metric: str = "total") -> None:
        pct = snap.percent_for(metric) if snap and not snap.error else None
        err = bool(snap and snap.error)
        if pct == self._last_pct and err == self._last_err and self.size == self._last_size:
            return
        self._last_pct = pct
        self._last_err = err
        self._last_size = self.size
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
        foreground_only: bool = False,
        agents_bottom_offset: int | None = None,
    ) -> None:
        self.root = root
        self.overlay_size = overlay_size
        self.activity_bar_width = activity_bar_width
        self.bottom_offset = bottom_offset
        self.agents_bottom_offset = (
            bottom_offset - 200 if agents_bottom_offset is None else int(agents_bottom_offset)
        )
        self.metric = metric
        # True = only the focused Cursor window.
        # False = every Cursor window that should stay pinned (dual-monitor friendly).
        self.foreground_only = foreground_only
        self._click_through = click_through
        # One overlay per monitor — reuse when switching editor <-> Agents (no flash).
        self._overlays: dict[int, RingOverlay] = {}
        self._usage_by_dir: dict[str, UsageSnapshot] = {}
        self._account_meta: list[tuple[str, str]] = []  # (normalized_dir, label)
        self._peek = AccountPeekPopup(root)
        self._sticky_hwnds: list[int] = []

    @staticmethod
    def _is_our_ui(hwnd: int) -> bool:
        """Ring / peek / root Tk — clicking these must not count as leaving Cursor."""
        if not hwnd:
            return False
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) == os.getpid():
            return True
        title = (_window_title(root_hwnd(hwnd)) or _window_title(hwnd) or "").lower()
        return "cur-usage" in title or "cursor-quota-ring" in title

    def _overlay_skip_hwnds(self) -> set[int]:
        skip: set[int] = set()
        for ov in self._overlays.values():
            if ov.hwnd:
                skip.add(ov.hwnd)
        try:
            if self._peek.visible and self._peek._win is not None:
                peek_hwnd = int(
                    user32_raw.GetParent(int(self._peek._win.winfo_id()))
                    or self._peek._win.winfo_id()
                )
                if peek_hwnd:
                    skip.add(peek_hwnd)
        except Exception:
            pass
        return skip

    def _should_show_on(
        self,
        target: CursorWindow,
        fg: int,
        fg_is_cursor: bool,
        fg_is_ours: bool,
        *,
        skip_hwnds: set[int] | None = None,
    ) -> bool:
        """Show on Cursor; hide when another app covers it (even if focus is elsewhere)."""
        if self.foreground_only:
            return bool(fg) and root_hwnd(fg) == target.hwnd

        # Clicking our ring/peek must not hide the overlay.
        if fg_is_ours:
            return True

        # This Cursor frame has focus (or a child does) — always show.
        # Needed because always-on-top widgets (weather, etc.) can sit above
        # Cursor in z-order while Cursor still owns the foreground.
        if fg_is_cursor and window_owns_foreground(target.hwnd, fg):
            return True

        # Focus is elsewhere: only show if Cursor is still the front app on
        # its own monitor (dual-screen). If a browser/etc. covers it, hide.
        return is_cursor_exposed(target.hwnd, skip_hwnds=skip_hwnds)

    @staticmethod
    def _same_screen_slot(a: CursorWindow, b: CursorWindow) -> bool:
        return (
            abs(a.client_left - b.client_left) < 48
            and abs(a.client_top - b.client_top) < 48
            and abs(a.client_width - b.client_width) < 96
            and abs(a.client_height - b.client_height) < 96
        )

    @staticmethod
    def _z_topmost(wins: list[CursorWindow]) -> CursorWindow:
        """Return the highest z-order window among wins (front-most)."""
        if len(wins) == 1:
            return wins[0]
        want = {w.hwnd: w for w in wins}
        # GW_HWNDFIRST from any hwnd, then GW_HWNDNEXT — top → bottom.
        GW_HWNDFIRST = 0
        GW_HWNDNEXT = 2
        cur = int(user32.GetWindow(wins[0].hwnd, GW_HWNDFIRST) or 0)
        seen = 0
        while cur and seen < 4096:
            if cur in want:
                return want[cur]
            cur = int(user32.GetWindow(cur, GW_HWNDNEXT) or 0)
            seen += 1
        # Fallback: EnumWindows order already topmost-first.
        return wins[0]

    @staticmethod
    def _pick_on_monitor(
        wins: list[CursorWindow],
        *,
        fg_hwnd: int,
        fg_is_cursor: bool,
    ) -> CursorWindow:
        """Pick editor vs Agents for one monitor."""
        if not wins:
            raise ValueError("wins empty")
        if len(wins) == 1:
            return wins[0]

        stacked = all(
            OverlayManager._same_screen_slot(wins[0], w) for w in wins[1:]
        )
        # Maximized editor + Agents share one rect. Focus often stays on the
        # buried editor while Agents is what you actually see — always follow
        # front-most z-order for stacked windows.
        if stacked:
            return OverlayManager._z_topmost(wins)

        # Not stacked (side-by-side / different sizes): ownership first, else z-order.
        if fg_is_cursor and fg_hwnd:
            owners = [w for w in wins if window_owns_foreground(w.hwnd, fg_hwnd)]
            if owners:
                fg_root = root_hwnd(fg_hwnd)
                exact = next((w for w in owners if w.hwnd == fg_root), None)
                return exact or owners[0]
        return OverlayManager._z_topmost(wins)

    def _targets(
        self,
        visible: list[CursorWindow],
        foreground_cursor: int | None,
    ) -> list[CursorWindow]:
        fg = foreground_hwnd()
        fg_pid = ctypes.wintypes.DWORD()
        fg_is_cursor = False
        fg_is_ours = False
        if fg:
            user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
            fg_is_cursor = _is_cursor_pid(int(fg_pid.value))
            fg_is_ours = self._is_our_ui(fg)

        if self.foreground_only:
            if not foreground_cursor:
                return []
            hit = next((w for w in visible if w.hwnd == foreground_cursor), None)
            return [hit] if hit else []

        skip_hwnds = self._overlay_skip_hwnds()

        # Group by monitor; keep EnumWindows order (= z-order, topmost first).
        by_mon: dict[int, list[CursorWindow]] = {}
        for w in visible:
            if not self._should_show_on(
                w, fg, fg_is_cursor, fg_is_ours, skip_hwnds=skip_hwnds
            ):
                continue
            mon = monitor_id(w.hwnd) or self._slot_fallback(w)
            by_mon.setdefault(mon, []).append(w)

        targets: list[CursorWindow] = []
        for _mon, wins in by_mon.items():
            targets.append(
                self._pick_on_monitor(
                    wins,
                    fg_hwnd=fg,
                    fg_is_cursor=fg_is_cursor,
                )
            )

        if targets:
            self._sticky_hwnds = [t.hwnd for t in targets]
            return targets

        # Clicking our UI can briefly clear targets — keep last Cursor hwnds (fresh objs).
        if fg_is_ours and self._sticky_hwnds:
            sticky = set(self._sticky_hwnds)
            kept = [w for w in visible if w.hwnd in sticky]
            if kept:
                return kept
        return []
    @staticmethod
    def _slot_fallback(w: CursorWindow) -> int:
        # Stable-ish key when MonitorFromWindow fails.
        return hash((w.client_left // 50, w.client_top // 50)) & 0x7FFFFFFF

    def _place(self, target: CursorWindow) -> tuple[int, int, int, str]:
        scale = target.dpi / 96.0
        size = max(36, int(round(self.overlay_size * scale)))
        bar_w = max(size + 4, int(round(self.activity_bar_width * scale)))
        mode = "agents" if target.is_agents else "editor"
        base_bottom = self.agents_bottom_offset if target.is_agents else self.bottom_offset
        bottom = int(round(base_bottom * scale))

        x = target.client_left + max(0, (bar_w - size) // 2)
        y = target.client_top + target.client_height - bottom - size
        y = min(max(y, target.client_top), target.client_top + max(0, target.client_height - size))
        return x, y, size, mode

    def set_accounts(self, accounts: list[tuple[str, str]]) -> None:
        """accounts: list of (normalized_user_data_dir, label)."""
        self._account_meta = [( _norm_dir(d), label) for d, label in accounts]

    def _lookup_snap(self, key: str) -> UsageSnapshot | None:
        nk = _norm_dir(key)
        hit = self._usage_by_dir.get(nk)
        if hit is not None:
            return hit
        for k, snap in self._usage_by_dir.items():
            if _norm_dir(k) == nk:
                return snap
        return None

    def _peek_accounts(self, current_key: str) -> list[PeekAccount]:
        cur = _norm_dir(current_key) if current_key else ""
        out: list[PeekAccount] = []
        seen: set[str] = set()
        for key, label in self._account_meta:
            nk = _norm_dir(key)
            if nk in seen:
                continue
            seen.add(nk)
            snap = self._lookup_snap(nk)
            if snap is None:
                continue
            out.append(
                PeekAccount(
                    label=label or snap.label or "account",
                    snap=snap,
                    is_current=(bool(cur) and nk == cur),
                )
            )
        if not out:
            for key, snap in list(self._usage_by_dir.items()):
                nk = _norm_dir(key)
                if nk in seen:
                    continue
                seen.add(nk)
                out.append(
                    PeekAccount(
                        label=snap.label or "account",
                        snap=snap,
                        is_current=(bool(cur) and nk == cur),
                    )
                )
        return out

    def _on_ring_right_click(self, ov: RingOverlay) -> None:
        if self._click_through:
            return

        def _show() -> None:
            try:
                accounts = self._peek_accounts(ov.current_key)
                others = [a for a in accounts if not a.is_current]
                if not others:
                    others = list(accounts)
                if not others:
                    return
                ordered = others + [a for a in accounts if a.is_current]
                if not ov._pos:
                    return
                x, y, size = ov._pos
                # Always show (don't toggle-off on the same click that opens).
                self._peek.show(
                    anchor_x=x,
                    anchor_y=y,
                    anchor_size=size,
                    accounts=ordered,
                    scale=max(1.0, ov.dpi_scale),
                )
            except Exception:
                pass

        # Defer so the click finishes before we map the peek window.
        self.root.after(10, _show)

    def _on_ring_enter(self, _ov: RingOverlay) -> None:
        self._peek.notify_ring_enter()

    def _on_ring_leave(self, _ov: RingOverlay) -> None:
        self._peek.notify_ring_leave()

    def sync(
        self,
        windows: list[CursorWindow],
        usage_by_dir: dict[str, UsageSnapshot],
        foreground_hwnd_cursor: int | None = None,
    ) -> None:
        self._usage_by_dir = usage_by_dir
        visible = [w for w in windows if w.visible_client]
        targets = self._targets(visible, foreground_hwnd_cursor)

        active: set[int] = set()
        for target in targets:
            mon = monitor_id(target.hwnd) or self._slot_fallback(target)
            ov = self._overlays.get(mon)
            if ov is None:
                ov = RingOverlay(
                    self.root,
                    click_through=self._click_through,
                    on_right_click=self._on_ring_right_click,
                    on_enter=self._on_ring_enter,
                    on_leave=self._on_ring_leave,
                )
                self._overlays[mon] = ov

            x, y, size, mode = self._place(target)
            key = _norm_dir(target.user_data_dir)
            raw = target.user_data_dir.replace("/", "\\").lower()
            snap = usage_by_dir.get(key) or usage_by_dir.get(raw)

            ov.current_key = key
            ov.current_snap = snap
            ov.dpi_scale = target.dpi / 96.0
            # Render before mapping so first paint already has the ring image.
            ov.size = size
            ov.render(snap, self.metric)
            ov.show_at(x, y, size, mode=mode)
            active.add(mon)

        for mon in list(self._overlays.keys()):
            if mon not in active:
                # Hide+reuse instead of destroy — avoids create flash on next show.
                self._overlays[mon].hide()
        # Never auto-dismiss peek here — click/Escape/timeout owns that.

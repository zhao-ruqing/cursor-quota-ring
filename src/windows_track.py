# -*- coding: utf-8 -*-
"""Track Cursor windows without spawning PowerShell."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.ClientToScreen.restype = wt.BOOL
user32.IsIconic.argtypes = [wt.HWND]
user32.IsIconic.restype = wt.BOOL
user32.GetDpiForWindow.argtypes = [wt.HWND]
user32.GetDpiForWindow.restype = ctypes.c_uint
user32.GetForegroundWindow.restype = wt.HWND
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.MonitorFromWindow.restype = wt.HMONITOR
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.IsChild.argtypes = [wt.HWND, wt.HWND]
user32.IsChild.restype = wt.BOOL

MONITOR_DEFAULTTONEAREST = 2
GA_ROOT = 2

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
ProcessBasicInformation = 0
ProcessCommandLineInformation = 60

_proc_cache: dict[int, tuple[str, int]] = {}
_proc_cache_at = 0.0
_PROC_CACHE_TTL = 8.0


def is_agents_title(title: str) -> bool:
    t = (title or "").lower()
    return "agents" in t


@dataclass(frozen=True)
class CursorWindow:
    hwnd: int
    pid: int
    title: str
    user_data_dir: str
    left: int
    top: int
    right: int
    bottom: int
    client_left: int
    client_top: int
    client_width: int
    client_height: int
    dpi: int
    is_agents: bool = False

    @property
    def visible_client(self) -> bool:
        return (
            self.client_width > 0
            and self.client_height > 0
            and not user32.IsIconic(wt.HWND(self.hwnd))
        )

    @property
    def client_right(self) -> int:
        return self.client_left + self.client_width

    @property
    def client_bottom(self) -> int:
        return self.client_top + self.client_height


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


class _PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.POINTER(ctypes.c_ulong)),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
    ]


def enable_dpi_awareness() -> None:
    try:
        # Per-monitor v2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass


def _process_image_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        fn = kernel32.QueryFullProcessImageNameW
        fn.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        fn.restype = wt.BOOL
        if fn(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _is_cursor_pid(pid: int) -> bool:
    return "cursor.exe" in _process_image_name(pid).lower().replace("/", "\\")


def _command_line(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wt.DWORD(0)
        ntdll.NtQueryInformationProcess(handle, ProcessCommandLineInformation, None, 0, ctypes.byref(size))
        if size.value == 0:
            return ""
        buf = ctypes.create_string_buffer(size.value)
        status = ntdll.NtQueryInformationProcess(
            handle, ProcessCommandLineInformation, buf, size.value, ctypes.byref(size)
        )
        if status != 0:
            return ""
        us = _UNICODE_STRING.from_buffer_copy(buf.raw[: ctypes.sizeof(_UNICODE_STRING)])
        if not us.Buffer or us.Length == 0:
            return ""
        return ctypes.wstring_at(us.Buffer, max(0, us.Length // 2))
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _parent_pid(pid: int) -> int:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0
    try:
        info = _PROCESS_BASIC_INFORMATION()
        status = ntdll.NtQueryInformationProcess(
            handle, ProcessBasicInformation, ctypes.byref(info), ctypes.sizeof(info), None
        )
        if status != 0:
            return 0
        return int(info.InheritedFromUniqueProcessId or 0)
    except Exception:
        return 0
    finally:
        kernel32.CloseHandle(handle)


def _refresh_proc_cache(force: bool = False) -> None:
    global _proc_cache, _proc_cache_at
    now = time.monotonic()
    if not force and _proc_cache and (now - _proc_cache_at) < _PROC_CACHE_TTL:
        return

    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wt.BOOL
    kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wt.BOOL

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid = ctypes.c_void_p(-1).value
    if snap is None or int(snap) == int(invalid):
        return
    cache: dict[int, tuple[str, int]] = {}
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if (entry.szExeFile or "").lower() == "cursor.exe":
                pid = int(entry.th32ProcessID)
                cache[pid] = (_command_line(pid), int(entry.th32ParentProcessID))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    _proc_cache = cache
    _proc_cache_at = now


def _user_data_dir_from_cmd(cmd: str) -> str | None:
    if not cmd:
        return None
    for marker in ("--user-data-dir=", "--user-data-dir "):
        idx = cmd.lower().find(marker.lower())
        if idx < 0:
            continue
        rest = cmd[idx + len(marker) :].lstrip()
        if rest.startswith('"'):
            end = rest.find('"', 1)
            if end > 1:
                return rest[1:end]
        else:
            return rest.split(" ", 1)[0]
    return None


def _cursor_root_pid(pid: int) -> int:
    """Walk up while still inside Cursor.exe; stop before explorer/etc."""
    cur = pid
    last = pid
    seen: set[int] = set()
    while cur and cur not in seen:
        seen.add(cur)
        if not _is_cursor_pid(cur):
            break
        last = cur
        cached = _proc_cache.get(cur)
        cur = cached[1] if cached else _parent_pid(cur)
    return last


def _resolve_user_data_dir(pid: int) -> str:
    """Resolve user-data-dir only within this Cursor instance (never across explorer)."""
    root = _cursor_root_pid(pid)

    # 1) Walk this window's Cursor ancestors.
    cur = pid
    seen: set[int] = set()
    while cur and cur not in seen:
        seen.add(cur)
        if not _is_cursor_pid(cur):
            break
        cached = _proc_cache.get(cur)
        cmd = cached[0] if cached else _command_line(cur)
        udd = _user_data_dir_from_cmd(cmd)
        if udd:
            return os.path.normpath(udd)
        if cur == root:
            break
        cur = cached[1] if cached else _parent_pid(cur)

    # 2) Any Cursor process belonging to the same Cursor root instance.
    for other_pid, (cmd, parent) in _proc_cache.items():
        if _cursor_root_pid(other_pid) != root:
            continue
        udd = _user_data_dir_from_cmd(cmd)
        if udd:
            return os.path.normpath(udd)

    # 3) Default profile
    return os.path.normpath(os.path.join(os.environ.get("APPDATA", ""), "Cursor"))


def _window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(wt.HWND(hwnd))
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(wt.HWND(hwnd), buf, n + 1)
    return buf.value


def _is_main_cursor_window(title: str) -> bool:
    if not title:
        return False
    t = title.lower()
    # Include editor + Agents windows; skip Chromium/IME chrome only.
    skip = ("devtools", "gpu", "crashpad", "msctfime", "default ime")
    if any(s in t for s in skip):
        return False
    return "cursor" in t


def discover_cursor_windows() -> list[CursorWindow]:
    _refresh_proc_cache()
    found: list[CursorWindow] = []

    @EnumWindowsProc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        title = _window_title(int(hwnd))
        if not _is_main_cursor_window(title):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not _is_cursor_pid(int(pid.value)):
            return True

        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        client = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(client))
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))

        try:
            dpi = int(user32.GetDpiForWindow(hwnd)) or 96
        except Exception:
            dpi = 96

        found.append(
            CursorWindow(
                hwnd=int(hwnd),
                pid=int(pid.value),
                title=title,
                user_data_dir=_resolve_user_data_dir(int(pid.value)),
                left=int(rect.left),
                top=int(rect.top),
                right=int(rect.right),
                bottom=int(rect.bottom),
                client_left=int(pt.x),
                client_top=int(pt.y),
                client_width=int(client.right - client.left),
                client_height=int(client.bottom - client.top),
                dpi=dpi,
                is_agents=is_agents_title(title),
            )
        )
        return True

    user32.EnumWindows(callback, 0)
    return found


def monitor_id(hwnd: int) -> int:
    """Stable handle id for the monitor containing hwnd (0 if unknown)."""
    if not hwnd:
        return 0
    try:
        return int(user32.MonitorFromWindow(wt.HWND(hwnd), MONITOR_DEFAULTTONEAREST) or 0)
    except Exception:
        return 0


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def root_hwnd(hwnd: int) -> int:
    if not hwnd:
        return 0
    try:
        root = int(user32.GetAncestor(wt.HWND(hwnd), GA_ROOT) or 0)
        return root or hwnd
    except Exception:
        return hwnd


def window_owns_foreground(hwnd: int, fg: int | None = None) -> bool:
    """True if fg is this top-level window or one of its descendants."""
    if not hwnd:
        return False
    if fg is None:
        fg = foreground_hwnd()
    if not fg:
        return False
    if int(fg) == int(hwnd):
        return True
    if root_hwnd(fg) == int(hwnd):
        return True
    try:
        if user32.IsChild(wt.HWND(hwnd), wt.HWND(fg)):
            return True
    except Exception:
        pass
    return False


def foreground_cursor_hwnd() -> int | None:
    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        return None
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not _is_cursor_pid(int(pid.value)):
        return None
    # Prefer the top-level frame (editor or Agents), not an inner Chromium child.
    root = root_hwnd(hwnd)
    if _is_main_cursor_window(_window_title(root)):
        return root
    if _is_main_cursor_window(_window_title(hwnd)):
        return hwnd
    cur = hwnd
    for _ in range(8):
        parent = int(user32.GetParent(cur) or 0)
        if not parent:
            owner = int(user32.GetWindow(cur, 4) or 0)  # GW_OWNER
            parent = owner
        if not parent or parent == cur:
            break
        cur = parent
        if _is_main_cursor_window(_window_title(cur)):
            return cur
    return None

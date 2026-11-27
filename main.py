# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# DPI awareness MUST be set before tkinter is imported (Windows locks it on load).
from src.windows_track import (  # noqa: E402
    discover_cursor_windows,
    enable_dpi_awareness,
    foreground_cursor_hwnd,
)

enable_dpi_awareness()

import tkinter as tk  # noqa: E402

from src.accounts import load_profiles, read_auth  # noqa: E402
from src.overlay import OverlayManager  # noqa: E402
from src.usage_api import UsageSnapshot, fetch_usage  # noqa: E402


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}"


def path_norm(p: str) -> str:
    try:
        return str(Path(os.path.expandvars(p)).resolve()).lower()
    except OSError:
        return p.replace("/", "\\").lower()


def probe(config: dict) -> int:
    profiles = load_profiles(config)
    if not profiles:
        print("No Cursor profiles found. Check config.json")
        return 1

    print(f"Found {len(profiles)} profile(s):\n")
    for p in profiles:
        auth = read_auth(p)
        print(f"- [{p.id}] {p.label}")
        print(f"  data: {p.user_data_dir}")
        print(f"  email: {auth.email or '(none)'}")
        print(f"  plan: {auth.plan or '(none)'}")
        print(f"  token: {'OK' if auth.access_token else 'MISSING'}")
        snap = fetch_usage(auth)
        if snap.error:
            print(f"  usage: ERROR - {snap.error}")
        else:
            print(
                f"  usage: total={_fmt(snap.total_percent)}% "
                f"auto={_fmt(snap.auto_percent)}% "
                f"api={_fmt(snap.api_percent)}%"
            )
            if snap.display_message:
                print(f"  msg: {snap.display_message}")
        print()

    print("Visible Cursor windows:")
    wins = discover_cursor_windows()
    if not wins:
        print("  (none)")
    for w in wins:
        print(f"  hwnd={w.hwnd} dpi={w.dpi} udd={w.user_data_dir}")
        print(f"    title={w.title}")
    return 0


class App:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.metric = str(config.get("metric") or "total")
        self.poll_seconds = float(config.get("poll_seconds") or 20)
        self.reposition_ms = int(config.get("reposition_ms") or 250)
        self.profiles = load_profiles(config)
        self.usage_by_dir: dict[str, UsageSnapshot] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("cursor-quota-ring")
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        bottom_offset = int(config.get("bottom_offset") or 80)
        agents_bottom = config.get("agents_bottom_offset")
        self.overlays = OverlayManager(
            self.root,
            overlay_size=int(config.get("overlay_size") or 40),
            activity_bar_width=int(config.get("activity_bar_width") or 48),
            bottom_offset=bottom_offset,
            agents_bottom_offset=None if agents_bottom is None else int(agents_bottom),
            click_through=bool(config.get("click_through", False)),
            metric=self.metric,
            foreground_only=bool(config.get("foreground_only", False)),  # false = always-on
        )
        self.overlays.set_accounts([(p.normalized_dir(), p.label) for p in self.profiles])

    def start(self) -> None:
        if not self.profiles:
            print("No profiles configured. Edit config.json")
            return
        print(f"Loaded {len(self.profiles)} profile(s). Tracking Cursor windows...")
        print("Quit: Ctrl+C in this console.")
        # First paint must already have usage — otherwise every restart shows a
        # hollow ring ("-") and a missed redraw can leave it empty.
        self._refresh_all_usage()
        threading.Thread(target=self._poll_loop, name="usage-poll", daemon=True).start()
        self.root.after(50, self._tick)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    def _poll_one(self, p) -> tuple[str, UsageSnapshot]:
        try:
            auth = read_auth(p)
            snap = fetch_usage(auth)
        except Exception as e:  # noqa: BLE001 — keep poll thread alive
            snap = UsageSnapshot(
                email="",
                label=p.label,
                plan="",
                total_percent=None,
                auto_percent=None,
                api_percent=None,
                display_message="",
                error=f"poll exception: {e}",
            )
        return p.normalized_dir(), snap

    def _publish(self, key: str, snap: UsageSnapshot) -> None:
        with self._lock:
            self.usage_by_dir = {**self.usage_by_dir, key: snap}
        # Wake the UI promptly when a background poll lands new numbers.
        try:
            self.root.after(0, self.overlays.invalidate_render_cache)
        except Exception:
            pass

    def _refresh_all_usage(self) -> None:
        for p in self._profiles_poll_order():
            key, snap = self._poll_one(p)
            with self._lock:
                self.usage_by_dir = {**self.usage_by_dir, key: snap}

    def _profiles_poll_order(self) -> list:
        """Prefer accounts tied to currently visible Cursor windows."""
        try:
            wins = discover_cursor_windows()
        except Exception:
            return list(self.profiles)
        active = {path_norm(w.user_data_dir) for w in wins}
        if not active:
            return list(self.profiles)
        first = [p for p in self.profiles if p.normalized_dir() in active]
        rest = [p for p in self.profiles if p.normalized_dir() not in active]
        return first + rest

    def _poll_loop(self) -> None:
        # Startup already fetched once; wait a full interval before the next round.
        self._stop.wait(self.poll_seconds)
        while not self._stop.is_set():
            for p in self._profiles_poll_order():
                if self._stop.is_set():
                    break
                key, snap = self._poll_one(p)
                self._publish(key, snap)
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        if self._stop.is_set():
            return
        try:
            wins = discover_cursor_windows()
            with self._lock:
                by_dir = dict(self.usage_by_dir)

            # Exact path keys only — never fuzzy-match across accounts.
            resolved: dict[str, UsageSnapshot] = {}
            for pk, snap in by_dir.items():
                resolved[pk] = snap
                resolved[pk.replace("/", "\\")] = snap
            for w in wins:
                key = path_norm(w.user_data_dir)
                raw = w.user_data_dir.replace("/", "\\").lower()
                snap = by_dir.get(key)
                if snap is not None:
                    resolved[key] = snap
                    resolved[raw] = snap
            self.overlays.sync(wins, resolved, foreground_cursor_hwnd())
        except Exception as e:
            # Avoid crashing the UI loop; log once-ish via print when console exists.
            try:
                print(f"[tick] {e}")
            except Exception:
                pass
        self.root.after(self.reposition_ms, self._tick)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cursor-quota-ring - Activity Bar overlay")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1

    config = load_config(config_path)
    if args.probe:
        return probe(config)

    App(config).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

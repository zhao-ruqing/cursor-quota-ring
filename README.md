# cursor-quota-ring

Windows overlay that shows your **Cursor** plan usage as a small ring + percentage on the left Activity Bar.

Not a Cursor extension — a lightweight desktop overlay that follows the focused Cursor window and binds usage to that window’s account (`--user-data-dir`).

**Repo:** https://github.com/zhao-ruqing/cursor-quota-ring

![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![license](https://img.shields.io/badge/license-MIT-green)

## Features

- Ring chart with center percentage (sharp on 150% / 200% DPI)
- Multi-account: each Cursor profile / `user-data-dir` is tracked separately
- Maps the focused Cursor window → correct account automatically
- Decrypts Cursor 3.27+ `cursor-safe-storage:v1:` tokens (Windows DPAPI + AES-GCM)
- Optional startup install; no Electron runtime

## Why not Pulse / CodeNotch / UsageBar?

| Tool | Form | Gap |
|------|------|-----|
| Pulse / CodeNotch | Screen-edge notch, all accounts | Not pinned to a Cursor Activity Bar / window |
| UsageBar | Draggable strip | Not window-bound; may miss custom profile folders |
| **cursor-quota-ring** | Overlay on Activity Bar | Built for dual Cursor instances on Windows |

Token / API approach inspired by [UsageBar](https://github.com/yavuzceliker/usagebar) (MIT).

## Requirements

- Windows 10 / 11
- Python **3.10+** with **tkinter**
- Cursor desktop signed in (one or more profiles)

```powershell
pip install -r requirements.txt
```

## Quick start

```powershell
git clone https://github.com/zhao-ruqing/cursor-quota-ring.git
cd cursor-quota-ring

copy config.example.json config.json   # then edit profiles if needed
pip install -r requirements.txt

# Check accounts / usage / window binding
.\run.ps1 -Probe

# Run (console)
.\run.ps1

# Run background (no console)
.\run.ps1 -Hidden

# Optional: start with Windows
.\install-startup.ps1
```

Click a Cursor window so it is focused — the ring appears on the left Activity Bar (above the gear).

## Dual accounts

Cursor keeps one login per `user-data-dir`. Example second instance:

```powershell
& "$env:LOCALAPPDATA\Programs\cursor\Cursor.exe" `
  --user-data-dir="$env:USERPROFILE\CursorAccount2\data" `
  --extensions-dir="$env:USERPROFILE\CursorAccount2\extensions"
```

Then list both folders under `profiles` in `config.json` (see `config.example.json`).

## Config

| Key | Meaning |
|-----|---------|
| `overlay_size` | Ring size at 96 DPI (scales with display DPI) |
| `activity_bar_width` | Activity Bar width (default `48`) |
| `bottom_offset` | Distance from client bottom — **larger = higher** |
| `metric` | `total` \| `auto` \| `api` |
| `click_through` | `true` = clicks pass through to Cursor |
| `foreground_only` | `true` = only show ring for the focused Cursor window (recommended when two windows are maximized on the same monitor) |
| `poll_seconds` | Usage API refresh interval |
| `reposition_ms` | Overlay follow interval |

## Project layout

```text
cursor-quota-ring/
  main.py                 # entry
  config.example.json     # sample config
  run.ps1                 # start / probe / hidden
  install-startup.ps1     # optional autostart
  requirements.txt
  src/
    accounts.py           # profile discovery + token read
    safe_storage.py       # cursor-safe-storage decrypt
    usage_api.py          # GetCurrentPeriodUsage
    windows_track.py      # Cursor window + user-data-dir binding
    overlay.py            # always-on-top overlay
    ring_draw.py          # antialiased ring (Pillow)
```

## Notes / limits

- Uses Cursor’s undocumented Dashboard API; fields may change.
- Tokens stay on your machine; requests go only to Cursor’s API.
- Electron windows do not accept a reliable `SetParent` child overlay, so the ring is a top-level window aligned to the Activity Bar.
- With two maximized Cursor windows on one screen, keep `foreground_only: true` so accounts don’t visually stack.

## License

MIT

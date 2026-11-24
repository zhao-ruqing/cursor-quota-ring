from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


AUTH_KEYS = (
    "cursorAuth/accessToken",
    "cursorAuth/cachedEmail",
    "cursorAuth/stripeMembershipType",
)


@dataclass(frozen=True)
class CursorProfile:
    id: str
    label: str
    user_data_dir: Path

    @property
    def state_db(self) -> Path:
        return self.user_data_dir / "User" / "globalStorage" / "state.vscdb"

    def normalized_dir(self) -> str:
        return str(self.user_data_dir.resolve()).lower()


def expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def load_profiles(config: dict) -> list[CursorProfile]:
    profiles: list[CursorProfile] = []
    seen: set[str] = set()

    for item in config.get("profiles") or []:
        raw = item.get("user_data_dir") or ""
        if not raw:
            continue
        path = expand_path(raw)
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        profiles.append(
            CursorProfile(
                id=str(item.get("id") or path.name),
                label=str(item.get("label") or path.name),
                user_data_dir=path,
            )
        )

    # Auto-discover common layouts UsageBar-style, without overriding explicit config.
    appdata = Path(os.environ.get("APPDATA", ""))
    home = Path.home()
    extras: list[tuple[str, str, Path]] = []
    if appdata.exists():
        for d in sorted(appdata.glob("Cursor*")):
            if d.is_dir():
                label = "primary" if d.name == "Cursor" else d.name
                extras.append((f"auto-{d.name}", label, d))
    for d in sorted(home.glob(".cursor-*")):
        if d.is_dir():
            extras.append((f"auto-{d.name}", d.name[8:], d))
    for d in sorted(home.glob("CursorAccount*")):
        data = d / "data" if (d / "data").is_dir() else d
        if data.is_dir():
            extras.append((f"auto-{d.name}", d.name, data))

    for pid, label, path in extras:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        db = path / "User" / "globalStorage" / "state.vscdb"
        if not db.exists():
            continue
        seen.add(key)
        profiles.append(CursorProfile(id=pid, label=label, user_data_dir=path.resolve()))

    return profiles


def _read_item_table(db_path: Path, keys: Iterable[str]) -> dict[str, str]:
    if not db_path.exists():
        return {}

    key_list = list(keys)
    result: dict[str, str] = {}

    def query(uri: str) -> None:
        con = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            cur = con.cursor()
            placeholders = ",".join("?" for _ in key_list)
            rows = cur.execute(
                f"SELECT key, value FROM ItemTable WHERE key IN ({placeholders})",
                key_list,
            ).fetchall()
            for k, v in rows:
                if isinstance(v, bytes):
                    v = v.decode("utf-8", "replace")
                result[str(k)] = str(v)
        finally:
            con.close()

    # Prefer true read-only open; fall back to a temp copy if the live DB is locked.
    try:
        uri = db_path.as_uri() + "?mode=ro"
        query(uri)
        return result
    except sqlite3.Error:
        pass

    tmp: str | None = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="cursor-usage-", suffix=".vscdb")
        os.close(fd)
        shutil.copy2(db_path, tmp)
        wal = Path(str(db_path) + "-wal")
        shm = Path(str(db_path) + "-shm")
        if wal.exists():
            shutil.copy2(wal, tmp + "-wal")
        if shm.exists():
            shutil.copy2(shm, tmp + "-shm")
        query(Path(tmp).as_uri() + "?mode=ro")
    except OSError:
        return {}
    finally:
        if tmp:
            for p in (tmp, tmp + "-wal", tmp + "-shm"):
                try:
                    os.remove(p)
                except OSError:
                    pass
    return result


@dataclass
class AuthInfo:
    profile: CursorProfile
    email: str
    access_token: str
    plan: str

    @property
    def ok(self) -> bool:
        return bool(self.access_token)


def read_auth(profile: CursorProfile) -> AuthInfo:
    from .safe_storage import decrypt_secret

    values = _read_item_table(profile.state_db, AUTH_KEYS)
    raw = values.get("cursorAuth/accessToken", "").strip()
    token = ""
    if raw:
        try:
            token = decrypt_secret(raw, profile.user_data_dir)
        except Exception:
            # Leave empty so probe/UI show a clear auth error instead of sending ciphertext.
            token = ""
    return AuthInfo(
        profile=profile,
        email=values.get("cursorAuth/cachedEmail", "").strip(),
        access_token=token,
        plan=values.get("cursorAuth/stripeMembershipType", "").strip(),
    )

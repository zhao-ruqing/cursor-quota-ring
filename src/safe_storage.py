# -*- coding: utf-8 -*-
"""Decrypt Cursor Electron safeStorage values on Windows (cursor-safe-storage:v1:)."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

SAFE_PREFIX = "cursor-safe-storage:v1:"


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes as wt

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _os_crypt_key(user_data_dir: Path) -> bytes | None:
    local_state = user_data_dir / "Local State"
    if not local_state.exists():
        # Some layouts keep Local State one level up from "data".
        alt = user_data_dir.parent / "Local State"
        local_state = alt if alt.exists() else local_state
    if not local_state.exists():
        return None
    try:
        payload = json.loads(local_state.read_text(encoding="utf-8"))
        b64 = payload["os_crypt"]["encrypted_key"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError):
        return None
    raw = base64.b64decode(b64)
    if not raw.startswith(b"DPAPI"):
        return None
    return _dpapi_unprotect(raw[5:])


def _aes_gcm_decrypt(key: bytes, blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # Chromium OSCrypt Win AES-GCM: optional "v10" prefix, 12-byte nonce, ciphertext||tag(16)
    data = blob
    if data.startswith(b"v10"):
        data = data[3:]
    elif data.startswith(b"v11"):
        data = data[3:]
    nonce = data[:12]
    body = data[12:]
    return AESGCM(key).decrypt(nonce, body, None)


def decrypt_secret(value: str, user_data_dir: str | Path) -> str:
    """Return plaintext JWT/string. Passes through legacy plaintext tokens."""
    if not value:
        return value
    if not value.startswith(SAFE_PREFIX):
        return value

    user_data_dir = Path(os.path.expandvars(str(user_data_dir)))
    blob = base64.b64decode(value[len(SAFE_PREFIX) :])

    # 1) Chromium/Electron OSCrypt AES-GCM with Local State key
    key = _os_crypt_key(user_data_dir)
    if key is not None:
        try:
            return _aes_gcm_decrypt(key, blob).decode("utf-8")
        except Exception:
            pass

    # 2) Whole-blob DPAPI (older Electron path)
    try:
        return _dpapi_unprotect(blob).decode("utf-8")
    except Exception:
        pass

    # 3) DPAPI after stripping v10
    if blob.startswith(b"v10") or blob.startswith(b"v11"):
        try:
            return _dpapi_unprotect(blob[3:]).decode("utf-8")
        except Exception:
            pass

    raise ValueError(
        f"Failed to decrypt Cursor safeStorage token for {user_data_dir}. "
        "Install 'cryptography' and ensure this Windows user can unlock DPAPI."
    )

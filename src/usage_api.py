from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .accounts import AuthInfo


USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"


@dataclass
class UsageSnapshot:
    email: str
    label: str
    plan: str
    total_percent: float | None
    auto_percent: float | None
    api_percent: float | None
    display_message: str
    error: str = ""

    def percent_for(self, metric: str = "total") -> float | None:
        metric = (metric or "total").lower()
        if metric == "auto":
            return self.auto_percent
        if metric == "api":
            return self.api_percent
        # Prefer total; fall back to max of auto/api so the ring still moves.
        if self.total_percent is not None:
            return self.total_percent
        vals = [v for v in (self.auto_percent, self.api_percent) if v is not None]
        return max(vals) if vals else None


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_usage(auth: AuthInfo, timeout: float = 20.0) -> UsageSnapshot:
    label = auth.profile.label
    if not auth.access_token:
        return UsageSnapshot(
            email=auth.email,
            label=label,
            plan=auth.plan,
            total_percent=None,
            auto_percent=None,
            api_percent=None,
            display_message="",
            error="not signed in / no token",
        )

    req = urllib.request.Request(
        USAGE_URL,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {auth.access_token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "x-cursor-client-version": "3.31.15",
            "User-Agent": "cursor-quota-ring/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return UsageSnapshot(
            email=auth.email,
            label=label,
            plan=auth.plan,
            total_percent=None,
            auto_percent=None,
            api_percent=None,
            display_message="",
            error=f"HTTP {e.code}: {body[:160]}",
        )
    except Exception as e:  # noqa: BLE001 — surface any network/parse failure in UI
        return UsageSnapshot(
            email=auth.email,
            label=label,
            plan=auth.plan,
            total_percent=None,
            auto_percent=None,
            api_percent=None,
            display_message="",
            error=str(e),
        )

    plan = data.get("planUsage") or {}
    return UsageSnapshot(
        email=auth.email,
        label=label,
        plan=auth.plan,
        total_percent=_num(plan.get("totalPercentUsed")),
        auto_percent=_num(plan.get("autoPercentUsed")),
        api_percent=_num(plan.get("apiPercentUsed")),
        display_message=str(data.get("displayMessage") or ""),
        error="",
    )

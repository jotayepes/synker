"""Which backups to keep: the newest N, plus the newest one of each day for D days, plus locked ones."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from synker.repository import BackupEntry


def select_for_deletion(backups: list[BackupEntry], keep_last: int, keep_daily_days: int,
                        now: float | None = None) -> list[BackupEntry]:
    now = time.time() if now is None else now
    ordered = sorted(backups, key=lambda b: b.created, reverse=True)
    keep = {b.id for b in ordered[:keep_last]}
    keep |= {b.id for b in ordered if b.locked}
    if keep_daily_days > 0:
        cutoff = now - keep_daily_days * 86400
        seen_days: set[str] = set()
        for b in ordered:
            if b.created < cutoff:
                break
            day = datetime.fromtimestamp(b.created, UTC).strftime("%Y-%m-%d")
            if day not in seen_days:
                seen_days.add(day)
                keep.add(b.id)
    return [b for b in ordered if b.id not in keep]

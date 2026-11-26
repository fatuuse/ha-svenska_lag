"""Membership period helpers. No Home Assistant imports, so they can be tested on their own."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp. Naive timestamps are treated as UTC."""
    if not value or not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def current_period(periods: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """The period that contains `now`. If several do, the one that started last."""
    active: list[tuple[datetime, dict[str, Any]]] = []
    for period in periods:
        start = parse_iso(period.get("startDate"))
        end = parse_iso(period.get("endDate"))
        if start and end and start <= now <= end:
            active.append((start, period))
    if not active:
        return None
    return max(active, key=lambda item: item[0])[1]


def card_valid_until(periods: list[dict[str, Any]], now: datetime) -> datetime | None:
    """Latest end of a membership card validity that is active at `now`."""
    ends: list[datetime] = []
    for period in periods:
        validity = period.get("membershipCardValidity") or {}
        start = parse_iso(validity.get("startDate"))
        end = parse_iso(validity.get("endDate"))
        if start and end and start <= now <= end:
            ends.append(end)
    return max(ends) if ends else None

"""Tests for membership period helpers. Run with: python3 tests/test_membership.py"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "membership", ROOT / "custom_components" / "svenskalag" / "membership.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _period(name, start, end, card_start=None, card_end=None):
    period = {"name": name, "startDate": start, "endDate": end}
    if card_start:
        period["membershipCardValidity"] = {"startDate": card_start, "endDate": card_end}
    return period


def test_current_period_is_the_active_one():
    periods = [
        _period("2025/2026", "2025-07-01T00:00:00+00:00", "2026-06-30T23:59:59+00:00"),
        _period("2026/2027", "2026-07-01T00:00:00+00:00", "2027-06-30T23:59:59+00:00"),
    ]
    assert m.current_period(periods, NOW)["name"] == "2026/2027"


def test_no_active_period_returns_none():
    periods = [_period("2025/2026", "2025-07-01T00:00:00+00:00", "2026-06-30T23:59:59+00:00")]
    assert m.current_period(periods, NOW) is None


def test_overlapping_periods_pick_the_one_that_started_last():
    periods = [
        _period("A", "2026-01-01T00:00:00+00:00", "2027-12-31T00:00:00+00:00"),
        _period("B", "2026-07-01T00:00:00+00:00", "2027-06-30T00:00:00+00:00"),
    ]
    assert m.current_period(periods, NOW)["name"] == "B"


def test_empty_list_returns_none():
    assert m.current_period([], NOW) is None
    assert m.card_valid_until([], NOW) is None


def test_card_validity_returns_latest_active_end():
    periods = [
        _period("A", "2026-07-01T00:00:00+00:00", "2027-06-30T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00", "2026-12-31T00:00:00+00:00"),
        _period("B", "2026-07-01T00:00:00+00:00", "2027-06-30T00:00:00+00:00",
                "2026-06-01T00:00:00+00:00", "2027-02-28T00:00:00+00:00"),
    ]
    assert m.card_valid_until(periods, NOW) == datetime(2027, 2, 28, tzinfo=timezone.utc)


def test_card_validity_ignores_expired_cards():
    periods = [_period("A", "2025-07-01T00:00:00+00:00", "2026-06-30T00:00:00+00:00",
                       "2025-01-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00")]
    assert m.card_valid_until(periods, NOW) is None


def test_z_suffix_and_naive_timestamps_are_parsed():
    assert m.parse_iso("2026-07-01T00:00:00Z") == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert m.parse_iso("2026-07-01T00:00:00") == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert m.parse_iso("not a date") is None
    assert m.parse_iso(None) is None


if __name__ == "__main__":
    failures = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as err:
            failures += 1
            print(f"FAIL {name}: {err!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)

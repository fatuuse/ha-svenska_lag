"""Store per-activity numbers in Home Assistant's recorder (long-term statistics).

Each activity that has started gets one hourly value at its start time:
- attending: number who answered yes
- invited: number of recipients of the invitation

The values appear in Home Assistant's statistics graphs and are kept in the
built-in database. No external database is used.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# (statistic suffix, activity key, display name)
_SERIES = (
    ("attending", "attending_count", "Svenskalag anmälda"),
    ("invited", "recipients", "Svenskalag kallade"),
)


def _metadata(statistic_id: str, name: str) -> StatisticMetaData:
    return StatisticMetaData(
        source="recorder",
        statistic_id=statistic_id,
        name=name,
        unit_of_measurement=None,
        has_mean=True,
        has_sum=False,
        mean_type=StatisticMeanType.ARITHMETIC,
    )


def _rows(activities: list[dict[str, Any]], key: str) -> list[StatisticData]:
    """One value per start hour. Later activities in the same hour replace earlier ones."""
    now = dt_util.now()
    by_hour: dict[datetime, float] = {}
    for activity in activities:
        start = activity["start"]
        value = activity.get(key)
        if start is None or value is None or start > now:
            continue
        hour = dt_util.as_utc(start.replace(minute=0, second=0, microsecond=0))
        by_hour[hour] = float(value)
    return [StatisticData(start=h, mean=v, min=v, max=v) for h, v in sorted(by_hour.items())]


def async_import_activity_stats(
    hass: HomeAssistant, stats_key: str, activities: list[dict[str, Any]]
) -> None:
    """Write the current values for all started activities."""
    for suffix, key, name in _SERIES:
        rows = _rows(activities, key)
        if not rows:
            _LOGGER.debug("No %s values to write yet", suffix)
            continue
        _LOGGER.debug("Writing %d %s rows to statistics", len(rows), suffix)
        async_add_external_statistics(
            hass,
            _metadata(f"{DOMAIN}:{suffix}_{stats_key}", name),
            rows,
        )

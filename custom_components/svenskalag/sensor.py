"""Sensors for Svenskalag."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DAYS_AHEAD
from .coordinator import SvenskalagCoordinator
from .entity import SvenskalagEntity, activity_attributes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    for subentry_id, coordinator in entry.runtime_data.items():
        async_add_entities(
            [
                NextActivitySensor(coordinator),
                UpcomingCountSensor(coordinator),
                NextAttendanceSensor(coordinator, "next_training_attendance", lambda d: d.next_training),
                NextAttendanceSensor(coordinator, "next_match_attendance", lambda d: d.next_match),
            ],
            config_subentry_id=subentry_id or None,
        )

class NextActivitySensor(SvenskalagEntity, SensorEntity):
    """Timestamp of the next activity, with details as attributes."""

    _attr_translation_key = "next_activity"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "next_activity")

    @property
    def native_value(self):
        nxt = self.coordinator.data.next_activity
        return nxt["start"] if nxt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        nxt = self.coordinator.data.next_activity
        return activity_attributes(nxt) if nxt else None


class UpcomingCountSensor(SvenskalagEntity, SensorEntity):
    """Number of upcoming (non-cancelled) activities in the fetch window."""

    _attr_translation_key = "upcoming_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "upcoming_count")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.upcoming_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"days_ahead": DAYS_AHEAD}


class NextAttendanceSensor(SvenskalagEntity, SensorEntity):
    """Number of people who answered yes to the next training or match."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SvenskalagCoordinator, key: str, pick) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._pick = pick

    @property
    def _activity(self) -> dict[str, Any] | None:
        return self._pick(self.coordinator.data)

    @property
    def native_value(self) -> int | None:
        activity = self._activity
        return activity["attending_count"] if activity else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        activity = self._activity
        if not activity:
            return None
        return {
            "title": activity["title"],
            "starts_at": activity["start"].isoformat() if activity["start"] else None,
            "location": activity["location"],
            "invited_at": activity["invited_at"].isoformat() if activity["invited_at"] else None,
        }

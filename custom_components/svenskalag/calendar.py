"""Calendar entity for Svenskalag activities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SvenskalagCoordinator
from .entity import SvenskalagEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    for subentry_id, coordinator in entry.runtime_data.items():
        async_add_entities(
            [SvenskalagCalendar(coordinator)],
            config_subentry_id=subentry_id or None,
        )


def _to_event(activity: dict[str, Any]) -> CalendarEvent:
    title = activity["title"] or activity["type"] or "Aktivitet"
    if activity["cancelled"]:
        title = f"[Inställd] {title}"
    elif activity["postponed"]:
        title = f"[Flyttad] {title}"

    lines: list[str] = []
    if activity["team"]:
        lines.append(f"Lag: {activity['team']}")
    if activity["opponent"]:
        lines.append(f"Motståndare: {activity['opponent']}")
    if activity["gathering_at"]:
        lines.append(f"Samling: {dt_util.as_local(activity['gathering_at']).strftime('%H:%M')}")
    if activity["gathering_location"]:
        lines.append(f"Samlingsplats: {activity['gathering_location']}")
    if activity["web_url"]:
        lines.append(activity["web_url"])

    return CalendarEvent(
        summary=title,
        start=activity["start"],
        end=activity["end"] or activity["start"],
        location=activity["location"],
        description="\n".join(lines) or None,
    )


class SvenskalagCalendar(SvenskalagEntity, CalendarEntity):
    """All activities as calendar events."""

    _attr_translation_key = "activities"

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "activities")

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        for activity in self.coordinator.data.activities:
            if activity["end"] and activity["end"] >= now:
                return _to_event(activity)
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        return [
            _to_event(a)
            for a in self.coordinator.data.activities
            if a["start"] and start_date <= a["start"] < end_date
        ]

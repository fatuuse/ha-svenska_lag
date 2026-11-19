"""Shared helpers for Svenskalag entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SvenskalagCoordinator


class SvenskalagEntity(CoordinatorEntity[SvenskalagCoordinator]):
    """Base entity: one device per config entry (= one person)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SvenskalagCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=f"Svenskalag {coordinator.data.person_name}",
            manufacturer="Svenskalag",
            entry_type=DeviceEntryType.SERVICE,
        )


def activity_attributes(activity: dict[str, Any]) -> dict[str, Any]:
    """Flatten an activity into entity attributes."""
    return {
        "title": activity["title"],
        "type": activity["type"],
        "team": activity["team"],
        "is_game": activity["is_game"],
        "opponent": activity["opponent"],
        "is_home": activity["is_home"],
        "location": activity["location"],
        "gathering_at": activity["gathering_at"].isoformat() if activity["gathering_at"] else None,
        "gathering_location": activity["gathering_location"],
        "cancelled": activity["cancelled"],
        "postponed": activity["postponed"],
        "attending": activity["attending"],
        "reply_deadline": activity["reply_deadline"].isoformat() if activity["reply_deadline"] else None,
        "reply_url": activity["reply_url"],
        "web_url": activity["web_url"],
    }

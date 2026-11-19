"""Binary sensors for Svenskalag."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SvenskalagCoordinator
from .entity import SvenskalagEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NeedsReplyBinarySensor(entry.runtime_data)])


class NeedsReplyBinarySensor(SvenskalagEntity, BinarySensorEntity):
    """On when there are invitations without a reply before the deadline."""

    _attr_translation_key = "needs_reply"

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "needs_reply")

    @property
    def is_on(self) -> bool:
        return len(self.coordinator.data.needs_reply) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "activities": [
                {
                    "title": a["title"],
                    "start": a["start"].isoformat() if a["start"] else None,
                    "reply_deadline": a["reply_deadline"].isoformat() if a["reply_deadline"] else None,
                    "reply_url": a["reply_url"],
                }
                for a in self.coordinator.data.needs_reply
            ]
        }

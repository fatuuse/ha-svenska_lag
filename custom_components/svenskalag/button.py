"""Button that refreshes Svenskalag data on demand."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    for subentry_id, coordinator in entry.runtime_data.items():
        async_add_entities(
            [RefreshDataButton(coordinator)],
            config_subentry_id=subentry_id or None,
        )


class RefreshDataButton(SvenskalagEntity, ButtonEntity):
    """Starts an update now, without waiting for the next scheduled one."""

    _attr_translation_key = "refresh_data"

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "refresh_data")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()

"""The Svenskalag integration."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SvenskalagApi
from .const import (
    CONF_DOMAIN,
    CONF_PASSWORD,
    CONF_TEAM_SLUG,
    CONF_TOKEN,
    CONF_USERNAME,
)
from .coordinator import SvenskalagCoordinator
from .web_client import SvenskalagWebClient

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change, so the new interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
]


def _create_client(hass: HomeAssistant, entry: ConfigEntry) -> SvenskalagApi | SvenskalagWebClient:
    if CONF_TOKEN in entry.data:
        return SvenskalagApi(async_get_clientsession(hass), entry.data[CONF_TOKEN])

    # The web login keeps cookies, so it gets its own session with its own jar.
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    entry.async_on_unload(session.close)
    return SvenskalagWebClient(
        session,
        entry.data[CONF_DOMAIN],
        entry.data[CONF_TEAM_SLUG],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Svenskalag from a config entry."""
    client = _create_client(hass, entry)
    coordinator = SvenskalagCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

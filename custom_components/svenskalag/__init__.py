"""The Svenskalag integration.

Two kinds of config entries are supported:
- Person key (API): one entry, one person.
- Username and password: one entry per username, with one subentry per team.
  Each team gets its own coordinator and devices.
"""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SvenskalagApi
from .const import CONF_DOMAIN, CONF_PASSWORD, CONF_TEAM_SLUG, CONF_TOKEN, CONF_USERNAME
from .coordinator import SvenskalagCoordinator
from .web_client import SvenskalagWebClient

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
]


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change, so the new interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


def _web_coordinator(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str | None,
    team_slug: str,
) -> SvenskalagCoordinator:
    # Each team gets its own session, so cookies from one team do not affect another.
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    entry.async_on_unload(session.close)
    client = SvenskalagWebClient(
        session,
        entry.data[CONF_DOMAIN],
        team_slug,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    return SvenskalagCoordinator(hass, entry, client, subentry_id, team_slug)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Svenskalag from a config entry."""
    coordinators: dict[str, SvenskalagCoordinator] = {}

    if CONF_TOKEN in entry.data:
        api = SvenskalagApi(async_get_clientsession(hass), entry.data[CONF_TOKEN])
        coordinators[""] = SvenskalagCoordinator(hass, entry, api, None, None)
    elif CONF_TEAM_SLUG in entry.data:
        raise ConfigEntryError(
            "This entry uses the old one-team format, which is no longer supported. "
            "Remove it and add the login again, then add the teams."
        )
    else:
        for subentry in entry.subentries.values():
            coordinators[subentry.subentry_id] = _web_coordinator(
                hass, entry, subentry.subentry_id, subentry.data[CONF_TEAM_SLUG]
            )

    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinators
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

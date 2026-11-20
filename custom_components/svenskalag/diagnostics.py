"""Diagnostics for Svenskalag. Download from the integration page in Home Assistant.

Passwords and tokens are redacted. Activity titles and locations are left out,
so the file can be shared when asking for help.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_PASSWORD, CONF_TOKEN, CONF_UPDATE_HOURS, CONF_USERNAME

TO_REDACT = {CONF_TOKEN, CONF_PASSWORD, CONF_USERNAME}


def _team_diagnostics(coordinator) -> dict[str, Any]:
    data = coordinator.data
    return {
        "team": coordinator.team_slug,
        "subentry_id": coordinator.subentry_id,
        "last_update_success": coordinator.last_update_success,
        "update_interval": str(coordinator.update_interval),
        "last_exception": str(coordinator.last_exception) if coordinator.last_exception else None,
        "summary": {
            "activities": len(data.activities),
            "upcoming": data.upcoming_count,
            "needs_reply": len(data.needs_reply),
        },
        "activities": [
            {
                "type": a["type"],
                "is_game": a["is_game"],
                "start": a["start"].isoformat() if a["start"] else None,
                "cancelled": a["cancelled"],
                "attending_count": a["attending_count"],
                "recipients": a["recipients"],
                "invited_at": a["invited_at"].isoformat() if a["invited_at"] else None,
            }
            for a in data.activities
        ],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    auth = "person_key" if CONF_TOKEN in entry.data else "credentials"

    return {
        "generated_at": dt_util.now().isoformat(),
        "entry": {
            "auth": auth,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": {CONF_UPDATE_HOURS: entry.options.get(CONF_UPDATE_HOURS)},
            "subentries": [sub.data.get("team_slug") for sub in entry.subentries.values()],
        },
        "teams": [_team_diagnostics(c) for c in entry.runtime_data.values()],
    }

"""Config flow for Svenskalag.

A username and password login is one entry. Teams are added as subentries,
so the teams appear grouped under the login in Home Assistant.
Person key (API) logins are single entries without teams.
"""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import SvenskalagApi, SvenskalagAuthError, SvenskalagError
from .const import (
    CONF_DOMAIN,
    CONF_PASSWORD,
    CONF_TEAM_SLUG,
    CONF_TOKEN,
    CONF_UPDATE_HOURS,
    CONF_USERNAME,
    DEFAULT_UPDATE_HOURS,
    DOMAIN,
    SUBENTRY_TYPE_TEAM,
)
from .web_client import SvenskalagWebClient

STEP_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})

STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DOMAIN): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_TEAM_SCHEMA = vol.Schema({vol.Required(CONF_TEAM_SLUG): str})

STEP_PASSWORD_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _clean_domain(value: str) -> str:
    value = value.strip()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.strip("/")


def _clean_slug(value: str) -> str:
    return value.strip().strip("/")


def _person_name(raw: dict[str, Any]) -> str:
    person = raw.get("person") or {}
    name = " ".join(p for p in (person.get("firstName"), person.get("lastName")) if p)
    return name.strip() or "Okänd"


async def _async_check_login(
    domain: str, team: str, username: str, password: str
) -> None:
    """Log in to one team's site. Raises SvenskalagAuthError or SvenskalagError."""
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    try:
        client = SvenskalagWebClient(session, domain, team, username, password)
        await client.async_login()
    finally:
        await session.close()


class SvenskalagConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Svenskalag."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_TEAM: SvenskalagTeamSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SvenskalagOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["credentials", "token"])

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Save the login. Teams are added afterwards, and each one is checked then."""
        if user_input is not None:
            domain = _clean_domain(user_input[CONF_DOMAIN])
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(f"{domain}/{username}".lower())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Svenskalag – {username}",
                data={
                    CONF_DOMAIN: domain,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                },
            )
        return self.async_show_form(step_id="credentials", data_schema=STEP_CREDENTIALS_SCHEMA)

    async def async_step_token(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            try:
                name = await self._async_validate_token(token)
            except SvenskalagAuthError:
                errors["base"] = "invalid_auth"
            except SvenskalagError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(name.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Svenskalag – {name}",
                    data={CONF_TOKEN: token},
                )
        return self.async_show_form(step_id="token", data_schema=STEP_TOKEN_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        uses_token = CONF_TOKEN in entry.data
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                if uses_token:
                    new_data = {CONF_TOKEN: user_input[CONF_TOKEN].strip()}
                    await self._async_validate_token(new_data[CONF_TOKEN])
                else:
                    password = user_input[CONF_PASSWORD]
                    # Check against one team, if the login has any.
                    team = next(
                        (sub.data[CONF_TEAM_SLUG] for sub in entry.subentries.values()), None
                    )
                    if team:
                        await _async_check_login(
                            entry.data[CONF_DOMAIN], team, entry.data[CONF_USERNAME], password
                        )
                    new_data = {CONF_PASSWORD: password}
            except SvenskalagAuthError:
                errors["base"] = "invalid_auth"
            except SvenskalagError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=new_data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_TOKEN_SCHEMA if uses_token else STEP_PASSWORD_SCHEMA,
            errors=errors,
        )

    def _get_reauth_entry(self) -> ConfigEntry:
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    async def _async_validate_token(self, token: str) -> str:
        api = SvenskalagApi(async_get_clientsession(self.hass), token)
        today = dt_util.now().date()
        raw = await api.async_get_my_activities(today, today)
        return _person_name(raw)


class SvenskalagTeamSubentryFlow(ConfigSubentryFlow):
    """Add one team under an existing username login."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()

        # Only username logins have teams. Person key logins do not.
        if CONF_USERNAME not in entry.data:
            return self.async_abort(reason="not_supported")

        errors: dict[str, str] = {}
        if user_input is not None:
            team = _clean_slug(user_input[CONF_TEAM_SLUG])
            if any(sub.unique_id == team for sub in entry.subentries.values()):
                return self.async_abort(reason="already_configured")
            try:
                await _async_check_login(
                    entry.data[CONF_DOMAIN],
                    team,
                    entry.data[CONF_USERNAME],
                    entry.data[CONF_PASSWORD],
                )
            except SvenskalagAuthError:
                errors["base"] = "invalid_auth"
            except SvenskalagError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=team,
                    data={CONF_TEAM_SLUG: team},
                    unique_id=team,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_TEAM_SCHEMA, errors=errors
        )


class SvenskalagOptionsFlow(OptionsFlow):
    """Set how often data is fetched."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options.get(CONF_UPDATE_HOURS, DEFAULT_UPDATE_HOURS)
        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_HOURS, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=24)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

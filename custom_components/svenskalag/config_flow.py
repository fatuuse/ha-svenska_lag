"""Config flow for Svenskalag. Supports person key or username and password."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
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
)
from .web_client import SvenskalagWebClient

STEP_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})

STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DOMAIN): str,
        vol.Required(CONF_TEAM_SLUG): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_PASSWORD_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _clean_domain(value: str) -> str:
    value = value.strip()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.strip("/")


def _person_name(raw: dict[str, Any]) -> str:
    person = raw.get("person") or {}
    name = " ".join(p for p in (person.get("firstName"), person.get("lastName")) if p)
    return name.strip() or "Okänd"


class SvenskalagConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Svenskalag."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SvenskalagOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["credentials", "token"])

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
                return await self._async_create(
                    title=f"Svenskalag – {name}",
                    unique_id=name.lower(),
                    data={CONF_TOKEN: token},
                )
        return self.async_show_form(step_id="token", data_schema=STEP_TOKEN_SCHEMA, errors=errors)

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            domain = _clean_domain(user_input[CONF_DOMAIN])
            team = user_input[CONF_TEAM_SLUG].strip().strip("/")
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            try:
                await self._async_validate_credentials(domain, team, username, password)
            except SvenskalagAuthError:
                errors["base"] = "invalid_auth"
            except SvenskalagError:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_create(
                    title=f"Svenskalag – {username} ({team})",
                    unique_id=f"{domain}/{team}/{username}".lower(),
                    data={
                        CONF_DOMAIN: domain,
                        CONF_TEAM_SLUG: team,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )
        return self.async_show_form(
            step_id="credentials", data_schema=STEP_CREDENTIALS_SCHEMA, errors=errors
        )

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
                    await self._async_validate_credentials(
                        entry.data[CONF_DOMAIN],
                        entry.data[CONF_TEAM_SLUG],
                        entry.data[CONF_USERNAME],
                        password,
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

    async def _async_create(self, title: str, unique_id: str, data: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data=data)

    async def _async_validate_token(self, token: str) -> str:
        api = SvenskalagApi(async_get_clientsession(self.hass), token)
        today = dt_util.now().date()
        raw = await api.async_get_my_activities(today, today)
        return _person_name(raw)

    async def _async_validate_credentials(
        self, domain: str, team: str, username: str, password: str
    ) -> None:
        session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
        try:
            client = SvenskalagWebClient(session, domain, team, username, password)
            await client.async_login()
        finally:
            await session.close()


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

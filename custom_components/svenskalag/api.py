"""Minimal async client for the Svenskalag API (person key / Connection auth)."""

from __future__ import annotations

from datetime import date
from typing import Any

import aiohttp

from .const import API_BASE_URL


class SvenskalagError(Exception):
    """Generic communication error."""


class SvenskalagAuthError(SvenskalagError):
    """The token was rejected."""


class SvenskalagApi:
    """Wraps the endpoints we need."""

    def __init__(self, session: aiohttp.ClientSession, token: str) -> None:
        self._session = session
        self._token = token

    async def async_get_my_activities(self, start: date, end: date) -> dict[str, Any]:
        """Return person + activities between start and end (inclusive)."""
        return await self._get(
            "/me/activities",
            params={"from": start.isoformat(), "to": end.isoformat()},
        )

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.get(
                f"{API_BASE_URL}{path}",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status in (401, 403):
                    raise SvenskalagAuthError(f"Token rejected ({resp.status})")
                resp.raise_for_status()
                return await resp.json()
        except SvenskalagError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SvenskalagError(f"Request to {path} failed: {err}") from err

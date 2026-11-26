"""Data coordinator for Svenskalag."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SvenskalagAuthError, SvenskalagError
from .const import (
    ACTIVE_AFTER,
    ACTIVE_BEFORE,
    ACTIVE_INTERVAL,
    CONF_UPDATE_HOURS,
    DAYS_AHEAD,
    DEFAULT_UPDATE_HOURS,
    DOMAIN,
)
from .membership import card_valid_until, current_period, parse_iso
from .statistics import async_import_activity_stats

_LOGGER = logging.getLogger(__name__)


@dataclass
class SvenskalagData:
    """Processed data shared by all entities."""

    person_name: str
    activities: list[dict[str, Any]] = field(default_factory=list)
    next_activity: dict[str, Any] | None = None
    next_training: dict[str, Any] | None = None
    next_match: dict[str, Any] | None = None
    upcoming_count: int = 0
    needs_reply: list[dict[str, Any]] = field(default_factory=list)
    membership_period_name: str | None = None
    membership_period_end: datetime | None = None
    card_valid_until: datetime | None = None


def _parse(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    reply = raw.get("reply") or {}
    invitation = raw.get("invitation") or {}
    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "type": raw.get("typeName"),
        "team": raw.get("teamName"),
        "is_game": raw.get("isGame", False),
        "opponent": raw.get("opponent"),
        "is_home": raw.get("isHome"),
        "start": _parse(raw.get("startsAt")),
        "end": _parse(raw.get("endsAt")),
        "location": raw.get("location"),
        "gathering_at": _parse(raw.get("gatheringAt")),
        "gathering_location": raw.get("gatheringLocation"),
        "cancelled": raw.get("isCancelled", False),
        "postponed": raw.get("isPostponed", False),
        "reply_deadline": _parse(raw.get("replyDeadline")),
        "attending": reply.get("attending"),
        "replied_at": _parse(reply.get("repliedAt")),
        "invited_at": _parse(invitation.get("invitedAt")),
        "recipients": invitation.get("recipients"),
        "invitation_message": invitation.get("message"),
        "type_id": raw.get("typeId"),
        "team_id": raw.get("teamId"),
        "reply_comment": reply.get("comment"),
        "reply_url": invitation.get("replyUrl"),
        "web_url": raw.get("webUrl"),
        "attending_count": raw.get("attendingCount"),
    }


class SvenskalagCoordinator(DataUpdateCoordinator[SvenskalagData]):
    """Fetches activities, derives sensor values, and writes statistics."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: Any,
        subentry_id: str | None,
        team_slug: str | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=self._configured_hours(entry)),
        )
        self.api = api
        self.subentry_id = subentry_id
        self.team_slug = team_slug
        # Keys statistics and entity ids. Person key logins have no subentry.
        self.stats_key = subentry_id or entry.entry_id

    @staticmethod
    def _configured_hours(entry: ConfigEntry) -> int:
        return int(entry.options.get(CONF_UPDATE_HOURS, DEFAULT_UPDATE_HOURS))

    def _next_interval(self, activities: list[dict[str, Any]]) -> timedelta:
        """Poll often while an activity is running or about to start."""
        now = dt_util.now()
        for activity in activities:
            if activity["cancelled"] or activity["start"] is None:
                continue
            end = activity["end"] or activity["start"]
            if activity["start"] - ACTIVE_BEFORE <= now <= end + ACTIVE_AFTER:
                return ACTIVE_INTERVAL
        return timedelta(hours=self._configured_hours(self.config_entry))

    async def _async_update_data(self) -> SvenskalagData:
        today = dt_util.now().date()
        try:
            raw = await self.api.async_get_my_activities(
                today - timedelta(days=1),
                today + timedelta(days=DAYS_AHEAD),
            )
        except SvenskalagAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SvenskalagError as err:
            raise UpdateFailed(str(err)) from err

        data = self._process(raw)
        (
            data.membership_period_name,
            data.membership_period_end,
            data.card_valid_until,
        ) = await self._async_fetch_membership()
        self.update_interval = self._next_interval(data.activities)
        _LOGGER.debug(
            "Update done: %d activities, %d upcoming, %d need reply, next update in %s",
            len(data.activities), data.upcoming_count, len(data.needs_reply), self.update_interval,
        )

        try:
            async_import_activity_stats(self.hass, self.stats_key, data.activities)
        except Exception:  # statistics must not break sensors
            _LOGGER.exception("Could not write statistics")
        return data

    async def _async_fetch_membership(
        self,
    ) -> tuple[str | None, datetime | None, datetime | None]:
        """Membership periods are only available with a person key. Other clients return nothing."""
        fetch = getattr(self.api, "async_get_membership_periods", None)
        if fetch is None:
            return None, None, None
        try:
            raw = await fetch()
        except SvenskalagError as err:
            _LOGGER.warning("Could not read membership periods: %s", err)
            return None, None, None
        periods = raw.get("membershipPeriods") or []
        now = dt_util.now()
        period = current_period(periods, now)
        if period is None:
            return None, None, card_valid_until(periods, now)
        return (
            period.get("name"),
            parse_iso(period.get("endDate")),
            card_valid_until(periods, now),
        )

    @staticmethod
    def _process(raw: dict[str, Any]) -> SvenskalagData:
        now = dt_util.now()
        person = raw.get("person") or {}
        name = " ".join(
            p for p in (person.get("firstName"), person.get("lastName")) if p
        ).strip() or "Okänd"

        activities = sorted(
            (_normalize(a) for a in raw.get("activities", [])),
            key=lambda a: a["start"] or now,
        )

        upcoming = [
            a for a in activities
            if a["start"] and a["start"] >= now and not a["cancelled"]
        ]

        needs_reply = [
            a for a in upcoming
            if a["attending"] is None
            and a["reply_deadline"] is not None
            and a["reply_deadline"] > now
        ]

        return SvenskalagData(
            person_name=name,
            activities=activities,
            next_activity=upcoming[0] if upcoming else None,
            next_training=next((a for a in upcoming if not a["is_game"]), None),
            next_match=next((a for a in upcoming if a["is_game"]), None),
            upcoming_count=len(upcoming),
            needs_reply=needs_reply,
        )

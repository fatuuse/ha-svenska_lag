"""Sensors for Svenskalag."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DAYS_AHEAD
from .coordinator import SvenskalagCoordinator
from .entity import SvenskalagEntity, activity_attributes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    for subentry_id, coordinator in entry.runtime_data.items():
        entities: list[SensorEntity] = [
            NextActivitySensor(coordinator),
            UpcomingCountSensor(coordinator),
            NextAttendanceSensor(coordinator, "next_training_attendance", lambda d: d.next_training),
            NextAttendanceSensor(coordinator, "next_match_attendance", lambda d: d.next_match),
        ]
        entities += [
            NextInvitationSensor(coordinator, "next_training_invited", lambda d: d.next_training, "invited"),
            NextInvitationSensor(coordinator, "next_training_not_attending", lambda d: d.next_training, "not_attending"),
            NextInvitationSensor(coordinator, "next_match_invited", lambda d: d.next_match, "invited"),
            NextInvitationSensor(coordinator, "next_match_not_attending", lambda d: d.next_match, "not_attending"),
        ]
        if getattr(coordinator.api, "supports_replies", False):
            entities.append(UnansweredInvitationsSensor(coordinator))
        if hasattr(coordinator.api, "async_get_membership_periods"):
            entities += [
                MembershipDateSensor(coordinator, "membership_period_end", lambda d: d.membership_period_end),
                MembershipDateSensor(coordinator, "card_valid_until", lambda d: d.card_valid_until),
            ]
        async_add_entities(entities, config_subentry_id=subentry_id or None)

class NextActivitySensor(SvenskalagEntity, SensorEntity):
    """Timestamp of the next activity, with details as attributes."""

    _attr_translation_key = "next_activity"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "next_activity")

    @property
    def native_value(self):
        nxt = self.coordinator.data.next_activity
        return nxt["start"] if nxt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        nxt = self.coordinator.data.next_activity
        return activity_attributes(nxt) if nxt else None


class UpcomingCountSensor(SvenskalagEntity, SensorEntity):
    """Number of upcoming (non-cancelled) activities in the fetch window."""

    _attr_translation_key = "upcoming_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "upcoming_count")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.upcoming_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"days_ahead": DAYS_AHEAD}


class NextAttendanceSensor(SvenskalagEntity, SensorEntity):
    """Number of people who answered yes to the next training or match."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SvenskalagCoordinator, key: str, pick) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._pick = pick

    @property
    def _activity(self) -> dict[str, Any] | None:
        return self._pick(self.coordinator.data)

    @property
    def native_value(self) -> int | None:
        activity = self._activity
        return activity["attending_count"] if activity else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        activity = self._activity
        if not activity:
            return None
        return {
            "title": activity["title"],
            "starts_at": activity["start"].isoformat() if activity["start"] else None,
            "location": activity["location"],
            "invited_at": activity["invited_at"].isoformat() if activity["invited_at"] else None,
        }



class MembershipDateSensor(SvenskalagEntity, SensorEntity):
    """A date from the membership periods: when the current period or the card ends."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SvenskalagCoordinator, key: str, pick) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._pick = pick

    @property
    def native_value(self):
        return self._pick(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        name = self.coordinator.data.membership_period_name
        return {"period": name} if name else None


class NextInvitationSensor(SvenskalagEntity, SensorEntity):
    """Invited count, or people invited but not yet attending, for the next training or match.

    "not_attending" is invited minus the yes answers. The page only lists yes answers,
    so people who answered no are included in this number.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SvenskalagCoordinator, key: str, pick, mode: str) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._pick = pick
        self._mode = mode

    @property
    def _activity(self) -> dict[str, Any] | None:
        return self._pick(self.coordinator.data)

    @property
    def native_value(self) -> int | None:
        activity = self._activity
        if not activity:
            return None
        if self._mode == "invited":
            return activity["recipients"]
        invited, attending = activity["recipients"], activity["attending_count"]
        if invited is None or attending is None:
            return None
        return max(invited - attending, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        activity = self._activity
        if not activity:
            return None
        return {
            "title": activity["title"],
            "starts_at": activity["start"].isoformat() if activity["start"] else None,
            "invited_at": activity["invited_at"].isoformat() if activity["invited_at"] else None,
            "invited": activity["recipients"],
            "attending": activity["attending_count"],
        }


class UnansweredInvitationsSensor(SvenskalagEntity, SensorEntity):
    """Upcoming invitations the person has not answered yet, before the reply deadline."""

    _attr_translation_key = "unanswered_invitations"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SvenskalagCoordinator) -> None:
        super().__init__(coordinator, "unanswered_invitations")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.needs_reply)

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

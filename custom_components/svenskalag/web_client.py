"""Username and password access to a Svenskalag team site.

Mirrors the scraper's flow: log in through the team's /logga-in form, read
the team's monthly calendar pages for activity links, and read each activity
page. The activity page carries its data as JSON inside
data-ng-init="vm.init({...})". That JSON has the series settings and a
"schedules" list with one entry per occurrence, including invitation status.

This is web scraping, not a documented API, so it may break if the site
changes.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from homeassistant.util import dt as dt_util

from .api import SvenskalagAuthError, SvenskalagError

_LOGGER = logging.getLogger(__name__)

# URL month names. Hardcoded so the system locale does not matter.
MONTHS_SV = (
    "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december",
)

# eventTypeId values, taken from the activity edit form.
EVENT_TYPES = {
    1: "Träning", 5: "Tävling", 6: "Cup", 10: "Läger",
    2: "Möte", 8: "Utbildning", 9: "Arbetspass", 4: "Övrigt",
}

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input",
     "link", "meta", "source", "track", "wbr"}
)

_INIT_RE = re.compile(r"^\s*vm\.init\((.*)\)\s*;?\s*$", re.DOTALL)
_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


class _PageParser(HTMLParser):
    """Collects team activity links and the <body> attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self.body_attrs: dict[str, str | None] = {}
        self.activity_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "body" and not self.body_attrs:
            self.body_attrs = attr
        # Same selector as the scraper: .//td/a[@class="invisible-link"]
        if (
            tag == "a"
            and attr.get("class") == "invisible-link"
            and "td" in self._stack
            and attr.get("href")
        ):
            self.activity_hrefs.append(attr["href"])
        if tag not in VOID_TAGS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._stack:
            idx = len(self._stack) - 1 - self._stack[::-1].index(tag)
            del self._stack[idx:]


def _is_own_activity_link(url: str, team_slug: str) -> bool:
    """True only for links to this team's own activities.

    Calendar pages also link to other teams (opponents, shared events). Those
    links have other team slugs as their first path segment, so they are
    rejected here. An activity link must also end with a numeric id.
    """
    parts = [part for part in urlparse(url).path.split("/") if part]
    return len(parts) >= 2 and parts[0] == team_slug and parts[-1].isdigit()


def _to_aware_iso(value: Any, tz) -> str | None:
    """Parse a timestamp from the site and return it as ISO 8601 with timezone."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.isoformat()


def _months_in_window(today: date) -> list[tuple[int, int]]:
    """Previous month through two months ahead, as (year, month)."""
    months: list[tuple[int, int]] = []
    for offset in range(-1, 3):
        year, month = today.year, today.month + offset
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        months.append((year, month))
    return months


def _parse_activity_page(html: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (series settings, schedules) from an activity edit page."""
    parser = _PageParser()
    parser.feed(html)
    init = parser.body_attrs.get("data-ng-init")
    if not init:
        raise SvenskalagError("data-ng-init missing on activity page")
    match = _INIT_RE.match(init)
    if not match:
        raise SvenskalagError("data-ng-init has an unexpected format")
    try:
        data = json.loads(match.group(1))
    except ValueError as err:
        raise SvenskalagError(f"data-ng-init is not valid JSON: {err}") from err
    schedules = data.get("schedules")
    if not isinstance(schedules, list):
        raise SvenskalagError("data-ng-init has no schedules list")
    return data, schedules


def _map_schedule(
    series: dict[str, Any],
    schedule: dict[str, Any],
    team_slug: str,
    is_game: bool,
    web_url: str,
    tz,
) -> dict[str, Any] | None:
    """Convert one occurrence in a series into the API's activity shape."""
    start = _to_aware_iso(schedule.get("scheduleDate"), tz)
    if start is None:
        return None
    start_dt = datetime.fromisoformat(start)

    gathering_at = None
    gathering_minutes = series.get("gatheringTime")
    if isinstance(gathering_minutes, str) and gathering_minutes.isdigit():
        gathering_at = (start_dt - timedelta(minutes=int(gathering_minutes))).isoformat()

    recipients = schedule.get("recipients")
    return {
        "id": schedule.get("id"),
        "title": schedule.get("text") or series.get("scheduleText"),
        "typeName": EVENT_TYPES.get(series.get("eventTypeId")),
        "teamName": team_slug,
        "isGame": is_game,
        "opponent": series.get("opponent"),
        "isHome": series.get("isHomeMatch"),
        "startsAt": start,
        "endsAt": _to_aware_iso(schedule.get("scheduleToDate"), tz) or start,
        "location": schedule.get("place") or series.get("place"),
        "gatheringAt": gathering_at,
        "gatheringLocation": series.get("gatheringPlace") or None,
        "isCancelled": False,
        "isPostponed": False,
        # Left out: the site's "reply by" setting is relative and not yet mapped.
        "replyDeadline": None,
        "reply": None,
        "webUrl": web_url,
        "invitation": {
            "invitedAt": _to_aware_iso(schedule.get("firstInvite"), tz),
            "secondInviteAt": _to_aware_iso(schedule.get("secondInvite"), tz),
            "recipients": len(recipients) if isinstance(recipients, list) else None,
        },
        # Filled in for upcoming activities from the presence page.
        "attendingCount": None,
    }


_ATTENDING_MEMBERS_RE = re.compile(
    r"""["']?attendingMembers["']?\s*[:=]\s*\[""",
    re.IGNORECASE,
)


def _find_matching_bracket(text: str, start: int, opening: str = "[", closing: str = "]") -> int | None:
    """Return the index of the bracket that closes the one at `start`, or None."""
    depth = 0
    quote: str | None = None
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if char in ("'", '"'):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if quote is not None:
            continue

        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index

    return None


def _count_top_level_entries(text: str) -> int:
    """Count entries in an array body. Commas inside nested [] or {} are ignored.

    A trailing comma does not add an entry.
    """
    if not text.strip():
        return 0

    count = 1
    bracket_depth = 0
    brace_depth = 0
    quote: str | None = None
    escaped = False
    last_significant = ""

    for char in text:
        if escaped:
            escaped = False
            last_significant = char
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if char in ("'", '"'):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            last_significant = char
            continue
        if quote is not None:
            continue

        if char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
        elif char == "," and bracket_depth == 0 and brace_depth == 0:
            count += 1

        if not char.isspace():
            last_significant = char

    if last_significant == "," and bracket_depth == 0 and brace_depth == 0:
        count -= 1
    return count


def _parse_attending_count(html: str) -> tuple[int | None, list[str]]:
    """Return (number attending, found keys) from the presence page.

    Looks for the attendingMembers array in the head scripts and counts its
    top-level entries. This is not a JavaScript parser. Returns (None, []) if
    the field is missing, and (None, [...]) if the array is incomplete.
    """
    head = html.split("</head>", 1)[0]

    for match in _SCRIPT_RE.finditer(head):
        script = match.group(1)
        member_match = _ATTENDING_MEMBERS_RE.search(script)
        if not member_match:
            continue

        # The match ends just after the opening bracket.
        array_start = member_match.end() - 1
        array_end = _find_matching_bracket(script, array_start)
        if array_end is None:
            return None, ["attendingMembers"]

        array_content = script[array_start + 1:array_end]
        return _count_top_level_entries(array_content), ["attendingMembers"]

    return None, []

class SvenskalagWebClient:
    """Logs in with username and password and reads the team pages."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        domain: str,
        team_slug: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._domain = domain
        self._team_slug = team_slug
        self._username = username
        self._password = password
        self._logged_in = False

    def _url(self, path: str) -> str:
        return f"https://{self._domain}/{self._team_slug}/{path}"

    def _month_url(self, year: int, month: int) -> str:
        return self._url(f"kalender/{year}/{MONTHS_SV[month - 1]}")

    async def _fetch(self, url: str, post_data: dict[str, str] | None = None) -> tuple[str, str]:
        """Return (final_url, body). Raises SvenskalagError on failure."""
        timeout = aiohttp.ClientTimeout(total=30)
        method = "GET" if post_data is None else "POST"
        started = time.monotonic()
        try:
            request = (
                self._session.get(url, timeout=timeout)
                if post_data is None
                else self._session.post(url, data=post_data, timeout=timeout)
            )
            async with request as resp:
                text = await resp.text()
                _LOGGER.debug(
                    "%s %s -> %s, %d bytes, %.0f ms",
                    method, url, resp.status, len(text),
                    (time.monotonic() - started) * 1000,
                )
                if resp.status >= 400:
                    raise SvenskalagError(f"HTTP {resp.status} from {url}")
                return str(resp.url), text
        except SvenskalagError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SvenskalagError(f"Request to {url} failed: {err}") from err

    @staticmethod
    def _is_authenticated(final_url: str, html: str) -> bool:
        # Same check as the scraper: a logged-in page has "Logga ut" and is not the login URL.
        return "Logga ut" in html and "logga-in" not in final_url.lower()

    async def async_login(self) -> None:
        self._logged_in = False
        _, body = await self._fetch(
            self._url("logga-in"),
            post_data={"UserName": self._username, "UserPass": self._password},
        )
        try:
            payload = json.loads(body)
        except ValueError as err:
            raise SvenskalagError("Login response was not JSON") from err
        if isinstance(payload, dict) and payload.get("error"):
            raise SvenskalagAuthError(str(payload["error"]))

        today = dt_util.now().date()
        final_url, html = await self._fetch(self._month_url(today.year, today.month))
        if not self._is_authenticated(final_url, html):
            raise SvenskalagAuthError("Login was not accepted by the site")
        self._logged_in = True
        _LOGGER.debug("Login accepted for team %s on %s", self._team_slug, self._domain)

    async def _fetch_month_links(self, year: int, month: int) -> list[str]:
        url = self._month_url(year, month)
        final_url, html = await self._fetch(url)
        if not self._is_authenticated(final_url, html):
            # The session may have expired. Log in once more and retry.
            await self.async_login()
            final_url, html = await self._fetch(url)
            if not self._is_authenticated(final_url, html):
                raise SvenskalagAuthError("Session is not authenticated")

        parser = _PageParser()
        parser.feed(html)
        links = {urljoin(final_url, href) for href in parser.activity_hrefs}
        own = [link for link in links if _is_own_activity_link(link, self._team_slug)]
        _LOGGER.debug(
            "Month %d-%02d: %d links, %d for this team",
            year, month, len(links), len(own),
        )
        return sorted(own)

    async def _async_attending_count(self, activity_id: int) -> int | None:
        url = self._url(f"controlpanel/presence/chooseparticipants/{activity_id}")
        try:
            _, html = await self._fetch(url)
        except SvenskalagError as err:
            _LOGGER.warning("Could not read attendance for activity %s: %s", activity_id, err)
            return None
        count, keys = _parse_attending_count(html)
        _LOGGER.debug("Attendance for activity %s: %s (initData keys: %s)", activity_id, count, keys)
        if count is None:
            _LOGGER.warning(
                "No attendingMembers for activity %s. initData keys found: %s",
                activity_id, keys,
            )
        return count

    async def async_get_my_activities(self, start: date, end: date) -> dict[str, Any]:
        """Return activities in the same shape as the /me/activities API."""
        if not self._logged_in:
            await self.async_login()

        today = dt_util.now().date()
        tz = dt_util.get_default_time_zone()

        urls: set[str] = set()
        for year, month in _months_in_window(today):
            urls.update(await self._fetch_month_links(year, month))

        _LOGGER.debug("Calendar links found across %d months: %d", len(_months_in_window(today)), len(urls))

        # One series page covers every occurrence in its series, so skip links
        # whose id has already been seen as an occurrence.
        seen_ids: set[int] = set()
        activities: list[dict[str, Any]] = []
        for url in sorted(urls):
            activity_id = [part for part in url.split("/") if part][-1]
            if activity_id.isdigit() and int(activity_id) in seen_ids:
                _LOGGER.debug("Activity %s already covered by a series page", activity_id)
                continue

            is_game = "/match/" in url
            edit_url = (
                self._url(f"match/redigera/{activity_id}")
                if is_game
                else self._url(f"kalender/redigera-aktivitet/{activity_id}")
            )
            try:
                _, page = await self._fetch(edit_url)
                series, schedules = _parse_activity_page(page)
                _LOGGER.debug("Activity %s: %d occurrences in series", activity_id, len(schedules))
            except SvenskalagError as err:
                _LOGGER.warning("Skipping activity %s: %s", activity_id, err)
                continue

            for schedule in schedules:
                if isinstance(schedule.get("id"), int):
                    seen_ids.add(schedule["id"])
                mapped = _map_schedule(series, schedule, self._team_slug, is_game, url, tz)
                if mapped is None:
                    continue
                day = datetime.fromisoformat(mapped["startsAt"]).date()
                if start <= day <= end:
                    activities.append(mapped)

        # Attendance is only read for upcoming activities, to limit requests.
        now = dt_util.now()
        for activity in activities:
            if activity["isCancelled"] or datetime.fromisoformat(activity["startsAt"]) < now:
                continue
            activity["attendingCount"] = await self._async_attending_count(activity["id"])

        _LOGGER.debug(
            "Fetched %d activities in range %s to %s", len(activities), start, end,
        )
        return {
            "person": {"firstName": self._username, "lastName": ""},
            "activities": activities,
        }

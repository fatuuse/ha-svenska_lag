"""Tests for the attendingMembers parser in web_client.py.

Runs with pytest, or directly with: python3 tests/test_presence_parser.py
Home Assistant and aiohttp are stubbed if they are not installed, so the
parser can be tested on its own.
"""

from __future__ import annotations

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "custom_components" / "svenskalag"


def _load_web_client():
    try:
        import homeassistant.util.dt  # noqa: F401
    except ImportError:
        ha = types.ModuleType("homeassistant")
        util = types.ModuleType("homeassistant.util")
        dt = types.ModuleType("homeassistant.util.dt")
        dt.now = lambda: None
        dt.get_default_time_zone = lambda: None
        dt.parse_datetime = lambda value: None
        util.dt = dt
        sys.modules.update({
            "homeassistant": ha,
            "homeassistant.util": util,
            "homeassistant.util.dt": dt,
        })
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        aiohttp = types.ModuleType("aiohttp")
        aiohttp.ClientError = type("ClientError", (Exception,), {})
        aiohttp.ClientSession = object
        aiohttp.ClientTimeout = lambda **kwargs: None
        aiohttp.CookieJar = object
        sys.modules["aiohttp"] = aiohttp

    # Load the package without running its __init__.py (which needs Home Assistant).
    pkg = types.ModuleType("svenskalag")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules.setdefault("svenskalag", pkg)
    from svenskalag import web_client
    return web_client


wc = _load_web_client()


def _page(script: str) -> str:
    return f"<html><head><script>{script}</script></head><body></body></html>"


# --- Missing or empty ---------------------------------------------------------

def test_missing_field_returns_none():
    assert wc._parse_attending_count(_page("var x = {other: [1, 2]};")) == (None, [])


def test_no_scripts_returns_none():
    assert wc._parse_attending_count("<html><head></head><body></body></html>") == (None, [])


def test_empty_array_returns_zero():
    html = _page('var initData = {"attendingMembers": []};')
    assert wc._parse_attending_count(html) == (0, ["attendingMembers"])


def test_empty_array_with_whitespace_returns_zero():
    html = _page("var initData = { attendingMembers: [   \n  ] };")
    assert wc._parse_attending_count(html) == (0, ["attendingMembers"])


# --- Array styles -------------------------------------------------------------

def test_json_string_array():
    html = _page('var initData = {"attendingMembers": ["Anna", "Erik"]};')
    assert wc._parse_attending_count(html) == (2, ["attendingMembers"])


def test_js_single_quoted_array():
    html = _page("var initData = {attendingMembers: ['Anna', 'Erik', 'Bo']};")
    assert wc._parse_attending_count(html) == (3, ["attendingMembers"])


def test_js_objects_without_quotes_on_keys():
    html = _page('var initData = {attendingMembers: [{id: 1, name: "A"}, {id: 2, name: "B"}]};')
    assert wc._parse_attending_count(html) == (2, ["attendingMembers"])


def test_objects_with_commas_inside_strings_and_nested_arrays():
    html = _page(
        'var initData = {attendingMembers: ['
        '{id: 1, name: "Andersson, Anna", tags: [1, 2, 3]}, '
        "{id: 2, name: 'Berg, Bo', tags: []}"
        ']};'
    )
    assert wc._parse_attending_count(html) == (2, ["attendingMembers"])


def test_escaped_quote_inside_string_does_not_end_string_early():
    html = _page(r'var initData = {attendingMembers: ["Say \"hi, there\"", "Erik"]};')
    assert wc._parse_attending_count(html) == (2, ["attendingMembers"])


def test_trailing_comma_does_not_add_entry():
    html = _page('var initData = {attendingMembers: ["Anna", "Erik",]};')
    assert wc._parse_attending_count(html) == (2, ["attendingMembers"])


def test_single_entry():
    html = _page('var initData = {attendingMembers: [{id: 7}]};')
    assert wc._parse_attending_count(html) == (1, ["attendingMembers"])


# --- Surrounding data ---------------------------------------------------------

def test_other_fields_before_attending_members():
    html = _page(
        'var initData = {'
        'lastPresenceTimes: ["0-m", "end", "15-m"], '
        'placeAreas: {}, '
        'subGroups: [{id: 1, name: "P15, Grupp", memberCount: 3}], '
        'attendingMembers: [{id: 1}, {id: 2}, {id: 3}], '
        'notAttending: [{id: 9}]'
        '};'
    )
    assert wc._parse_attending_count(html) == (3, ["attendingMembers"])


def test_field_in_second_script_tag():
    html = (
        "<html><head>"
        "<script>var a = 1;</script>"
        '<script>var initData = {attendingMembers: [{id: 1}]};</script>'
        "</head><body></body></html>"
    )
    assert wc._parse_attending_count(html) == (1, ["attendingMembers"])


def test_field_only_in_body_is_ignored():
    html = (
        "<html><head></head><body>"
        '<script>var initData = {attendingMembers: [{id: 1}]};</script>'
        "</body></html>"
    )
    assert wc._parse_attending_count(html) == (None, [])


# --- Incomplete input ---------------------------------------------------------

def test_incomplete_array_returns_none_count():
    html = _page('var initData = {attendingMembers: [{id: 1}, {id: 2}')
    count, keys = wc._parse_attending_count(html)
    assert count is None
    assert keys == ["attendingMembers"]


def test_unclosed_string_returns_none_count():
    html = _page('var initData = {attendingMembers: ["Anna, Erik]};')
    count, _ = wc._parse_attending_count(html)
    assert count is None


# --- Helpers ------------------------------------------------------------------

def test_find_matching_bracket_ignores_brackets_in_strings():
    text = '[ "a]b", [1, 2] ]'
    assert wc._find_matching_bracket(text, 0) == len(text) - 1


def test_count_top_level_entries_ignores_nested_commas():
    assert wc._count_top_level_entries('{a: 1, b: 2}, [1, 2, 3], "x, y"') == 3



# --- Link parsing ------------------------------------------------------------

TEAM = "ingaroif-innebandy-innebandyp2015"


def test_training_link_gives_id_and_not_match():
    url = f"/{TEAM}/aktivitet/21184290/traning"
    assert wc._activity_from_link(url, TEAM) == ("21184290", False)


def test_match_link_gives_id_and_match():
    url = f"/{TEAM}/match/21129150/alta-if"
    assert wc._activity_from_link(url, TEAM) == ("21129150", True)


def test_full_url_is_accepted():
    url = f"https://www.ingaroif.se/{TEAM}/aktivitet/21184256/traning"
    assert wc._activity_from_link(url, TEAM) == ("21184256", False)


def test_other_team_link_is_rejected():
    assert wc._activity_from_link("/alta-if/aktivitet/21184256/traning", TEAM) is None


def test_news_link_is_rejected():
    assert wc._activity_from_link(f"/{TEAM}/nyheter/2551451/hostens-traning", TEAM) is None


def test_non_numeric_id_is_rejected():
    assert wc._activity_from_link(f"/{TEAM}/aktivitet/abc/traning", TEAM) is None


# --- Activity pages -----------------------------------------------------------

def test_match_page_without_schedules_list_is_one_occurrence():
    init = (
        'vm.init({&quot;scheduleId&quot;:21129154,&quot;scheduleText&quot;:&quot;Match mot V&#228;rmd&#246; IF&quot;,'
        '&quot;eventTypeId&quot;:7,&quot;place&quot;:&quot;V&#228;rmd&#246; sporthall&quot;,'
        '&quot;scheduleDate&quot;:&quot;2026-11-21&quot;,&quot;startTime&quot;:&quot;09:15&quot;,'
        '&quot;endTime&quot;:&quot;10:00&quot;,&quot;gatheringTime&quot;:&quot;30&quot;,'
        '&quot;schedules&quot;:null,&quot;opponent&quot;:&quot;V&#228;rmd&#246; IF&quot;})'
    )
    html = f'<html><body data-ng-init="{init}"></body></html>'
    series, schedules = wc._parse_activity_page(html)
    assert len(schedules) == 1
    assert schedules[0]["id"] == 21129154
    assert schedules[0]["scheduleDate"] == "2026-11-21T09:15:00"
    assert schedules[0]["scheduleToDate"] == "2026-11-21T10:00:00"
    assert schedules[0]["text"] == "Match mot V\u00e4rmd\u00f6 IF"
    mapped = wc._map_schedule(series, schedules[0], "ingaroif-innebandy-innebandyp2015",
                              True, "https://example.se/x/match/21129154", None)
    assert mapped["typeName"] == "Match"
    assert mapped["isGame"] is True


def test_page_with_neither_schedules_nor_date_still_fails():
    html = '<html><body data-ng-init="vm.init({&quot;scheduleId&quot;:1})"></body></html>'
    try:
        wc._parse_activity_page(html)
    except wc.SvenskalagError:
        return
    raise AssertionError("expected SvenskalagError")



# --- Attendance breakdown (players vs leaders) --------------------------------

def test_breakdown_splits_leaders_and_players_by_type_id():
    html = _page(
        "var initData = {attendingMembers: ["
        "{id: 1, memberTypeIds: [1]}, "
        "{id: 2, memberTypeIds: [2]}, "
        "{id: 3, memberTypeIds: [1, 2]}"
        "]};"
    )
    result = wc._parse_attendance_breakdown(html)
    assert result == {"total": 3, "leaders": 2, "players": 1, "fields": ["id", "memberTypeIds"]}


def test_breakdown_reads_member_type_objects():
    html = _page(
        "var initData = {attendingMembers: ["
        '{id: 1, memberTypes: [{id: 2, name: "Ledare"}]}, '
        '{id: 2, memberTypes: [{id: 1, name: "Spelare"}]}'
        "]};"
    )
    result = wc._parse_attendance_breakdown(html)
    assert result["leaders"] == 1
    assert result["players"] == 1


def test_breakdown_is_none_leaders_without_member_type_field():
    html = _page('var initData = {attendingMembers: [{id: 1, name: "A"}, {id: 2, name: "B, C"}]};')
    result = wc._parse_attendance_breakdown(html)
    assert result["total"] == 2
    assert result["leaders"] is None
    assert result["players"] is None


def test_breakdown_empty_array_is_all_zero():
    html = _page("var initData = {attendingMembers: []};")
    assert wc._parse_attendance_breakdown(html) == {
        "total": 0, "leaders": 0, "players": 0, "fields": [],
    }


def test_breakdown_missing_field_returns_none():
    assert wc._parse_attendance_breakdown(_page("var x = {other: [1, 2]};")) is None


def test_breakdown_handles_commas_and_escaped_quotes_in_strings():
    html = _page(
        'var initData = {attendingMembers: [{id: 1, name: "Andersson, Anna", memberTypeIds: [1]}, '
        r'{id: 2, name: "Say "hi, there"", memberTypeIds: [2]}]};'
    )
    result = wc._parse_attendance_breakdown(html)
    assert result["total"] == 2
    assert result["leaders"] == 1
    assert result["players"] == 1


def test_split_top_level_keeps_nested_commas_together():
    entries = wc._split_top_level('{a: 1, b: [1, 2]}, {a: 2, b: []}')
    assert len(entries) == 2



# --- Month range for the fetch window ------------------------------------------

def test_months_between_covers_a_season():
    from datetime import date
    months = wc._months_between(date(2026, 11, 25), date(2027, 5, 24))
    assert months[0] == (2026, 11)
    assert months[-1] == (2027, 5)
    assert len(months) == 7


def test_months_between_crosses_year_boundary():
    from datetime import date
    assert wc._months_between(date(2026, 12, 1), date(2027, 1, 31)) == [(2026, 12), (2027, 1)]


def test_months_between_single_month():
    from datetime import date
    assert wc._months_between(date(2026, 11, 1), date(2026, 11, 30)) == [(2026, 11)]



# --- Invite rows (kallelser) ---------------------------------------------------

def test_invites_latest_initial_send_gives_date_and_recipients():
    rows = [
        {"isSent": True, "isReminder": False, "date": "2026-10-17T10:14:05.52", "sentToAmount": 0},
        {"isSent": True, "isReminder": False, "date": "2026-11-10T21:57:48.983", "sentToAmount": 24},
    ]
    result = wc._summarize_invites(rows)
    assert result["invitedAt"] == "2026-11-10T21:57:48.983"
    assert result["recipients"] == 24
    assert result["reminders"] == 0
    assert result["plannedAt"] is None


def test_invites_reminders_are_counted_not_used_as_the_invite():
    rows = [
        {"isSent": True, "isReminder": False, "date": "2026-11-13T18:00:31.337", "sentToAmount": 26},
        {"isSent": True, "isReminder": True, "date": "2026-11-16T18:00:00", "sentToAmount": 5},
    ]
    result = wc._summarize_invites(rows)
    assert result["invitedAt"] == "2026-11-13T18:00:31.337"
    assert result["recipients"] == 26
    assert result["reminders"] == 1


def test_invites_planned_automatic_invite_is_the_next_unsent_row():
    rows = [
        {"isSent": False, "isReminder": False, "date": "2026-11-16T17:00:00", "sentToAmount": None},
        {"isSent": False, "isReminder": False, "date": "2026-11-23T17:00:00", "sentToAmount": None},
    ]
    result = wc._summarize_invites(rows)
    assert result["invitedAt"] is None
    assert result["recipients"] is None
    assert result["plannedAt"] == "2026-11-16T17:00:00"


def test_invites_empty_rows_give_nothing():
    assert wc._summarize_invites([]) == {
        "invitedAt": None, "recipients": None, "reminders": 0, "plannedAt": None,
    }


def test_map_schedule_prefers_invite_rows_over_schedule_fields():
    from datetime import timezone
    series = {"eventTypeId": 1, "gatheringTime": "0"}
    schedule = {"id": 21184299, "text": "Träning", "scheduleDate": "2026-12-03T17:00:00",
                "scheduleToDate": "2026-12-03T18:15:00", "place": "Skeppet",
                "firstInvite": 4320, "recipients": None}
    invite = {"invitedAt": "2026-11-30T17:00:00", "recipients": 26, "reminders": 0, "plannedAt": None}
    mapped = wc._map_schedule(series, schedule, "ingaroif-innebandy-innebandyp2015",
                              False, "https://example.se/x", timezone.utc, invite)
    assert mapped["invitation"]["invitedAt"] == "2026-11-30T17:00:00+00:00"
    assert mapped["invitation"]["recipients"] == 26


def test_map_schedule_without_invite_info_has_no_invited_date_from_minutes():
    from datetime import timezone
    series = {"eventTypeId": 1, "gatheringTime": "0"}
    schedule = {"id": 1, "text": "T", "scheduleDate": "2026-12-03T17:00:00",
                "scheduleToDate": "2026-12-03T18:15:00", "firstInvite": 4320}
    mapped = wc._map_schedule(series, schedule, "team", False, "u", timezone.utc, None)
    assert mapped["invitation"]["invitedAt"] is None


if __name__ == "__main__":
    failures = 0
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as err:
            failures += 1
            print(f"FAIL {name}: {err!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)

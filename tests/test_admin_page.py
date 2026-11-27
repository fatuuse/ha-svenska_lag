"""Tests for the admin page parser. Run with: python3 tests/test_admin_page.py"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "admin_page", ROOT / "custom_components" / "svenskalag" / "admin_page.py"
)
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)

SMS_TEXT = (
    '<p class="m-0 font-bold">158 gratis-SMS från Comviq kvar i november + 0 köpta SMS</p>'
)
DATA = (
    "<script>kit.start(app, element, {data:[null,null,"
    '{type:"data",data:{userInfo:{isAuthenticated:true,isAdmin:true},'
    "siteData:{myPagesMenu:{children:[{firstName:\"X\"}],expiredInvoices:0,pendingInvites:5,visibility:{}}}}},"
    '{type:"data",data:{systemNavigationCounters:{likelyDuplicatesCount:0,newApplicationCount:7,'
    "criminalRecordsCount:103}}}]})</script>"
)


def test_all_numbers_are_read():
    assert ap.parse_admin_page(SMS_TEXT + DATA) == {
        "sms_free": 158,
        "sms_bought": 0,
        "new_applications": 7,
        "pending_invites": 5,
    }


def test_logged_out_page_returns_none():
    page = SMS_TEXT + DATA.replace("isAuthenticated:true", "isAuthenticated:false")
    assert ap.parse_admin_page(page) is None


def test_missing_sms_text_still_gives_the_counters():
    result = ap.parse_admin_page(DATA)
    assert result["sms_free"] is None
    assert result["new_applications"] == 7
    assert result["pending_invites"] == 5


def test_html_entities_in_sms_text_are_handled():
    page = SMS_TEXT.replace("köpta", "k&#246;pta").replace("från", "fr&#229;n") + DATA
    assert ap.parse_admin_page(page)["sms_free"] == 158


def test_bought_sms_are_read():
    page = SMS_TEXT.replace("+ 0 köpta", "+ 40 köpta") + DATA
    assert ap.parse_admin_page(page)["sms_bought"] == 40


def test_authenticated_page_without_any_numbers_returns_none():
    assert ap.parse_admin_page("<script>{userInfo:{isAuthenticated:true}}</script>") is None


if __name__ == "__main__":
    failures = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as err:
            failures += 1
            print(f"FAIL {name}: {err!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)

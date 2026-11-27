"""Tests for the admin-only permission check around the send_sms service.

These exercise _async_handle_send_sms's permission and validation logic with
lightweight stand-ins for Home Assistant's hass/call objects, since the real
homeassistant package is not installed in this test environment. Run with:
python3 tests/test_send_sms_service.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "svenskalag"


def _install_ha_stubs():
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")

    config_entries = types.ModuleType("homeassistant.config_entries")
    class ConfigEntry:  # noqa: D401 - minimal stand-in
        pass
    config_entries.ConfigEntry = ConfigEntry

    const = types.ModuleType("homeassistant.const")
    class Platform:
        SENSOR = "sensor"; BINARY_SENSOR = "binary_sensor"; BUTTON = "button"; CALENDAR = "calendar"
    const.Platform = Platform

    core = types.ModuleType("homeassistant.core")
    class ServiceCall:
        def __init__(self, data, user_id=None):
            self.data = data
            self.context = types.SimpleNamespace(user_id=user_id)
    class HomeAssistant:
        pass
    core.ServiceCall = ServiceCall
    core.HomeAssistant = HomeAssistant

    exceptions = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    class ServiceValidationError(HomeAssistantError):
        pass
    class ConfigEntryError(HomeAssistantError):
        pass
    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ServiceValidationError = ServiceValidationError
    exceptions.ConfigEntryError = ConfigEntryError

    helpers = types.ModuleType("homeassistant.helpers")
    cv = types.ModuleType("homeassistant.helpers.config_validation")
    cv.string = str
    cv.boolean = bool
    dr_mod = types.ModuleType("homeassistant.helpers.device_registry")
    dr_mod.async_get = lambda hass: None
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    typing_mod = types.ModuleType("homeassistant.helpers.typing")
    typing_mod.ConfigType = dict

    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")
    dt.now = lambda: None
    dt.get_default_time_zone = lambda: None
    dt.parse_datetime = lambda v: None
    util.dt = dt

    sys.modules.update({
        "homeassistant": ha,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": const,
        "homeassistant.core": core,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.config_validation": cv,
        "homeassistant.helpers.device_registry": dr_mod,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
        "homeassistant.helpers.typing": typing_mod,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt,
    })

    # aiohttp stub, same as the other test files use
    if "aiohttp" not in sys.modules:
        aiohttp = types.ModuleType("aiohttp")
        aiohttp.ClientError = type("ClientError", (Exception,), {})
        aiohttp.ClientSession = object
        aiohttp.ClientTimeout = lambda **k: None
        aiohttp.CookieJar = object
        sys.modules["aiohttp"] = aiohttp

    if "voluptuous" not in sys.modules:
        vol = types.ModuleType("voluptuous")
        class Schema:
            def __init__(self, *a, **k): pass
        vol.Schema = Schema
        vol.Required = lambda key: key
        vol.In = lambda choices: choices
        vol.All = lambda *a: a
        vol.Length = lambda **k: k
        vol.Boolean = lambda: None
        sys.modules["voluptuous"] = vol


_install_ha_stubs()

pkg = types.ModuleType("svenskalag")
pkg.__path__ = [str(PKG)]
sys.modules.setdefault("svenskalag", pkg)

import svenskalag.__init__ as integration  # noqa: E402


class FakeAuth:
    """Stands in for hass.auth."""

    def __init__(self, users: dict[str, object]) -> None:
        self._users = users

    async def async_get_user(self, user_id):
        return self._users.get(user_id)


class FakeUser:
    def __init__(self, is_admin: bool) -> None:
        self.is_admin = is_admin


class FakeHass:
    def __init__(self, auth: FakeAuth) -> None:
        self.auth = auth


def _call(data, user_id=None):
    return integration.ServiceCall(data, user_id=user_id)


def _run(coro):
    return asyncio.run(coro)


def _base_data(**overrides):
    data = {
        "device_id": "dev1",
        "recipient_type": "players",
        "message": "Hej!",
        "confirm": True,
    }
    data.update(overrides)
    return data


def test_no_user_context_is_refused():
    hass = FakeHass(FakeAuth({}))
    call = _call(_base_data(), user_id=None)
    try:
        _run(integration._async_handle_send_sms(hass, call))
    except integration.ServiceValidationError as err:
        assert "administrat" in str(err).lower()
        return
    raise AssertionError("expected ServiceValidationError")


def test_non_admin_user_is_refused():
    hass = FakeHass(FakeAuth({"u1": FakeUser(is_admin=False)}))
    call = _call(_base_data(), user_id="u1")
    try:
        _run(integration._async_handle_send_sms(hass, call))
    except integration.ServiceValidationError as err:
        assert "administrat" in str(err).lower()
        return
    raise AssertionError("expected ServiceValidationError")


def test_unknown_user_id_is_refused():
    hass = FakeHass(FakeAuth({}))
    call = _call(_base_data(), user_id="ghost")
    try:
        _run(integration._async_handle_send_sms(hass, call))
    except integration.ServiceValidationError:
        return
    raise AssertionError("expected ServiceValidationError")


def test_admin_without_confirm_is_refused_before_any_device_lookup():
    hass = FakeHass(FakeAuth({"admin": FakeUser(is_admin=True)}))
    call = _call(_base_data(confirm=False), user_id="admin")
    try:
        _run(integration._async_handle_send_sms(hass, call))
    except integration.ServiceValidationError as err:
        assert "confirm" in str(err).lower()
        return
    raise AssertionError("expected ServiceValidationError")


def test_admin_with_confirm_but_unknown_device_is_refused():
    hass = FakeHass(FakeAuth({"admin": FakeUser(is_admin=True)}))
    # _find_coordinator will return None since no real device registry is set up.
    orig = integration._find_coordinator
    integration._find_coordinator = lambda hass, device_id: None
    try:
        call = _call(_base_data(), user_id="admin")
        try:
            _run(integration._async_handle_send_sms(hass, call))
        except integration.ServiceValidationError as err:
            assert "lag" in str(err).lower() or "device" in str(err).lower()
            return
        raise AssertionError("expected ServiceValidationError")
    finally:
        integration._find_coordinator = orig


def test_admin_confirmed_known_device_but_non_admin_capable_api_is_refused():
    class FakeCoordinator:
        stats_key = "team1"
        team_slug = "team1"
        class api:
            supports_admin = False

    hass = FakeHass(FakeAuth({"admin": FakeUser(is_admin=True)}))
    orig = integration._find_coordinator
    integration._find_coordinator = lambda hass, device_id: FakeCoordinator()
    try:
        call = _call(_base_data(), user_id="admin")
        try:
            _run(integration._async_handle_send_sms(hass, call))
        except integration.ServiceValidationError as err:
            assert "användarnamn" in str(err).lower() or "password" in str(err).lower()
            return
        raise AssertionError("expected ServiceValidationError")
    finally:
        integration._find_coordinator = orig


def test_admin_confirmed_reaches_the_unimplemented_send_and_wraps_the_error():
    class FakeApi:
        supports_admin = True
        async def async_send_sms(self, recipient_type, message):
            from svenskalag.api import SvenskalagError
            raise SvenskalagError("not implemented yet")

    class FakeCoordinator:
        stats_key = "team1"
        team_slug = "team1"
        api = FakeApi()

    hass = FakeHass(FakeAuth({"admin": FakeUser(is_admin=True)}))
    orig = integration._find_coordinator
    integration._find_coordinator = lambda hass, device_id: FakeCoordinator()
    try:
        call = _call(_base_data(), user_id="admin")
        try:
            _run(integration._async_handle_send_sms(hass, call))
        except integration.HomeAssistantError as err:
            assert "not implemented" in str(err).lower()
            return
        raise AssertionError("expected HomeAssistantError")
    finally:
        integration._find_coordinator = orig


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
        except Exception as err:  # noqa: BLE001 - surface any stubbing mistakes as failures
            failures += 1
            print(f"ERROR {name}: {err!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)

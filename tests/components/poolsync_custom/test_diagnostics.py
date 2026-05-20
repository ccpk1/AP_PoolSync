"""Tests for PoolSync diagnostics."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.components.diagnostics import REDACTED
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolsync_custom.const import (
    API_RESPONSE_MAC_ADDRESS,
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    DOMAIN,
)
from custom_components.poolsync_custom.diagnostics import (
    async_get_config_entry_diagnostics,
)

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


async def test_diagnostics_use_runtime_data_and_redact_sensitive_fields(hass) -> None:
    """Test diagnostics use entry.runtime_data and redact sensitive values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PoolSync",
        data={
            CONF_IP_ADDRESS: TEST_IP_ADDRESS,
            CONF_PASSWORD: TEST_PASSWORD,
            API_RESPONSE_MAC_ADDRESS: TEST_MAC_ADDRESS,
        },
        unique_id=TEST_MAC_ADDRESS,
    )
    entry.add_to_hass(hass)

    entry.runtime_data = SimpleNamespace(
        data={
            "poolSync": {
                "config": {"name": "runtime-device", "latitude": 33.1},
                "system": {
                    "macAddr": TEST_MAC_ADDRESS,
                    "bssid": "FF:FF:FF:FF:FF:FF",
                },
            },
            "devices": {
                "0": {
                    "system": {"serialNum": "serial-123"},
                    "config": {"setpoint": 88},
                }
            },
        },
        last_exception=RuntimeError("boom"),
        last_update_success=False,
        mac_address=TEST_MAC_ADDRESS,
        name="runtime-owner",
        update_interval=timedelta(seconds=120),
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        data={"poolSync": {"config": {"name": "stale-owner"}}},
        last_exception=None,
        last_update_success=True,
        mac_address="stale-mac",
        name="stale-owner",
        update_interval=timedelta(seconds=30),
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["config_entry"]["data"][CONF_IP_ADDRESS] == REDACTED
    assert diagnostics["config_entry"]["data"][CONF_PASSWORD] == REDACTED
    assert diagnostics["config_entry"]["data"][API_RESPONSE_MAC_ADDRESS] == REDACTED

    assert diagnostics["coordinator"]["name"] == "runtime-owner"
    assert diagnostics["coordinator"]["last_update_success"] is False
    assert diagnostics["coordinator"]["last_exception"] == "boom"
    assert diagnostics["coordinator"]["update_interval_seconds"] == 120

    assert diagnostics["runtime_data"]["poolSync"]["config"]["name"] == "runtime-device"
    assert diagnostics["runtime_data"]["poolSync"]["config"]["latitude"] == REDACTED
    assert diagnostics["runtime_data"]["poolSync"]["system"]["macAddr"] == REDACTED
    assert diagnostics["runtime_data"]["poolSync"]["system"]["bssid"] == REDACTED
    assert (
        diagnostics["runtime_data"]["devices"]["0"]["system"]["serialNum"] == REDACTED
    )

    assert "error_in_diagnostics" not in diagnostics
    assert diagnostics["runtime_data"]["poolSync"]["config"]["name"] != "stale-owner"


async def test_diagnostics_handle_missing_runtime_data(hass) -> None:
    """Test diagnostics still return redacted entry data before runtime setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PoolSync",
        data={
            CONF_IP_ADDRESS: TEST_IP_ADDRESS,
            CONF_PASSWORD: TEST_PASSWORD,
            API_RESPONSE_MAC_ADDRESS: TEST_MAC_ADDRESS,
        },
        unique_id=TEST_MAC_ADDRESS,
    )
    entry.add_to_hass(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["config_entry"]["data"] == {
        CONF_IP_ADDRESS: REDACTED,
        CONF_PASSWORD: REDACTED,
        API_RESPONSE_MAC_ADDRESS: REDACTED,
    }
    assert "coordinator" not in diagnostics
    assert "runtime_data" not in diagnostics
    assert "device" not in diagnostics

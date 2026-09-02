"""Tests for PoolSync diagnostics."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false

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
                    "system": {"serialNum": "serial-123", "modelNum": "075AHDSBLH"},
                    "config": {
                        "mode": 1,
                        "poolSpaMode": 1,
                        "setpoint": 78,
                        "spaSetpoint": 88,
                    },
                    "status": {"ctrlFlags": 13, "stateFlags": 8},
                    "faults": [8, 0],
                }
            },
            "deviceType": {"0": "heatPump"},
        },
        last_failure_class="transport_error",
        last_failure_context={
            "status_code": None,
            "has_response_body": False,
            "retryable": True,
        },
        last_failure_detail="Cannot connect to PoolSync device at 192.168.50.70",
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
    assert diagnostics["coordinator"]["last_failure_class"] == "transport_error"
    assert diagnostics["coordinator"]["last_failure_context"] == {
        "status_code": None,
        "has_response_body": False,
        "retryable": True,
    }
    assert (
        diagnostics["coordinator"]["last_failure_detail"]
        == "Cannot connect to PoolSync device at 192.168.50.70"
    )
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
    assert diagnostics["heat_pump_debug"] == {
        "active_target_temperature": 88,
        "active_fault_code": 8,
        "capabilities": {
            "model_number": "075AHDSBLH",
            "profile": "aquacal_heat_only_digital",
            "supports_heating": True,
            "supports_cooling": False,
            "supports_pool_spa_mode": True,
            "supports_separate_spa_setpoint": True,
        },
        "compressor_running": True,
        "ctrl_flags_raw": 13,
        "faults_raw": [8, 0],
        "fan_running": True,
        "has_flow": True,
        "mode_context": "heat_spa",
        "mode_value": 1,
        "pool_setpoint": 78,
        "pool_spa_mode": 1,
        "spa_setpoint": 88,
        "state_flags_raw": 8,
    }

    assert "error_in_diagnostics" not in diagnostics
    assert diagnostics["runtime_data"]["poolSync"]["config"]["name"] != "stale-owner"

    # New mapped sections
    assert diagnostics["mapped_binary_sensor_values"]["heat_pump_0_heatpump_fault"] == [
        8,
        0,
    ]
    assert (
        diagnostics["mapped_number_values"]["heat_pump_0_temperature_output_control"]
        == 88
    )
    assert (
        diagnostics["mapped_number_values"][
            "heat_pump_0_pool_temperature_output_control"
        ]
        == 78
    )
    assert (
        diagnostics["mapped_number_values"][
            "heat_pump_0_spa_temperature_output_control"
        ]
        == 88
    )
    assert diagnostics["faults_debug"]["heat_pump_0"] == {
        "raw": [8, 0],
        "active_faults": ["HP5 Lockout"],
    }


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


async def test_diagnostics_include_group_schedules(hass) -> None:
    """Test diagnostics expose per-group schedule mode and decoded slots."""
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
            "poolSync": {},
            "devices": {
                "7": {
                    "equip": {
                        "0": [3, "HEAT PUMP"],
                        "1": [0, "CIRCULATION PUMP"],
                        "3": [1, "RETURN VALVE"],
                    },
                    "groups": {
                        "0": {
                            "config": ["POOL", 0, 192, 2, 172800, 0, 1, 1],
                            "equip": {"1": [35, 0], "3": [0, 0]},
                        },
                        "1": {
                            "config": ["WATERFALL", 22, 24, 1, 21600, 21586, 1, 0],
                            "equip": {"1": [60, 0], "3": [3, 0]},
                        },
                    },
                    "schedules": {
                        "0": {
                            "0": [62, 0, 11],
                            "1": [62, 17, 0],
                            "2": [65, 0, 0],
                            "3": [0, 11527, 8],
                        },
                        "1": {
                            "0": [0, 8, 14],
                            "1": [0, 8, 14],
                            "2": [0, 8, 14],
                            "3": [0, 8, 14],
                        },
                    },
                }
            },
            "deviceType": {"7": "heatPump"},
        },
        last_failure_class="transport_error",
        last_failure_context={
            "status_code": None,
            "has_response_body": False,
            "retryable": True,
        },
        last_failure_detail="Cannot connect to PoolSync device at 192.168.50.70",
        last_exception=RuntimeError("boom"),
        last_update_success=True,
        mac_address=TEST_MAC_ADDRESS,
        name="runtime-owner",
        update_interval=timedelta(seconds=120),
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # Per-group schedule mode and decoded slots in equipment_debug
    group_schedules = diagnostics["equipment_debug"]["group_schedules"]
    assert group_schedules["0"]["schedule_mode"] is True  # POOL schedMode=1
    assert group_schedules["1"]["schedule_mode"] is False  # WATERFALL schedMode=0
    assert group_schedules["0"]["slots"] == [
        {"days": "Mon-Fri", "start": "00:00", "end": "11:00"},
        {"days": "Mon-Fri", "start": "17:00", "end": "00:00"},
        {"days": "Sat-Sun", "start": "00:00", "end": "00:00"},
        {"days": "disabled", "start": "07:45", "end": "08:00"},
    ]

    # Schedule mode also surfaced in mapped select values
    assert diagnostics["mapped_select_values"]["group_0_schedule_mode"] is True
    assert diagnostics["mapped_select_values"]["group_1_schedule_mode"] is False

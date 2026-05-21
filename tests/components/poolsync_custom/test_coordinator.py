"""Tests for the PoolSync coordinator."""

# pyright: reportPrivateUsage=false
# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.poolsync_custom.api import (
    PoolSyncApiAuthError,
    PoolSyncApiCommunicationError,
    PoolSyncApiError,
)
from custom_components.poolsync_custom.coordinator import PoolSyncDataUpdateCoordinator

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


def _build_coordinator(hass, api_client: Mock) -> PoolSyncDataUpdateCoordinator:
    """Create a coordinator for tests."""
    api_client.ip_address = TEST_IP_ADDRESS
    return PoolSyncDataUpdateCoordinator(
        hass=hass,
        api_client=api_client,
        password=TEST_PASSWORD,
        update_interval_seconds=120,
        config_entry_id="test-entry-id",
        mac_address=TEST_MAC_ADDRESS,
    )


async def test_logs_unavailable_once_on_repeated_failures(hass, caplog) -> None:
    """Test repeated refresh failures only log the unavailable transition once."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        side_effect=PoolSyncApiCommunicationError("cannot connect")
    )
    coordinator = _build_coordinator(hass, api_client)

    with caplog.at_level(logging.INFO):
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    unavailable_logs = [
        record.message
        for record in caplog.records
        if "is unavailable" in record.message
    ]
    assert unavailable_logs == [
        f"PoolSync device {coordinator.name} is unavailable: cannot connect"
    ]


async def test_logs_recovery_after_failure(hass, caplog) -> None:
    """Test a successful refresh logs recovery after an outage."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        side_effect=[
            PoolSyncApiCommunicationError("cannot connect"),
            {"poolSync": {}, "devices": {}},
        ]
    )
    coordinator = _build_coordinator(hass, api_client)

    with caplog.at_level(logging.INFO):
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    assert coordinator.data == {"poolSync": {}, "devices": {}}
    assert coordinator.last_update_success
    assert (
        f"PoolSync device {coordinator.name} is unavailable: cannot connect"
        in caplog.messages
    )
    assert f"PoolSync device {coordinator.name} is back online" in caplog.messages


async def test_refresh_classifies_transport_failure(hass) -> None:
    """Test communication failures are recorded as transport errors."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        side_effect=PoolSyncApiCommunicationError("cannot connect")
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.last_failure_class == "transport_error"
    assert coordinator.last_failure_detail == "cannot connect"
    assert coordinator.last_failure_context == {
        "status_code": None,
        "has_response_body": False,
        "retryable": True,
    }


async def test_refresh_classifies_auth_failure(hass) -> None:
    """Test auth failures are recorded as auth errors."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        side_effect=PoolSyncApiAuthError("Authentication failed: 401")
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.last_failure_class == "auth_error"
    assert coordinator.last_failure_detail == "Authentication failed: 401"
    assert coordinator.last_failure_context == {
        "status_code": None,
        "has_response_body": False,
        "retryable": False,
    }


async def test_update_data_preserves_malformed_failure_class(hass) -> None:
    """Test malformed payloads are classified explicitly."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(return_value={"poolSync": {}})
    coordinator = _build_coordinator(hass, api_client)

    coordinator._set_last_failure("transport_error", "previous failure")

    with pytest.raises(UpdateFailed, match="Malformed data received"):
        await coordinator._async_update_data()

    assert coordinator.last_failure_class == "malformed_response"
    assert coordinator.last_failure_detail == "malformed data received"
    assert coordinator.last_failure_context == {
        "status_code": None,
        "has_response_body": False,
        "retryable": True,
    }


async def test_refresh_classifies_invalid_json_api_error_as_malformed(hass) -> None:
    """Test invalid JSON API errors are exposed as malformed responses."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        side_effect=PoolSyncApiError("Invalid JSON response: bad payload")
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.last_failure_class == "malformed_response"
    assert coordinator.last_failure_detail == "Invalid JSON response: bad payload"
    assert coordinator.last_failure_context == {
        "status_code": None,
        "has_response_body": False,
        "retryable": False,
    }


async def test_refresh_classifies_non_auth_http_api_error(hass) -> None:
    """Test non-auth HTTP API failures are recorded as API errors."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        side_effect=PoolSyncApiError(
            "HTTP error 500: Internal Server Error",
            status_code=500,
            body="upstream exploded",
        )
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.last_failure_class == "api_error"
    assert coordinator.last_failure_detail == "HTTP error 500: Internal Server Error"
    assert coordinator.last_failure_context == {
        "status_code": 500,
        "has_response_body": True,
        "retryable": True,
    }


async def test_successful_refresh_clears_last_failure(hass) -> None:
    """Test successful refresh clears prior failure classification."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        side_effect=[
            PoolSyncApiCommunicationError("cannot connect"),
            {"poolSync": {}, "devices": {}},
        ]
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()
    assert coordinator.last_failure_class == "transport_error"

    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.last_failure_class is None
    assert coordinator.last_failure_detail is None
    assert coordinator.last_failure_context is None


async def test_refresh_populates_parsed_data_with_remapped_roles(hass) -> None:
    """Test successful refresh populates parsed data with resolved role IDs."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {
                "config": {"name": "PoolSync Backyard"},
                "system": {"fwVersion": "1.2.3"},
            },
            "devices": {
                "5": {"config": {"chlorOutput": 55}},
                "7": {"config": {"setpoint": 82, "mode": 1}},
            },
            "deviceType": {"5": "chlorSync", "7": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    assert coordinator.parsed_data is not None
    assert coordinator.parsed_data.system.is_present is True
    assert coordinator.parsed_data.chlorinator.device_id == "5"
    assert coordinator.parsed_data.chlorinator.is_present is True
    assert coordinator.parsed_data.heat_pump.device_id == "7"
    assert coordinator.parsed_data.heat_pump.is_present is True


async def test_refresh_parsed_data_marks_missing_resolved_device(hass) -> None:
    """Test parsed data records a resolved role even when its payload is missing."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {},
            "devices": {},
            "deviceType": {"9": "chlorSync", "11": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    assert coordinator.parsed_data is not None
    assert coordinator.parsed_data.chlorinator.device_id == "9"
    assert coordinator.parsed_data.chlorinator.is_present is False
    assert coordinator.parsed_data.heat_pump.device_id == "11"
    assert coordinator.parsed_data.heat_pump.is_present is False


async def test_device_info_uses_parsed_role_metadata(hass) -> None:
    """Test controller and attached device info use parsed role metadata."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {
                "config": {"name": "Pool Deck"},
                "system": {"fwVersion": "1.2.3", "hwVersion": "4.5.6"},
            },
            "devices": {
                "5": {
                    "nodeAttr": {"name": "ChlorSync Elite"},
                    "system": {"drvFwVersion": "8.7.6", "drvHwVersion": "2.1"},
                },
                "7": {
                    "nodeAttr": {"name": "T75 Heat Pump"},
                    "system": {
                        "modelNum": "075AHDSBLH",
                        "appFwVersion": 270,
                        "hwVersion": "F",
                    },
                },
            },
            "deviceType": {"5": "chlorSync", "7": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    controller_info = coordinator.get_device_info("controller")
    chlorinator_info = coordinator.get_device_info("chlorinator")
    heat_pump_info = coordinator.get_device_info("heat_pump")

    assert controller_info["name"] == "Pool Deck"
    assert controller_info["model"] == "PoolSync"
    assert controller_info["sw_version"] == "1.2.3"
    assert controller_info["hw_version"] == "4.5.6"

    assert chlorinator_info["name"] == "ChlorSync Elite"
    assert chlorinator_info["model"] == "ChlorSync Elite"
    assert chlorinator_info["sw_version"] == "8.7.6"
    assert chlorinator_info["hw_version"] == "2.1"
    assert chlorinator_info["via_device"] == ("poolsync_custom", TEST_MAC_ADDRESS)

    assert heat_pump_info["name"] == "T75 Heat Pump"
    assert heat_pump_info["model"] == "075AHDSBLH"
    assert heat_pump_info["sw_version"] == "270"
    assert heat_pump_info["hw_version"] == "F"
    assert heat_pump_info["via_device"] == ("poolsync_custom", TEST_MAC_ADDRESS)


async def test_device_info_normalizes_default_chlorinator_name_and_versions(
    hass,
) -> None:
    """Test default ChlorSync naming and device versions use known payload fields."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {},
            "devices": {
                "5": {
                    "nodeAttr": {"name": "ChlorSync®"},
                    "system": {"drvFwVersion": 520, "drvHwVersion": "A"},
                },
            },
            "deviceType": {"5": "chlorSync"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    chlorinator_info = coordinator.get_device_info("chlorinator")

    assert chlorinator_info["name"] == "ChlorSync"
    assert chlorinator_info["model"] == "ChlorSync"
    assert chlorinator_info["sw_version"] == "520"
    assert chlorinator_info["hw_version"] == "A"


async def test_device_info_gracefully_handles_missing_parsed_role_metadata(
    hass,
) -> None:
    """Test device info falls back cleanly when parsed role metadata is absent."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {
                "config": {"name": "PoolSync®"},
                "system": {},
            },
            "devices": {},
            "deviceType": {"11": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    controller_info = coordinator.get_device_info("controller")
    heat_pump_info = coordinator.get_device_info("heat_pump")

    assert controller_info["name"] == "PoolSync"
    assert controller_info["model"] == "PoolSync"
    assert heat_pump_info["name"] == "Heat Pump"
    assert heat_pump_info["model"] == "Heat Pump"


@pytest.mark.parametrize("default_name", ["PoolSync®", "PoolSync™", "PoolSyncTM"])
async def test_device_info_normalizes_default_controller_name_variants(
    hass,
    default_name: str,
) -> None:
    """Test default vendor controller names are normalized to PoolSync."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {
                "config": {"name": default_name},
                "system": {},
            },
            "devices": {},
        }
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    controller_info = coordinator.get_device_info("controller")

    assert controller_info["name"] == "PoolSync"
    assert controller_info["model"] == "PoolSync"


async def test_heat_pump_climate_mode_helper_uses_preset_context(hass) -> None:
    """Test climate HVAC writes map back to the contextual heat-pump mode writer."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {},
            "devices": {
                "7": {
                    "system": {"modelNum": "075AHDSBLH"},
                    "config": {
                        "mode": 0,
                        "poolSpaMode": 0,
                        "setpoint": 84,
                        "spaSetpoint": 99,
                    },
                    "status": {"ctrlFlags": 0, "stateFlags": 0},
                }
            },
            "deviceType": {"7": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)
    await coordinator.async_refresh()
    coordinator.async_set_heat_pump_mode_context = AsyncMock(return_value=None)

    await coordinator.async_set_heat_pump_climate_mode(
        hvac_mode="heat", preset_mode="spa"
    )

    coordinator.async_set_heat_pump_mode_context.assert_awaited_once_with("heat_spa")


async def test_heat_pump_active_target_uses_preset_override(hass) -> None:
    """Test climate target writes can target spa while the heat pump is off."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {},
            "devices": {
                "7": {
                    "system": {"modelNum": "075AHDSBLH"},
                    "config": {
                        "mode": 0,
                        "poolSpaMode": 0,
                        "setpoint": 84,
                        "spaSetpoint": 99,
                    },
                    "status": {"ctrlFlags": 0, "stateFlags": 0},
                }
            },
            "deviceType": {"7": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)
    await coordinator.async_refresh()
    coordinator.async_set_heat_pump_pool_setpoint = AsyncMock(return_value=None)
    coordinator.async_set_heat_pump_spa_setpoint = AsyncMock(return_value=None)

    await coordinator.async_set_heat_pump_active_target(91, preset_mode="spa")

    coordinator.async_set_heat_pump_spa_setpoint.assert_awaited_once_with(91)
    coordinator.async_set_heat_pump_pool_setpoint.assert_not_awaited()


async def test_heat_pump_climate_mode_helper_rejects_unsupported_cooling(hass) -> None:
    """Test climate helper does not expose unsupported cooling writes."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {},
            "devices": {
                "7": {
                    "system": {"modelNum": "075AHDSBLH"},
                    "config": {
                        "mode": 1,
                        "poolSpaMode": 0,
                        "setpoint": 84,
                        "spaSetpoint": 99,
                    },
                    "status": {"ctrlFlags": 13, "stateFlags": 8},
                }
            },
            "deviceType": {"7": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)
    await coordinator.async_refresh()

    with pytest.raises(HomeAssistantError, match="Cooling mode is not supported"):
        await coordinator.async_set_heat_pump_climate_mode(
            hvac_mode="cool", preset_mode="pool"
        )


async def test_device_info_derives_parsed_state_from_raw_data_when_needed(hass) -> None:
    """Test device info lazily derives parsed runtime state from raw coordinator data."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(return_value={"poolSync": {}, "devices": {}})
    coordinator = _build_coordinator(hass, api_client)
    coordinator.data = {
        "poolSync": {
            "config": {"name": "Pool House"},
            "system": {"fwVersion": "9.8.7", "hwVersion": "6.5.4"},
        },
        "devices": {
            "5": {"nodeAttr": {"name": "ChlorSync Pro"}},
        },
        "deviceType": {"5": "chlorSync"},
    }
    coordinator.parsed_data = None

    controller_info = coordinator.get_device_info("controller")
    chlorinator_info = coordinator.get_device_info("chlorinator")

    assert coordinator.parsed_data is not None
    assert controller_info["name"] == "Pool House"
    assert controller_info["model"] == "PoolSync"
    assert controller_info["sw_version"] == "9.8.7"
    assert controller_info["hw_version"] == "6.5.4"
    assert chlorinator_info["name"] == "ChlorSync Pro"
    assert chlorinator_info["model"] == "ChlorSync Pro"

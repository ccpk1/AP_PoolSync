"""Tests for the PoolSync coordinator."""

# pyright: reportPrivateUsage=false
# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

from custom_components.poolsync_custom.api import PoolSyncApiCommunicationError
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
    """Test device info uses parsed system and chlorinator role metadata."""
    api_client = Mock()
    api_client.get_all_data = AsyncMock(
        return_value={
            "poolSync": {
                "config": {"name": "Pool Deck"},
                "system": {"fwVersion": "1.2.3", "hwVersion": "4.5.6"},
            },
            "devices": {
                "5": {"nodeAttr": {"name": "ChlorSync Elite"}},
                "7": {},
            },
            "deviceType": {"5": "chlorSync", "7": "heatPump"},
        }
    )
    coordinator = _build_coordinator(hass, api_client)

    await coordinator.async_refresh()

    device_info = coordinator.device_info
    assert device_info["name"] == "Pool Deck"
    assert device_info["model"] == "ChlorSync Elite"
    assert device_info["sw_version"] == "1.2.3"
    assert device_info["hw_version"] == "4.5.6"


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

    device_info = coordinator.device_info
    assert device_info["name"] == f"PoolSync {TEST_MAC_ADDRESS[-6:]}"
    assert device_info["model"] == "PoolSync"


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

    device_info = coordinator.device_info

    assert coordinator.parsed_data is not None
    assert device_info["name"] == "Pool House"
    assert device_info["model"] == "ChlorSync Pro"
    assert device_info["sw_version"] == "9.8.7"
    assert device_info["hw_version"] == "6.5.4"

"""Tests for the PoolSync number write path."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.number import NumberEntityDescription
from homeassistant.const import PERCENTAGE
from homeassistant.exceptions import HomeAssistantError

from custom_components.poolsync_custom.api import PoolSyncApiCommunicationError
from custom_components.poolsync_custom.coordinator import PoolSyncDataUpdateCoordinator
from custom_components.poolsync_custom.number import PoolSyncChlorOutputNumberEntity
from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


def _build_coordinator(hass, api_client: Mock) -> PoolSyncDataUpdateCoordinator:
    """Create a coordinator for number entity tests."""
    api_client.ip_address = TEST_IP_ADDRESS
    coordinator = PoolSyncDataUpdateCoordinator(
        hass=hass,
        api_client=api_client,
        password=TEST_PASSWORD,
        update_interval_seconds=120,
        config_entry_id="test-entry-id",
        mac_address=TEST_MAC_ADDRESS,
    )
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "1": {
                "config": {
                    "chlorOutput": 50,
                }
            }
        },
        "deviceType": {"1": "chlorSync"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)
    coordinator.async_request_refresh = AsyncMock(return_value=None)
    return coordinator


def _build_entity(hass, api_client: Mock) -> PoolSyncChlorOutputNumberEntity:
    """Create a number entity backed by a coordinator."""
    coordinator = _build_coordinator(hass, api_client)
    return PoolSyncChlorOutputNumberEntity(
        coordinator,
        "chlorinator",
        NumberEntityDescription(
            key="chlor_output_control",
            name="Chlorinator Output",
            native_unit_of_measurement=PERCENTAGE,
            native_min_value=0,
            native_max_value=100,
            native_step=1,
        ),
    )


async def test_async_set_native_value_calls_public_api_and_refresh(hass) -> None:
    """Test number writes go through the public API method and refresh."""
    api_client = Mock()
    api_client.async_set_device_config_value = AsyncMock(return_value={})
    entity = _build_entity(hass, api_client)

    await entity.async_set_native_value(42)

    api_client.async_set_device_config_value.assert_awaited_once_with(
        device_id="1",
        key_id="chlorOutput",
        value=42,
        password=TEST_PASSWORD,
    )
    entity.coordinator.async_request_refresh.assert_awaited_once()


async def test_async_set_native_value_raises_homeassistant_error(hass) -> None:
    """Test API failures are surfaced as HomeAssistantError."""
    api_client = Mock()
    api_client.async_set_device_config_value = AsyncMock(
        side_effect=PoolSyncApiCommunicationError("cannot connect")
    )
    entity = _build_entity(hass, api_client)

    with pytest.raises(HomeAssistantError, match="Failed to set chlorinator output"):
        await entity.async_set_native_value(42)

    entity.coordinator.async_request_refresh.assert_not_awaited()


async def test_async_set_native_value_routes_active_target_to_spa_setpoint(
    hass,
) -> None:
    """Test active target writes use the spa setpoint when spa mode is active."""
    api_client = Mock()
    api_client.ip_address = TEST_IP_ADDRESS
    api_client.async_set_device_config_value = AsyncMock(return_value={})
    coordinator = PoolSyncDataUpdateCoordinator(
        hass=hass,
        api_client=api_client,
        password=TEST_PASSWORD,
        update_interval_seconds=120,
        config_entry_id="test-entry-id",
        mac_address=TEST_MAC_ADDRESS,
    )
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "7": {
                "config": {
                    "mode": 1,
                    "poolSpaMode": 1,
                    "setpoint": 78,
                    "spaSetpoint": 88,
                },
            },
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)
    coordinator.async_request_refresh = AsyncMock(return_value=None)

    entity = PoolSyncChlorOutputNumberEntity(
        coordinator,
        "heat_pump",
        NumberEntityDescription(
            key="temperature_output_control",
            name="Active Target Temperature",
            native_min_value=40,
            native_max_value=104,
            native_step=1,
        ),
    )

    await entity.async_set_native_value(91)

    api_client.async_set_device_config_value.assert_awaited_once_with(
        device_id="7",
        key_id="spaSetpoint",
        value=91,
        password=TEST_PASSWORD,
    )
    coordinator.async_request_refresh.assert_awaited_once()


async def test_number_entity_becomes_unavailable_when_value_missing(hass) -> None:
    """Test number entities report unavailable when their parsed value is missing."""
    api_client = Mock()
    api_client.ip_address = TEST_IP_ADDRESS
    coordinator = PoolSyncDataUpdateCoordinator(
        hass=hass,
        api_client=api_client,
        password=TEST_PASSWORD,
        update_interval_seconds=120,
        config_entry_id="test-entry-id",
        mac_address=TEST_MAC_ADDRESS,
    )
    coordinator.data = {
        "poolSync": {},
        "devices": {"1": {"config": {}}},
        "deviceType": {"1": "chlorSync"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncChlorOutputNumberEntity(
        coordinator,
        "chlorinator",
        NumberEntityDescription(
            key="chlor_output_control",
            name="Chlorinator Output",
            native_unit_of_measurement=PERCENTAGE,
            native_min_value=0,
            native_max_value=100,
            native_step=1,
        ),
    )

    assert entity.native_value is None
    assert entity.available is False

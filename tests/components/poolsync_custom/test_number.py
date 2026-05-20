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
    }
    coordinator.async_request_refresh = AsyncMock(return_value=None)
    return coordinator


def _build_entity(hass, api_client: Mock) -> PoolSyncChlorOutputNumberEntity:
    """Create a number entity backed by a coordinator."""
    coordinator = _build_coordinator(hass, api_client)
    return PoolSyncChlorOutputNumberEntity(
        coordinator,
        NumberEntityDescription(
            key="chlor_output_control",
            name="Chlorinator Output",
            native_unit_of_measurement=PERCENTAGE,
            native_min_value=0,
            native_max_value=100,
            native_step=1,
        ),
        ["devices", "1", "config", "chlorOutput"],
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

    with pytest.raises(HomeAssistantError, match="Failed to set chlorine output"):
        await entity.async_set_native_value(42)

    entity.coordinator.async_request_refresh.assert_not_awaited()

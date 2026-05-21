"""Tests for PoolSync select platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, call

import pytest
from homeassistant.components.select import SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from custom_components.poolsync_custom.coordinator import PoolSyncDataUpdateCoordinator
from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data
from custom_components.poolsync_custom.select import (
    PoolSyncHeatModeSelect,
    async_setup_entry,
)

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


def _build_entry(coordinator) -> Mock:
    """Build a config-entry-like object for setup tests."""
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


async def test_async_setup_entry_creates_translated_heat_mode_select(hass) -> None:
    """Test setup creates a heat-mode select with capability-aware options."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = TEST_MAC_ADDRESS
    coordinator.get_device_info = Mock(
        return_value={
            "identifiers": {("poolsync_custom", f"{TEST_MAC_ADDRESS}_heat_pump")}
        }
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
                "system": {"modelNum": "075AHDSBLH"},
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    added_entities: list[PoolSyncHeatModeSelect] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert len(added_entities) == 1
    select_entity = added_entities[0]
    assert select_entity.current_option == "heat_spa"
    assert select_entity.options == ["off", "heat_pool", "heat_spa"]
    assert select_entity.entity_description.translation_key == "mode"
    assert select_entity.entity_description.entity_category == EntityCategory.CONFIG
    assert select_entity.device_info["identifiers"] == {
        ("poolsync_custom", f"{TEST_MAC_ADDRESS}_heat_pump")
    }


async def test_async_select_option_routes_contextual_mode_writes(hass) -> None:
    """Test select writes route through the contextual heat-mode command path."""
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
                    "poolSpaMode": 0,
                    "setpoint": 78,
                    "spaSetpoint": 88,
                }
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)
    coordinator.async_request_refresh = AsyncMock(return_value=None)

    entity = PoolSyncHeatModeSelect(
        coordinator,
        SelectEntityDescription(
            key="heat_mode",
            options=["off", "heat_pool", "heat_spa"],
            translation_key="mode",
        ),
    )

    await entity.async_select_option("heat_spa")

    assert entity.current_option == "heat_spa"
    assert api_client.async_set_device_config_value.await_args_list == [
        call(
            device_id="7",
            key_id="mode",
            value=1,
            password=TEST_PASSWORD,
        ),
        call(
            device_id="7",
            key_id="poolSpaMode",
            value=1,
            password=TEST_PASSWORD,
        ),
    ]
    coordinator.async_request_refresh.assert_awaited_once()


async def test_async_select_option_rejects_unsupported_value(hass) -> None:
    """Test select rejects unsupported heat-mode options."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = TEST_MAC_ADDRESS
    coordinator.get_device_info = Mock(
        return_value={
            "identifiers": {("poolsync_custom", f"{TEST_MAC_ADDRESS}_heat_pump")}
        }
    )
    coordinator.async_set_heat_pump_mode_context = AsyncMock(return_value=None)
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "7": {
                "config": {
                    "mode": 1,
                    "poolSpaMode": 0,
                    "setpoint": 78,
                    "spaSetpoint": 88,
                },
                "system": {"modelNum": "075AHDSBLH"},
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncHeatModeSelect(
        coordinator,
        SelectEntityDescription(
            key="heat_mode",
            options=["off", "heat_pool", "heat_spa"],
            translation_key="mode",
        ),
    )

    with pytest.raises(HomeAssistantError, match="Unsupported heat pump mode"):
        await entity.async_select_option("auto_pool")

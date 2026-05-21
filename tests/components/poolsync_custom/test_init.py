"""Tests for PoolSync integration setup and unload."""

# pylint: disable=redefined-outer-name
# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolsync_custom import (
    async_setup_entry,
    async_unload_entry,
    async_update_options_listener,
)
from custom_components.poolsync_custom.const import (
    API_RESPONSE_MAC_ADDRESS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_SCAN_INTERVAL,
    PLATFORMS,
)
from custom_components.poolsync_custom.coordinator import PoolSyncDataUpdateCoordinator
from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


@pytest.fixture
def poolsync_config_entry() -> MockConfigEntry:
    """Return a default mocked PoolSync config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="PoolSync",
        data={
            CONF_IP_ADDRESS: TEST_IP_ADDRESS,
            CONF_PASSWORD: TEST_PASSWORD,
            API_RESPONSE_MAC_ADDRESS: TEST_MAC_ADDRESS,
        },
        options={OPTION_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
        unique_id=TEST_MAC_ADDRESS,
    )


async def test_async_setup_entry_sets_runtime_data(
    hass, poolsync_config_entry: MockConfigEntry
) -> None:
    """Test setup stores the coordinator on the config entry runtime data."""
    poolsync_config_entry.add_to_hass(hass)

    with (
        patch.object(
            PoolSyncDataUpdateCoordinator,
            "async_config_entry_first_refresh",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(return_value=True),
        ) as mock_forward_entry_setups,
    ):
        assert await async_setup_entry(hass, poolsync_config_entry)

    assert isinstance(poolsync_config_entry.runtime_data, PoolSyncDataUpdateCoordinator)
    mock_forward_entry_setups.assert_awaited_once_with(poolsync_config_entry, PLATFORMS)


async def test_async_setup_entry_uses_dedicated_poolsync_session(
    hass, poolsync_config_entry: MockConfigEntry
) -> None:
    """Test setup creates a dedicated PoolSync session instead of reusing the shared one."""
    poolsync_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.poolsync_custom.async_create_poolsync_session",
            return_value=object(),
        ) as mock_create_session,
        patch.object(
            PoolSyncDataUpdateCoordinator,
            "async_config_entry_first_refresh",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_entry(hass, poolsync_config_entry)

    mock_create_session.assert_called_once_with(hass)


async def test_async_setup_entry_raises_not_ready_on_refresh_failure(
    hass, poolsync_config_entry: MockConfigEntry
) -> None:
    """Test setup retries when the initial refresh fails."""
    poolsync_config_entry.add_to_hass(hass)

    with patch.object(
        PoolSyncDataUpdateCoordinator,
        "async_config_entry_first_refresh",
        new=AsyncMock(side_effect=UpdateFailed("cannot connect")),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, poolsync_config_entry)


async def test_async_setup_entry_raises_config_error_without_mac(hass) -> None:
    """Test setup fails clearly when the config entry is missing identity data."""
    missing_mac_entry = MockConfigEntry(
        domain=DOMAIN,
        title="PoolSync",
        data={
            CONF_IP_ADDRESS: TEST_IP_ADDRESS,
            CONF_PASSWORD: TEST_PASSWORD,
        },
        options={OPTION_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
    )
    missing_mac_entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryError, match="Missing PoolSync MAC address"):
        await async_setup_entry(hass, missing_mac_entry)


async def test_async_unload_entry_clears_runtime_data(
    hass, poolsync_config_entry: MockConfigEntry
) -> None:
    """Test unload removes runtime data after unloading platforms."""
    poolsync_config_entry.add_to_hass(hass)
    poolsync_config_entry.runtime_data = object()

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ) as mock_unload_platforms:
        assert await async_unload_entry(hass, poolsync_config_entry)

    mock_unload_platforms.assert_awaited_once_with(poolsync_config_entry, PLATFORMS)
    assert not hasattr(poolsync_config_entry, "runtime_data")


async def test_async_update_options_listener_reloads_entry(
    hass, poolsync_config_entry: MockConfigEntry
) -> None:
    """Test options updates trigger a config entry reload."""
    poolsync_config_entry.add_to_hass(hass)

    with patch.object(
        hass.config_entries,
        "async_reload",
        new=AsyncMock(return_value=True),
    ) as mock_reload:
        await async_update_options_listener(hass, poolsync_config_entry)

    mock_reload.assert_awaited_once_with(poolsync_config_entry.entry_id)


async def test_async_setup_entry_migrates_existing_entities_to_role_devices(
    hass,
    poolsync_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test setup rehomes stale registered entities to child devices."""
    poolsync_config_entry.add_to_hass(hass)

    controller_device = device_registry.async_get_or_create(
        config_entry_id=poolsync_config_entry.entry_id,
        identifiers={(DOMAIN, TEST_MAC_ADDRESS)},
        manufacturer="PoolSync",
        model="PoolSync",
        name="PoolSync",
    )

    heat_sensor = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{TEST_MAC_ADDRESS}_hp_water_temp",
        config_entry=poolsync_config_entry,
        device_id=controller_device.id,
    )
    heat_select = entity_registry.async_get_or_create(
        "select",
        DOMAIN,
        f"{TEST_MAC_ADDRESS}_heat_mode",
        config_entry=poolsync_config_entry,
        device_id=controller_device.id,
    )
    chlor_number = entity_registry.async_get_or_create(
        "number",
        DOMAIN,
        f"{TEST_MAC_ADDRESS}_chlor_output_control",
        config_entry=poolsync_config_entry,
        device_id=controller_device.id,
    )
    controller_sensor = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{TEST_MAC_ADDRESS}_board_temp",
        config_entry=poolsync_config_entry,
        device_id=controller_device.id,
    )

    async def _mock_first_refresh(self: PoolSyncDataUpdateCoordinator) -> None:
        self.data = {
            "poolSync": {
                "config": {"name": "Pool Deck"},
                "system": {"fwVersion": "1.2.3", "hwVersion": "4.5.6"},
            },
            "devices": {
                "5": {
                    "nodeAttr": {"name": "ChlorSync Elite"},
                    "system": {"fwVersion": "8.7.6", "hwVersion": "2.1"},
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
        self.parsed_data = parse_poolsync_runtime_data(self.data)

    with (
        patch.object(
            PoolSyncDataUpdateCoordinator,
            "async_config_entry_first_refresh",
            new=_mock_first_refresh,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_entry(hass, poolsync_config_entry)

    heat_pump_device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{TEST_MAC_ADDRESS}_heat_pump")}
    )
    chlorinator_device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{TEST_MAC_ADDRESS}_chlorinator")}
    )

    assert heat_pump_device is not None
    assert chlorinator_device is not None
    assert (
        entity_registry.async_get(heat_sensor.entity_id).device_id
        == heat_pump_device.id
    )
    assert (
        entity_registry.async_get(heat_select.entity_id).device_id
        == heat_pump_device.id
    )
    assert (
        entity_registry.async_get(chlor_number.entity_id).device_id
        == chlorinator_device.id
    )
    assert (
        entity_registry.async_get(controller_sensor.entity_id).device_id
        == controller_device.id
    )

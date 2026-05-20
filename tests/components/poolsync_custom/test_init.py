"""Tests for PoolSync integration setup and unload."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
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

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
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
    hass, mock_config_entry: MockConfigEntry
) -> None:
    """Test setup stores the coordinator on the config entry runtime data."""
    mock_config_entry.add_to_hass(hass)

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
        assert await async_setup_entry(hass, mock_config_entry)

    assert isinstance(mock_config_entry.runtime_data, PoolSyncDataUpdateCoordinator)
    mock_forward_entry_setups.assert_awaited_once_with(mock_config_entry, PLATFORMS)


async def test_async_setup_entry_raises_not_ready_on_refresh_failure(
    hass, mock_config_entry: MockConfigEntry
) -> None:
    """Test setup retries when the initial refresh fails."""
    mock_config_entry.add_to_hass(hass)

    with patch.object(
        PoolSyncDataUpdateCoordinator,
        "async_config_entry_first_refresh",
        new=AsyncMock(side_effect=UpdateFailed("cannot connect")),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry)


async def test_async_setup_entry_raises_config_error_without_mac(
    hass, mock_config_entry: MockConfigEntry
) -> None:
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
    hass, mock_config_entry: MockConfigEntry
) -> None:
    """Test unload removes runtime data after unloading platforms."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = object()

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ) as mock_unload_platforms:
        assert await async_unload_entry(hass, mock_config_entry)

    mock_unload_platforms.assert_awaited_once_with(mock_config_entry, PLATFORMS)
    assert not hasattr(mock_config_entry, "runtime_data")


async def test_async_update_options_listener_reloads_entry(
    hass, mock_config_entry: MockConfigEntry
) -> None:
    """Test options updates trigger a config entry reload."""
    mock_config_entry.add_to_hass(hass)

    with patch.object(
        hass.config_entries,
        "async_reload",
        new=AsyncMock(return_value=True),
    ) as mock_reload:
        await async_update_options_listener(hass, mock_config_entry)

    mock_reload.assert_awaited_once_with(mock_config_entry.entry_id)

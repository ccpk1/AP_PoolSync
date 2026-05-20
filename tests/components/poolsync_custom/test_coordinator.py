"""Tests for the PoolSync coordinator."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.poolsync_custom.api import PoolSyncApiCommunicationError
from custom_components.poolsync_custom.coordinator import PoolSyncDataUpdateCoordinator

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


def _build_coordinator(hass, api_client: Mock) -> PoolSyncDataUpdateCoordinator:
    """Create a coordinator for tests."""
    api_client._ip_address = TEST_IP_ADDRESS
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
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

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
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        result = await coordinator._async_update_data()

    assert result == {"poolSync": {}, "devices": {}}
    assert (
        f"PoolSync device {coordinator.name} is unavailable: cannot connect"
        in caplog.messages
    )
    assert f"PoolSync device {coordinator.name} is back online" in caplog.messages

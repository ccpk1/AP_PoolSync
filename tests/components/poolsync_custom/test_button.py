"""Tests for PoolSync button entities."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from custom_components.poolsync_custom.button import PoolSyncButton, async_setup_entry


def _build_entry(coordinator) -> Mock:
    """Build a config-entry-like object for setup tests."""
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


async def test_async_setup_entry_adds_controller_button(hass) -> None:
    """Test setup creates the manual refresh button on the controller device."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    )

    added_entities: list[PoolSyncButton] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert len(added_entities) == 1
    button = added_entities[0]
    assert button.entity_description.key == "manual_refresh"
    assert button.entity_description.translation_key == "manual_refresh"
    assert button.device_info["identifiers"] == {("poolsync_custom", "AABBCCDDEEFF")}


async def test_manual_refresh_button_uses_coordinator_refresh_path() -> None:
    """Test button presses call the coordinator manual refresh helper."""
    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    )
    coordinator.async_manual_refresh = AsyncMock(return_value=None)

    button = PoolSyncButton(
        coordinator,
        Mock(key="manual_refresh", translation_key="manual_refresh"),
    )

    await button.async_press()

    coordinator.async_manual_refresh.assert_awaited_once_with()

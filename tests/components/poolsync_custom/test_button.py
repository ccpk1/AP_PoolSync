"""Tests for PoolSync button entities."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from homeassistant.const import EntityCategory

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
    assert button.entity_description.entity_category == EntityCategory.CONFIG
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


# ===================================================================
# ChemSync / ChlorSync action buttons
# ===================================================================


def _build_action_coordinator() -> Mock:
    """Build a coordinator mock with chem_sync and chlorinator devices."""
    from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data

    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    )
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "0": {"config": {}, "status": {}},
            "5": {"config": {}, "status": {}},
        },
        "deviceType": {"0": "chemSync", "5": "chlorSync"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)
    return coordinator


async def test_async_setup_entry_adds_chem_and_chlor_buttons(hass) -> None:
    """Test setup creates chem_sync and chlorinator action buttons."""
    coordinator = _build_action_coordinator()
    added_entities: list[PoolSyncButton] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    keys = {e.entity_description.key for e in added_entities}
    assert "chem_prime_pump" in keys
    assert "chem_boost" in keys
    assert "chlor_clear_cell_life" in keys


async def test_chem_prime_pump_button_calls_coordinator() -> None:
    """Test the chem prime pump button calls the coordinator action."""
    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    )
    coordinator.async_chem_prime_pump = AsyncMock(return_value=None)

    button = PoolSyncButton(
        coordinator,
        Mock(key="chem_prime_pump", translation_key="chem_prime_pump"),
        role="chem_sync",
        device_index=0,
    )

    await button.async_press()

    coordinator.async_chem_prime_pump.assert_awaited_once_with(index=0)


async def test_chem_boost_button_calls_coordinator() -> None:
    """Test the chem boost button calls the coordinator action."""
    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    )
    coordinator.async_chem_boost = AsyncMock(return_value=None)

    button = PoolSyncButton(
        coordinator,
        Mock(key="chem_boost", translation_key="chem_boost"),
        role="chem_sync",
        device_index=0,
    )

    await button.async_press()

    coordinator.async_chem_boost.assert_awaited_once_with(index=0)


async def test_chlor_clear_cell_life_button_calls_coordinator() -> None:
    """Test the chlor clear cell life button calls the coordinator action."""
    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    )
    coordinator.async_chlor_clear_cell_life = AsyncMock(return_value=None)

    button = PoolSyncButton(
        coordinator,
        Mock(key="chlor_clear_cell_life", translation_key="chlor_clear_cell_life"),
        role="chlorinator",
        device_index=0,
    )

    await button.async_press()

    coordinator.async_chlor_clear_cell_life.assert_awaited_once_with(index=0)

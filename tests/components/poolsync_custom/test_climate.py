"""Tests for the PoolSync climate platform."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.poolsync_custom.climate import (
    PoolSyncHeatPumpClimateEntity,
    async_setup_entry,
)
from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data


def _build_entry(coordinator) -> Mock:
    """Build a config-entry-like object for setup tests."""
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


def _build_coordinator() -> Mock:
    """Build a mock coordinator with heat-pump runtime data."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.last_update_success = True
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_heat_pump")}}
    )
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "7": {
                "system": {"modelNum": "075AHDSBLH"},
                "status": {"waterTemp": 82.0, "ctrlFlags": 13, "stateFlags": 8},
                "config": {
                    "mode": 1,
                    "poolSpaMode": 0,
                    "setpoint": 84,
                    "spaSetpoint": 99,
                },
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)
    coordinator.async_set_heat_pump_climate_mode = AsyncMock(return_value=None)
    coordinator.async_set_heat_pump_active_target = AsyncMock(return_value=None)
    return coordinator


async def test_async_setup_entry_adds_heat_pump_climate(hass) -> None:
    """Test setup creates the heat-pump climate entity."""
    coordinator = _build_coordinator()
    added_entities: list[PoolSyncHeatPumpClimateEntity] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert len(added_entities) == 1
    entity = added_entities[0]
    assert entity.entity_description.key == "water_thermostat"
    assert entity.hvac_mode == HVACMode.HEAT
    assert entity.hvac_modes == [HVACMode.OFF, HVACMode.HEAT]
    assert entity.preset_mode == "pool"
    assert entity.preset_modes == ["pool", "spa"]
    assert entity.current_temperature == 82.0
    assert entity.target_temperature == 84
    assert entity.hvac_action == HVACAction.HEATING


async def test_climate_set_hvac_mode_uses_last_preset() -> None:
    """Test turning on climate routes through the coordinator climate helper."""
    coordinator = _build_coordinator()
    coordinator.data["devices"]["7"]["config"]["mode"] = 0
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncHeatPumpClimateEntity(
        coordinator,
        Mock(key="water_thermostat", translation_key="water_thermostat"),
    )
    entity._last_on_preset_mode = "spa"

    await entity.async_set_hvac_mode(HVACMode.HEAT)

    coordinator.async_set_heat_pump_climate_mode.assert_awaited_once_with(
        hvac_mode="heat", preset_mode="spa"
    )


async def test_climate_set_preset_mode_while_off_updates_local_state() -> None:
    """Test changing preset while off keeps the write local until turned on."""
    coordinator = _build_coordinator()
    coordinator.data["devices"]["7"]["config"]["mode"] = 0
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncHeatPumpClimateEntity(
        coordinator,
        Mock(key="water_thermostat", translation_key="water_thermostat"),
    )

    await entity.async_set_preset_mode("spa")

    assert entity.preset_mode == "spa"
    assert entity.target_temperature == 99
    coordinator.async_set_heat_pump_climate_mode.assert_not_awaited()


async def test_climate_set_temperature_routes_through_active_target_flow() -> None:
    """Test climate target writes reuse the coordinator active-target helper."""
    coordinator = _build_coordinator()
    entity = PoolSyncHeatPumpClimateEntity(
        coordinator,
        Mock(key="water_thermostat", translation_key="water_thermostat"),
    )

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 91})

    coordinator.async_set_heat_pump_active_target.assert_awaited_once_with(
        91, preset_mode="pool"
    )

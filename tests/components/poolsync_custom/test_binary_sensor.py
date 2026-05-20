"""Tests for PoolSync binary sensors."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from unittest.mock import Mock

from custom_components.poolsync_custom.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC,
    BINARY_SENSOR_DESCRIPTIONS_HEATPUMP,
    PoolSyncBinarySensor,
    async_setup_entry,
)


def _build_entry(coordinator) -> Mock:
    """Build a config-entry-like object for setup tests."""
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


def _build_coordinator() -> Mock:
    """Build a coordinator-like object for binary sensor tests."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.device_info = {"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {
            "status": {"online": 1},
            "config": {"serviceMode": 0},
            "faults": 0,
        },
        "devices": {
            "5": {"nodeAttr": {"online": 1}, "faults": [0], "status": {}},
            "7": {
                "nodeAttr": {"online": 1},
                "faults": [0],
                "status": {"ctrlFlags": 1, "stateFlags": 8},
            },
        },
        "deviceType": {"5": "chlorSync", "7": "heatPump"},
    }
    return coordinator


async def test_async_setup_entry_uses_detected_device_ids(hass) -> None:
    """Test setup creates binary sensors using detected device IDs."""
    coordinator = _build_coordinator()
    added_entities: list[PoolSyncBinarySensor] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert added_entities
    chlor_fault = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "chlorsync_fault"
    )
    heat_online = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "heatpump_online"
    )
    assert chlor_fault.is_on is False
    assert heat_online.is_on is True
    assert BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC[0][0].key == "chlorsync_online"
    assert BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[0][0].key == "heatpump_online"


async def test_binary_sensor_updates_cached_state() -> None:
    """Test binary sensor updates cached state and availability."""
    coordinator = _build_coordinator()
    sensor = PoolSyncBinarySensor(
        coordinator,
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[0][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[0][1],
    )

    assert sensor.is_on is True
    assert sensor.available is True

    coordinator.data["devices"]["7"]["nodeAttr"]["online"] = None
    sensor.async_write_ha_state = Mock()
    sensor._handle_coordinator_update()

    assert sensor.is_on is None
    assert sensor.available is False


async def test_async_setup_entry_skips_missing_remapped_device(hass) -> None:
    """Test setup skips device-specific binary sensors when the payload is missing."""
    coordinator = _build_coordinator()
    coordinator.data["devices"] = {}
    coordinator.data["deviceType"] = {"9": "chlorSync", "11": "heatPump"}

    added_entities: list[PoolSyncBinarySensor] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert {entity.entity_description.key for entity in added_entities} == {
        "poolsync_online",
        "service_mode_active",
        "system_fault",
    }

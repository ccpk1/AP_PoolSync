"""Tests for PoolSync sensor platform setup."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from unittest.mock import Mock

from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data
from custom_components.poolsync_custom.sensor import (
    SENSOR_DESCRIPTIONS_CHLORSYNC,
    SENSOR_DESCRIPTIONS_HEATPUMP,
    SENSOR_DESCRIPTIONS_POOLSYNC,
    PoolSyncSensor,
    async_setup_entry,
)


def _build_entry(coordinator) -> Mock:
    """Build a config-entry-like object for setup tests."""
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


async def test_async_setup_entry_uses_detected_device_ids(hass) -> None:
    """Test setup creates sensor entities from detected PoolSync device IDs."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.device_info = {"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    coordinator.data = {
        "poolSync": {"status": {"boardTemp": 30, "rssi": -67}},
        "devices": {
            "5": {
                "status": {"waterTemp": 24.5, "saltPPM": 3200},
                "config": {"chlorOutput": 55},
                "system": {
                    "cellSerialNum": "ABC123",
                    "cellFwVersion": "1.0",
                    "cellHwVersion": "2.0",
                },
            },
            "7": {
                "status": {"waterTemp": 82.0, "airTemp": 70.0},
                "config": {"mode": 1, "setpoint": 84},
            },
        },
        "deviceType": {"5": "chlorSync", "7": "heatPump"},
    }

    added_entities: list[PoolSyncSensor] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert added_entities
    chlor_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "water_temp"
    )
    heat_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "hp_setpoint_temp"
    )
    assert chlor_sensor.native_value == 24.5
    assert heat_sensor.native_value == 84
    assert chlor_sensor.name == "Water Temperature"
    assert heat_sensor.name == "Setpoint Temperature"
    assert SENSOR_DESCRIPTIONS_CHLORSYNC[0][0].key == "water_temp"
    assert SENSOR_DESCRIPTIONS_HEATPUMP[0][0].key == "hp_water_temp"


async def test_async_setup_entry_skips_missing_remapped_device(hass) -> None:
    """Test setup skips device-specific sensors when the resolved device payload is missing."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.device_info = {"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    coordinator.data = {
        "poolSync": {"status": {"boardTemp": 30, "rssi": -67}},
        "devices": {},
        "deviceType": {"9": "chlorSync", "11": "heatPump"},
    }

    added_entities: list[PoolSyncSensor] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert {entity.entity_description.key for entity in added_entities} == {
        "board_temp",
        "wifi_rssi",
        "system_datetime",
        "firmware_version",
        "hardware_version",
        "uptime_seconds",
    }


async def test_sensor_uses_parsed_runtime_values() -> None:
    """Test sensor reads current value and availability from parsed runtime data."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.device_info = {"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {
            "status": {"dateTime": "2026-05-20T12:30:00+00:00"},
            "system": {"fwVersion": "1.2.3"},
        },
        "devices": {},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    sensor = PoolSyncSensor(
        coordinator,
        next(
            description
            for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "system_datetime"
        ),
        lambda v: v,
    )

    assert sensor.native_value == "2026-05-20T12:30:00+00:00"
    assert sensor.available is True

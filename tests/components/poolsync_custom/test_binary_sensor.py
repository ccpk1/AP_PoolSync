"""Tests for PoolSync binary sensors."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from custom_components.poolsync_custom.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC,
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
    coordinator.get_device_info = Mock(
        side_effect=lambda role, index=0: {
            "identifiers": {("poolsync_custom", f"AABBCCDDEEFF_{role}")}
        }
    )
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


def _load_runtime_data(sample_name: str) -> dict:
    """Load runtime data from a sample diagnostics export.

    Handles trailing commas that sometimes appear in HA diagnostic
    download format so the files can be stored exactly as exported.
    """
    sample_path = (
        Path(__file__).resolve().parents[2] / "sample_diagnostics" / sample_name
    )
    raw = sample_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        payload = json.loads(cleaned)
    return payload["data"]["runtime_data"]


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
    assert heat_online.entity_description.translation_key == "node_connected"
    assert heat_online.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_heat_pump")
    }
    assert BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC[0][0].key == "chlorsync_online"
    assert BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[0][0].key == "heatpump_online"


async def test_binary_sensor_updates_cached_state() -> None:
    """Test binary sensor updates cached state and availability."""
    coordinator = _build_coordinator()
    sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
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
    assert (
        next(
            entity
            for entity in added_entities
            if entity.entity_description.key == "poolsync_online"
        ).entity_description.translation_key
        == "online"
    )


async def test_heat_pump_binary_sensors_use_derived_runtime_state() -> None:
    """Test heat-pump binary sensors follow derived runtime state mappings."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_heat_pump")}}
    )
    coordinator.last_update_success = True
    coordinator.data = _load_runtime_data("t75-spa-startup-fan-nocompressor.json")

    flow_sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[2][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[2][1],
    )
    compressor_sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[3][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[3][1],
    )
    fan_sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[4][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[4][1],
    )

    assert flow_sensor.is_on is True
    assert compressor_sensor.is_on is False
    assert fan_sensor.is_on is True


@pytest.mark.parametrize(
    ("sample_name", "expected_flow", "expected_compressor", "expected_fan"),
    [
        ("sq160r-heating.json", True, True, True),
        ("sq160r-idle.json", True, False, False),
        ("sq160r-off.json", False, False, False),
        ("t75-heat-pool.json", True, True, True),
        ("t75-off-with-flow.json", True, False, False),
        ("t75-off-no-flow.json", False, False, False),
        ("t75-heatpump-fault.json", True, False, False),
        ("t75-heat-spa.json", True, True, True),
        ("t75-spa-startup-fan-nocompressor.json", True, False, True),
    ],
)
async def test_heat_pump_binary_sensors_from_all_diagnostics(
    sample_name: str,
    expected_flow: bool,
    expected_compressor: bool,
    expected_fan: bool,
) -> None:
    """Test heat-pump binary sensors derive correct state from all diagnostic samples."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_heat_pump")}}
    )
    coordinator.last_update_success = True
    coordinator.data = _load_runtime_data(sample_name)

    flow_sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[2][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[2][1],
    )
    compressor_sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[3][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[3][1],
    )
    fan_sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[4][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[4][1],
    )

    assert flow_sensor.is_on is expected_flow
    assert compressor_sensor.is_on is expected_compressor
    assert fan_sensor.is_on is expected_fan


def _build_fault_coordinator(faults: list[int], role: str = "chlorinator") -> Mock:
    """Build a coordinator with a device reporting the given faults."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", f"AABBCCDDEEFF_{role}")}}
    )
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {"status": {"online": 1}, "config": {}, "faults": 0},
        "devices": {
            "5": {
                "nodeAttr": {"online": 1},
                "faults": faults,
                "status": {},
                "config": {},
            }
        },
        "deviceType": {"5": "chlorSync"},
    }
    return coordinator


def _find_fault_sensor(entities, key: str) -> PoolSyncBinarySensor:
    """Find a fault sensor by entity key."""
    return next(entity for entity in entities if entity.entity_description.key == key)


@pytest.mark.parametrize(
    ("faults", "expected_code", "expected_active"),
    [
        ([512], 512, ["High Salt"]),
        ([4], 4, ["Low Temperature"]),
        ([0], None, []),
        ([], None, []),
        ([1], 1, ["Cell Not Connected"]),
    ],
)
def test_chlor_fault_attributes(
    faults: list[int], expected_code: int | None, expected_active: list[str]
) -> None:
    """Test the chlorinator fault sensor exposes fault_code and active_faults."""
    coordinator = _build_fault_coordinator(faults)
    sensor = PoolSyncBinarySensor(
        coordinator,
        "chlorinator",
        BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC[1][0],
        BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC[1][1],
    )

    attrs = sensor.extra_state_attributes or {}
    assert attrs.get("fault_code") == expected_code
    assert attrs.get("active_faults", []) == expected_active
    assert sensor.is_on is (expected_code is not None)
    assert sensor.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_chlorinator")
    }


def test_chem_fault_attributes() -> None:
    """Test the ChemSync fault sensor exposes decoded fault names."""
    coordinator = _build_fault_coordinator([4], role="chem_sync")
    coordinator.data["deviceType"] = {"5": "chemSync"}
    sensor = PoolSyncBinarySensor(
        coordinator,
        "chem_sync",
        BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC[1][0],
        BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC[1][1],
    )

    attrs = sensor.extra_state_attributes or {}
    assert attrs.get("fault_code") == 4
    assert attrs.get("active_faults") == ["pH Above Max"]
    assert sensor.is_on is True
    assert sensor.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_chem_sync")
    }


def test_heat_pump_fault_attributes() -> None:
    """Test the heat pump fault sensor exposes fault_code and decoded active_faults."""
    coordinator = _build_fault_coordinator([8, 0], role="heat_pump")
    coordinator.data["deviceType"] = {"5": "heatPump"}
    sensor = PoolSyncBinarySensor(
        coordinator,
        "heat_pump",
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[1][0],
        BINARY_SENSOR_DESCRIPTIONS_HEATPUMP[1][1],
    )

    attrs = sensor.extra_state_attributes or {}
    assert attrs.get("fault_code") == 8
    assert attrs.get("active_faults") == ["HP5 Lockout"]
    assert sensor.is_on is True
    assert sensor.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_heat_pump")
    }


def test_fault_attributes_none_when_no_faults() -> None:
    """Test fault attributes are None when there are no active faults."""
    coordinator = _build_fault_coordinator([0])
    sensor = PoolSyncBinarySensor(
        coordinator,
        "chlorinator",
        BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC[1][0],
        BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC[1][1],
    )

    assert sensor.extra_state_attributes is None
    assert sensor.is_on is False

"""Tests for PoolSync sensor platform setup."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, patch

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.util import dt as dt_util

from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data
from custom_components.poolsync_custom.sensor import (
    SENSOR_DESCRIPTIONS_CHLORSYNC,
    SENSOR_DESCRIPTIONS_HEATPUMP,
    SENSOR_DESCRIPTIONS_POOLSYNC,
    PoolSyncSensor,
    _parse_poolsync_datetime,
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
    coordinator.get_device_info = Mock(
        side_effect=lambda role: {
            "identifiers": {("poolsync_custom", f"AABBCCDDEEFF_{role}")}
        }
    )
    coordinator.data = {
        "poolSync": {"status": {"boardTemp": 30, "rssi": -67}},
        "devices": {
            "5": {
                "status": {"waterTemp": 24.5, "saltPPM": 3200, "boardTemp": 94.63},
                "config": {"chlorOutput": 55},
                "system": {
                    "cellSerialNum": "ABC123",
                    "cellFwVersion": "1.0",
                    "cellHwVersion": "2.0",
                },
            },
            "7": {
                "status": {"waterTemp": 82.0, "airTemp": 70.0, "boardTemp": 76.99},
                "config": {
                    "mode": 1,
                    "poolSpaMode": 0,
                    "setpoint": 84,
                    "spaSetpoint": 99,
                },
                "faults": [8, 0],
            },
        },
        "deviceType": {"5": "chlorSync", "7": "heatPump"},
    }

    added_entities: list[PoolSyncSensor] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert added_entities
    wifi_status_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "wifi_signal_status"
    )
    chlor_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "water_temp"
    )
    chlor_board_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "chlor_board_temp"
    )
    heat_mode_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "hp_mode"
    )
    heat_board_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "hp_board_temp"
    )
    heat_fault_code_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "hp_fault_code"
    )
    heat_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "hp_setpoint_temp"
    )
    heat_pool_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "hp_pool_setpoint_temp"
    )
    heat_spa_sensor = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "hp_spa_setpoint_temp"
    )
    assert wifi_status_sensor.native_value == "good"
    assert wifi_status_sensor.extra_state_attributes == {"rssi_dbm": -67}
    assert chlor_sensor.native_value == 24.5
    assert chlor_board_sensor.native_value == 94.63
    assert heat_mode_sensor.native_value == "heat_pool"
    assert heat_board_sensor.native_value == 76.99
    assert heat_fault_code_sensor.native_value == "8"
    assert heat_sensor.native_value == 84
    assert heat_pool_sensor.native_value == 84
    assert heat_spa_sensor.native_value == 99
    assert chlor_sensor.entity_description.translation_key == "water_temperature"
    assert chlor_board_sensor.entity_description.translation_key == "board_temperature"
    assert heat_board_sensor.entity_description.translation_key == "board_temperature"
    assert heat_fault_code_sensor.entity_description.translation_key == "fault_code"
    assert heat_sensor.entity_description.translation_key == "active_target_temperature"
    assert (
        heat_pool_sensor.entity_description.translation_key
        == "pool_setpoint_temperature"
    )
    assert (
        heat_spa_sensor.entity_description.translation_key == "spa_setpoint_temperature"
    )
    assert chlor_sensor.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_chlorinator")
    }
    assert heat_sensor.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_heat_pump")
    }
    assert SENSOR_DESCRIPTIONS_CHLORSYNC[0][0].key == "water_temp"
    assert SENSOR_DESCRIPTIONS_HEATPUMP[0][0].key == "hp_water_temp"


async def test_async_setup_entry_skips_missing_remapped_device(hass) -> None:
    """Test setup skips device-specific sensors when the resolved device payload is missing."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        side_effect=lambda role: {
            "identifiers": {("poolsync_custom", f"AABBCCDDEEFF_{role}")}
        }
    )
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
        "wifi_signal_status",
        "system_datetime",
        "firmware_version",
        "hardware_version",
    }


async def test_sensor_uses_parsed_runtime_values() -> None:
    """Test sensor reads current value and availability from parsed runtime data."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_controller")}}
    )
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
        "controller",
        next(
            description
            for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "system_datetime"
        ),
        lambda v: v,
    )

    assert sensor.native_value == "2026-05-20T12:30:00+00:00"
    assert sensor.available is True


async def test_wifi_signal_status_sensor_uses_enum_state_and_rssi_attribute() -> None:
    """Test Wi-Fi signal status uses enum states and exposes raw RSSI."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_controller")}}
    )
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {"status": {"rssi": -74}},
        "devices": {},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    sensor = PoolSyncSensor(
        coordinator,
        "controller",
        next(
            description
            for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "wifi_signal_status"
        ),
    )

    assert sensor.native_value == "good"
    assert sensor.available is True
    assert sensor.extra_state_attributes == {"rssi_dbm": -74}

    description = sensor.entity_description
    assert description.device_class is SensorDeviceClass.ENUM
    assert description.options == ["good", "fair", "poor"]
    assert description.entity_registry_enabled_default is True


async def test_wifi_rssi_sensor_remains_disabled_diagnostic() -> None:
    """Test the raw Wi-Fi RSSI sensor remains a disabled diagnostic sensor."""
    description = next(
        description
        for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
        if description.key == "wifi_rssi"
    )

    assert description.entity_registry_enabled_default is False


async def test_system_datetime_sensor_parses_poolsync_datetime_format() -> None:
    """Test system datetime sensor parses PoolSync local datetime strings."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_controller")}}
    )
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {
            "status": {"dateTime": "Wed May 20 19:42:37 2026"},
        },
        "devices": {},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    sensor = PoolSyncSensor(
        coordinator,
        "controller",
        next(
            description
            for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "system_datetime"
        ),
        next(
            value_fn
            for description, value_fn in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "system_datetime"
        ),
    )

    assert sensor.native_value == dt_util.as_utc(
        datetime(2026, 5, 20, 19, 42, 37, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    assert sensor.available is True


async def test_heat_pump_mode_sensor_uses_contextual_runtime_value() -> None:
    """Test heat-pump mode sensor formats the derived runtime mode context."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_heat_pump")}}
    )
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "0": {
                "config": {"mode": 3, "poolSpaMode": 0, "setpoint": 80},
                "status": {"waterTemp": 78.0, "airTemp": 70.0},
            }
        },
        "deviceType": {"0": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    sensor = PoolSyncSensor(
        coordinator,
        "heat_pump",
        next(
            description
            for description, value_fn in SENSOR_DESCRIPTIONS_HEATPUMP
            if description.key == "hp_mode"
        ),
        next(
            value_fn
            for description, value_fn in SENSOR_DESCRIPTIONS_HEATPUMP
            if description.key == "hp_mode"
        ),
    )

    assert sensor.native_value == "auto_pool"
    assert sensor.available is True


async def test_heat_pump_setpoint_sensors_expose_active_pool_and_spa_values() -> None:
    """Test heat-pump setpoint sensors expose contextual and stored targets."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_heat_pump")}}
    )
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "0": {
                "config": {
                    "mode": 1,
                    "poolSpaMode": 1,
                    "setpoint": 78,
                    "spaSetpoint": 88,
                },
                "status": {"waterTemp": 78.0, "airTemp": 70.0},
            }
        },
        "deviceType": {"0": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    sensors_by_key = {
        description.key: PoolSyncSensor(coordinator, "heat_pump", description, value_fn)
        for description, value_fn in SENSOR_DESCRIPTIONS_HEATPUMP
        if description.key
        in {"hp_setpoint_temp", "hp_pool_setpoint_temp", "hp_spa_setpoint_temp"}
    }

    assert sensors_by_key["hp_setpoint_temp"].native_value == 88
    assert sensors_by_key["hp_pool_setpoint_temp"].native_value == 78
    assert sensors_by_key["hp_spa_setpoint_temp"].native_value == 88


async def test_heat_pump_sensors_stay_fahrenheit_native() -> None:
    """Test heat-pump temperatures remain Fahrenheit-native."""
    sensors_by_key = {
        description.key: description
        for description, _ in SENSOR_DESCRIPTIONS_HEATPUMP
        if description.key
        in {
            "hp_water_temp",
            "hp_air_temp",
            "hp_setpoint_temp",
            "hp_pool_setpoint_temp",
            "hp_spa_setpoint_temp",
        }
    }

    assert (
        sensors_by_key["hp_water_temp"].native_unit_of_measurement
        is UnitOfTemperature.FAHRENHEIT
    )
    assert (
        sensors_by_key["hp_air_temp"].native_unit_of_measurement
        is UnitOfTemperature.FAHRENHEIT
    )
    assert (
        sensors_by_key["hp_setpoint_temp"].native_unit_of_measurement
        is UnitOfTemperature.FAHRENHEIT
    )
    assert (
        sensors_by_key["hp_pool_setpoint_temp"].native_unit_of_measurement
        is UnitOfTemperature.FAHRENHEIT
    )
    assert (
        sensors_by_key["hp_spa_setpoint_temp"].native_unit_of_measurement
        is UnitOfTemperature.FAHRENHEIT
    )

    board_temp_description = next(
        description
        for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
        if description.key == "board_temp"
    )
    assert (
        board_temp_description.native_unit_of_measurement is UnitOfTemperature.CELSIUS
    )


def test_parse_poolsync_datetime_rejects_invalid_values() -> None:
    """Test PoolSync datetime parsing rejects invalid and non-string values."""
    assert _parse_poolsync_datetime(None) is None
    assert _parse_poolsync_datetime("not-a-date") is None


async def test_async_setup_entry_warns_on_missing_top_level_keys(hass, caplog) -> None:
    """Test sensor setup warns when top-level payload keys are missing."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        side_effect=lambda role: {
            "identifiers": {("poolsync_custom", f"AABBCCDDEEFF_{role}")}
        }
    )
    coordinator.data = {}
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    added_entities: list[PoolSyncSensor] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert (
        "Initial data is missing 'poolSync' or 'devices' top-level keys" in caplog.text
    )
    assert added_entities


async def test_sensor_handles_value_fn_errors_and_stringifies_unknown_values() -> None:
    """Test sensors handle processor failures and stringify unsupported raw values."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_controller")}}
    )
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {
            "status": {
                "boardTemp": {"value": 30},
                "dateTime": "2026-05-20T12:30:00+00:00",
            },
            "system": {"fwVersion": "1.2.3"},
        },
        "devices": {},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    failing_sensor = PoolSyncSensor(
        coordinator,
        "controller",
        next(
            description
            for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "system_datetime"
        ),
        lambda value: int(value),
    )
    board_sensor = PoolSyncSensor(
        coordinator,
        "controller",
        next(
            description
            for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "board_temp"
        ),
    )

    assert failing_sensor.native_value is None
    assert board_sensor.native_value == "{'value': 30}"
    assert board_sensor.available is True


async def test_sensor_handle_coordinator_update_refreshes_and_wifi_attrs() -> None:
    """Test sensor updates refresh parsed data and Wi-Fi attrs only expose numeric RSSI."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_controller")}}
    )
    coordinator.last_update_success = True
    coordinator.data = {
        "poolSync": {"status": {"rssi": -74}},
        "devices": {},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    sensor = PoolSyncSensor(
        coordinator,
        "controller",
        next(
            description
            for description, _ in SENSOR_DESCRIPTIONS_POOLSYNC
            if description.key == "wifi_signal_status"
        ),
    )

    coordinator.data["poolSync"]["status"]["rssi"] = "bad"
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)
    sensor.async_write_ha_state = Mock()

    with patch(
        "custom_components.poolsync_custom.sensor.ensure_parsed_data",
        side_effect=lambda coord, refresh=False: coord.parsed_data,
    ) as mock_ensure:
        sensor._handle_coordinator_update()

    assert any(call.kwargs == {"refresh": True} for call in mock_ensure.call_args_list)
    assert sensor.extra_state_attributes is None

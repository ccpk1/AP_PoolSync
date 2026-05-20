"""Sensor platform for the PoolSync Custom integration."""

import dataclasses
import logging
from collections.abc import Callable
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import METRIC_SYSTEM

from .const import CHLORINATOR_ID, HEATPUMP_ID
from .coordinator import PoolSyncDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _change_temperature_unit(description, is_metric):
    if is_metric:
        return description

    if description.native_unit_of_measurement is UnitOfTemperature.CELSIUS:
        description = dataclasses.replace(
            description, native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT
        )

    return description


def _get_value_from_path(
    data: dict[str, Any] | None, path: list[str | int]
) -> Any:
    """Safely retrieve a value from a nested dictionary using a path list."""
    if data is None:
        return None
    value = data
    try:
        for i, key_or_index in enumerate(path):
            if value is None:
                return None
            if isinstance(key_or_index, str):
                if not isinstance(value, dict):
                    return None
                value = value.get(key_or_index)
            elif isinstance(
                key_or_index, int
            ):  # Should not be needed for current paths
                if not isinstance(value, list) or not (0 <= key_or_index < len(value)):
                    return None
                value = value[key_or_index]
            else:
                return None  # Invalid path component type
        return value
    except (KeyError, IndexError, TypeError):
        return None


# Corrected SENSOR_DESCRIPTIONS paths
SENSOR_DESCRIPTIONS_CHLORSYNC: tuple[
    tuple[SensorEntityDescription, list[str], Callable[[Any], Any] | None], ...
] = (
    # --- ChlorSync Device Sensors (data from `devices.0`) ---
    (
        SensorEntityDescription(
            key="water_temp",
            name="Water Temperature",
            icon="mdi:coolant-temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        ["devices", CHLORINATOR_ID, "status", "waterTemp"],
        None,
    ),
    (
        SensorEntityDescription(
            key="salt_ppm",
            name="Salt Level",
            icon="mdi:shaker-outline",
            native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        ["devices", CHLORINATOR_ID, "status", "saltPPM"],
        None,
    ),
    (
        SensorEntityDescription(
            key="flow_rate",
            name="Chlor Flow Rate",
            icon="mdi:pump",
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        ["devices", CHLORINATOR_ID, "status", "flowRate"],
        None,
    ),
    (
        SensorEntityDescription(
            key="chlor_output_setting",
            name="Chlorinator Output Setting",
            icon="mdi:percent-circle",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        ["devices", CHLORINATOR_ID, "config", "chlorOutput"],
        None,
    ),  # This is the sensor for the setting
    (
        SensorEntityDescription(
            key="boost_remaining",
            name="Boost Time Remaining",
            icon="mdi:timer-sand",
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        ["devices", CHLORINATOR_ID, "status", "boostRemaining"],
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_fwd_current",
            name="Cell Forward Current",
            icon="mdi:current-dc",
            native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["devices", CHLORINATOR_ID, "status", "fwdCurrent"],
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_rev_current",
            name="Cell Reverse Current",
            icon="mdi:current-dc",
            native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["devices", CHLORINATOR_ID, "status", "revCurrent"],
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_output_voltage",
            name="Cell Output Voltage",
            icon="mdi:lightning-bolt",
            native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["devices", CHLORINATOR_ID, "status", "outVoltage"],
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_serial_number",
            name="Cell Serial Number",
            icon="mdi:barcode-scan",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["devices", CHLORINATOR_ID, "system", "cellSerialNum"],
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_firmware_version",
            name="Cell Firmware Version",
            icon="mdi:chip",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["devices", CHLORINATOR_ID, "system", "cellFwVersion"],
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_hardware_version",
            name="Cell Hardware Version",
            icon="mdi:memory",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["devices", CHLORINATOR_ID, "system", "cellHwVersion"],
        None,
    ),
)
SENSOR_DESCRIPTIONS_POOLSYNC: tuple[
    tuple[SensorEntityDescription, list[str], Callable[[Any], Any] | None], ...
] = (
    # --- System Wide Sensors (data from `poolSync`) ---
    (
        SensorEntityDescription(
            key="board_temp",
            name="Board Temperature",
            icon="mdi:thermometer-lines",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=0,
        ),
        ["poolSync", "status", "boardTemp"],
        None,
    ),
    (
        SensorEntityDescription(
            key="wifi_rssi",
            name="Wi-Fi Signal Strength",
            icon="mdi:wifi-strength-2",
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["poolSync", "status", "rssi"],
        None,
    ),
    (
        SensorEntityDescription(
            key="system_datetime",
            name="System Date/Time",
            icon="mdi:clock-outline",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["poolSync", "status", "dateTime"],
        lambda v: dt_util.parse_datetime(v) if isinstance(v, str) else None,
    ),
    (
        SensorEntityDescription(
            key="firmware_version",
            name="System Firmware Version",
            icon="mdi:chip",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["poolSync", "system", "fwVersion"],
        None,
    ),
    (
        SensorEntityDescription(
            key="hardware_version",
            name="System Hardware Version",
            icon="mdi:memory",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["poolSync", "system", "hwVersion"],
        None,
    ),
    (
        SensorEntityDescription(
            key="uptime_seconds",
            name="System Uptime",
            icon="mdi:timer-outline",
            native_unit_of_measurement="s",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        ["poolSync", "stats", "upTimeSecs"],
        None,
    ),
)
SENSOR_DESCRIPTIONS_HEATPUMP: tuple[
    tuple[SensorEntityDescription, list[str], Callable[[Any], Any] | None], ...
] = (
    # --- HeatPump Device Sensors (data from `devices.0`) ---
    (
        SensorEntityDescription(
            key="hp_water_temp",
            name="Water Temperature",
            icon="mdi:coolant-temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        ["devices", HEATPUMP_ID, "status", "waterTemp"],
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_air_temp",
            name="Air Temperature",
            icon="mdi:coolant-temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        ["devices", HEATPUMP_ID, "status", "airTemp"],
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_mode",
            name="Mode",
            icon="mdi:pump",
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        ["devices", HEATPUMP_ID, "config", "mode"],
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_setpoint_temp",
            name="SetPoint Temperature",
            icon="mdi:coolant-temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        ["devices", HEATPUMP_ID, "config", "setpoint"],
        None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    sensors_to_add: list[PoolSyncSensor] = []

    # Check for the presence of top-level keys to ensure basic data structure
    if not coordinator.data or not (
        isinstance(coordinator.data.get("poolSync"), dict)
        and isinstance(coordinator.data.get("devices"), dict)
    ):
        _LOGGER.warning(
            "Coordinator %s: Initial data is missing 'poolSync' or 'devices' top-level keys. Sensor setup may be incomplete.",
            coordinator.name,
        )
        # Still attempt to add sensors; they will become unavailable if their specific data is missing.

    heatpump_id = HEATPUMP_ID
    chlor_id = CHLORINATOR_ID
    if coordinator.data and isinstance(coordinator.data.get("deviceType"), dict):
        deviceTypes = coordinator.data.get("deviceType")
        temp = [key for key, value in deviceTypes.items() if value == "heatPump"]
        heatpump_id = temp[0] if temp else "-1"
        temp = [key for key, value in deviceTypes.items() if value == "chlorSync"]
        chlor_id = temp[0] if temp else "-1"

    # change temperature unit
    is_metric = hass.config.units is METRIC_SYSTEM

    for description, data_path, value_fn in SENSOR_DESCRIPTIONS_POOLSYNC:
        sensors_to_add.append(
            PoolSyncSensor(coordinator, description, data_path, value_fn)
        )

    if chlor_id != "-1":
        for description, data_path, value_fn in SENSOR_DESCRIPTIONS_CHLORSYNC:
            description = _change_temperature_unit(description, is_metric)
            data_path[1] = chlor_id
            sensors_to_add.append(
                PoolSyncSensor(coordinator, description, data_path, value_fn)
            )

    if heatpump_id != "-1":
        for description, data_path, value_fn in SENSOR_DESCRIPTIONS_HEATPUMP:
            description = _change_temperature_unit(description, is_metric)
            data_path[1] = heatpump_id
            sensors_to_add.append(
                PoolSyncSensor(coordinator, description, data_path, value_fn)
            )

    if sensors_to_add:
        async_add_entities(sensors_to_add)
        _LOGGER.info(
            "Added %d PoolSync sensors for %s", len(sensors_to_add), coordinator.name
        )


class PoolSyncSensor(CoordinatorEntity[PoolSyncDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: SensorEntityDescription,
        data_path: list[str],
        value_fn: Callable[[Any], Any] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._data_path = data_path
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.mac_address}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> StateType:
        value = _get_value_from_path(self.coordinator.data, self._data_path)
        if value is None:
            return None
        if self._value_fn:
            try:
                return self._value_fn(value)
            except Exception as e:
                _LOGGER.error(
                    "Sensor %s: Error processing value '%s' with value_fn: %s",
                    self.entity_description.key,
                    value,
                    e,
                )
                return None
        if isinstance(value, (str, int, float)) or value is None:
            return value
        try:
            return str(value)
        except Exception:
            return None

    @property
    def available(self) -> bool:
        coordinator_available = super().available
        val_at_path = _get_value_from_path(self.coordinator.data, self._data_path)
        value_is_present_and_processable = False
        if val_at_path is not None:
            if self._value_fn:
                try:
                    value_is_present_and_processable = (
                        self._value_fn(val_at_path) is not None
                    )
                except Exception:
                    value_is_present_and_processable = False
            else:
                value_is_present_and_processable = True
        return coordinator_available and value_is_present_and_processable

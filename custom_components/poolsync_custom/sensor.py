"""Sensor platform for the PoolSync Custom integration."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Sequence
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
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import METRIC_SYSTEM

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import ensure_parsed_data, get_sensor_value

_LOGGER = logging.getLogger(__name__)

type SensorDescription = tuple[SensorEntityDescription, Callable[[Any], Any] | None]


def _change_temperature_unit(description, is_metric):
    if is_metric:
        return description

    if description.native_unit_of_measurement is UnitOfTemperature.CELSIUS:
        description = dataclasses.replace(
            description, native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT
        )

    return description


SENSOR_DESCRIPTIONS_CHLORSYNC: tuple[SensorDescription, ...] = (
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
        None,
    ),
    (
        SensorEntityDescription(
            key="boost_remaining",
            name="Boost Time Remaining",
            icon="mdi:timer-sand",
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        ),
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
        None,
    ),
)
SENSOR_DESCRIPTIONS_POOLSYNC: tuple[SensorDescription, ...] = (
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
        None,
    ),
)
SENSOR_DESCRIPTIONS_HEATPUMP: tuple[SensorDescription, ...] = (
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
        None,
    ),
)


def _build_sensor_entities(
    coordinator: PoolSyncDataUpdateCoordinator,
    descriptions: Sequence[SensorDescription],
    is_metric: bool,
) -> list[PoolSyncSensor]:
    """Build sensor entities."""
    sensors: list[PoolSyncSensor] = []

    for description, value_fn in descriptions:
        entity_description = _change_temperature_unit(description, is_metric)
        sensors.append(PoolSyncSensor(coordinator, entity_description, value_fn))

    return sensors


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    sensors_to_add: list[PoolSyncSensor] = []
    parsed_data = ensure_parsed_data(coordinator)
    data = coordinator.data or {}

    # Check for the presence of top-level keys to ensure basic data structure
    poolsync_data_present = isinstance(data.get("poolSync"), dict)
    devices = data.get("devices") if isinstance(data.get("devices"), dict) else None

    if not poolsync_data_present or devices is None:
        _LOGGER.warning(
            "Coordinator %s: Initial data is missing 'poolSync' or 'devices' top-level keys. Sensor setup may be incomplete.",
            coordinator.name,
        )
        # Still attempt to add sensors; they will become unavailable if their specific data is missing.

    heatpump_id = parsed_data.heat_pump.device_id
    chlor_id = parsed_data.chlorinator.device_id

    # change temperature unit
    is_metric = hass.config.units is METRIC_SYSTEM

    sensors_to_add.extend(
        _build_sensor_entities(
            coordinator, SENSOR_DESCRIPTIONS_POOLSYNC, is_metric=is_metric
        )
    )

    if chlor_id and parsed_data.chlorinator.is_present:
        sensors_to_add.extend(
            _build_sensor_entities(
                coordinator,
                SENSOR_DESCRIPTIONS_CHLORSYNC,
                is_metric=is_metric,
            )
        )
    elif chlor_id and devices is not None:
        _LOGGER.warning(
            "Coordinator %s data is missing chlorinator device %s. Skipping chlorinator sensors.",
            coordinator.name,
            chlor_id,
        )

    if heatpump_id and parsed_data.heat_pump.is_present:
        sensors_to_add.extend(
            _build_sensor_entities(
                coordinator,
                SENSOR_DESCRIPTIONS_HEATPUMP,
                is_metric=is_metric,
            )
        )
    elif heatpump_id and devices is not None:
        _LOGGER.warning(
            "Coordinator %s data is missing heat pump device %s. Skipping heat pump sensors.",
            coordinator.name,
            heatpump_id,
        )

    if sensors_to_add:
        async_add_entities(sensors_to_add)
        _LOGGER.info(
            "Added %d PoolSync sensors for %s", len(sensors_to_add), coordinator.name
        )


class PoolSyncSensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], SensorEntity
):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: SensorEntityDescription,
        value_fn: Callable[[Any], Any] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.mac_address}_{description.key}"
        self._attr_device_info = coordinator.device_info
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        """Update cached entity attributes from coordinator data."""
        value = get_sensor_value(
            ensure_parsed_data(self.coordinator), self.entity_description.key
        )
        if value is None:
            self._attr_native_value = None
            self._attr_available = False
            return
        if self._value_fn:
            try:
                self._attr_native_value = self._value_fn(value)
            except (AttributeError, TypeError, ValueError) as err:
                _LOGGER.error(
                    "Sensor %s: Error processing value '%s' with value_fn: %s",
                    self.entity_description.key,
                    value,
                    err,
                )
                self._attr_native_value = None
                self._attr_available = False
                return
        elif isinstance(value, (str, int, float)):
            self._attr_native_value = value
        else:
            self._attr_native_value = str(value)

        self._attr_available = super().available and self._attr_native_value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        ensure_parsed_data(self.coordinator, refresh=True)
        self._update_attrs()
        super()._handle_coordinator_update()

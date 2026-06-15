"""Sensor platform for the PoolSync Custom integration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
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

from .coordinator import PoolSyncDataUpdateCoordinator, PoolSyncDeviceInfoRole
from .runtime import ensure_parsed_data, get_sensor_value

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator-based updates

type SensorDescription = tuple[SensorEntityDescription, Callable[[Any], Any] | None]

_POOLSYNC_DATETIME_FORMAT = "%a %b %d %H:%M:%S %Y"


def _parse_poolsync_datetime(value: Any) -> datetime | None:
    """Parse PoolSync timestamp strings into timezone-aware datetimes."""
    if not isinstance(value, str):
        return None

    if parsed := dt_util.parse_datetime(value):
        return parsed

    try:
        local_datetime = datetime.strptime(value, _POOLSYNC_DATETIME_FORMAT)
    except ValueError:
        return None

    return dt_util.as_utc(local_datetime.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE))


SENSOR_DESCRIPTIONS_CHLORSYNC: tuple[SensorDescription, ...] = (
    (
        SensorEntityDescription(
            key="water_temp",
            translation_key="water_temperature",
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
            translation_key="salt_level",
            native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="chlor_board_temp",
            translation_key="board_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="flow_rate",
            translation_key="flow_rate",
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="chlor_output_setting",
            translation_key="output_setting",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="boost_remaining",
            translation_key="boost_time_remaining",
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_fwd_current",
            translation_key="cell_forward_current",
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
            translation_key="cell_reverse_current",
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
            translation_key="cell_output_voltage",
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
            translation_key="cell_serial_number",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_firmware_version",
            translation_key="cell_firmware_version",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="cell_hardware_version",
            translation_key="cell_hardware_version",
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
            translation_key="board_temperature",
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
            translation_key="wifi_signal_strength",
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
            key="wifi_signal_status",
            translation_key="wifi_signal_status",
            device_class=SensorDeviceClass.ENUM,
            options=["good", "fair", "poor"],
            entity_registry_enabled_default=True,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="system_datetime",
            translation_key="date_time",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        _parse_poolsync_datetime,
    ),
    (
        SensorEntityDescription(
            key="firmware_version",
            translation_key="firmware_version",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hardware_version",
            translation_key="hardware_version",
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
            translation_key="water_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_air_temp",
            translation_key="air_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_board_temp",
            translation_key="board_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_fault_code",
            translation_key="fault_code",
            entity_registry_enabled_default=True,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        str,
    ),
    (
        SensorEntityDescription(
            key="hp_mode",
            translation_key="mode",
            native_unit_of_measurement=None,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_setpoint_temp",
            translation_key="active_target_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_pool_setpoint_temp",
            translation_key="pool_setpoint_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_spa_setpoint_temp",
            translation_key="spa_setpoint_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_water_temp2",
            translation_key="outlet_water_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_ds1_temp",
            translation_key="defrost_sensor_1_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_ds2_temp",
            translation_key="defrost_sensor_2_temperature",
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            suggested_display_precision=1,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_top_fault_code",
            translation_key="top_fault_code",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="hp_top_fault_count",
            translation_key="top_fault_count",
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        ),
        None,
    ),
)


def _build_sensor_entities(
    coordinator: PoolSyncDataUpdateCoordinator,
    descriptions: Sequence[SensorDescription],
    role: PoolSyncDeviceInfoRole,
) -> list[PoolSyncSensor]:
    """Build sensor entities."""
    sensors: list[PoolSyncSensor] = []

    for description, value_fn in descriptions:
        sensors.append(PoolSyncSensor(coordinator, role, description, value_fn))

    return sensors


async def async_setup_entry(
    _hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PoolSync sensors from a config entry."""
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    sensors_to_add: list[PoolSyncSensor] = []
    parsed_data = ensure_parsed_data(coordinator)
    data = coordinator.data or {}

    # Check for the presence of top-level keys to ensure basic data structure
    poolsync_data_present = isinstance(data.get("poolSync"), dict)
    devices = data.get("devices") if isinstance(data.get("devices"), dict) else None

    if not poolsync_data_present or devices is None:
        _LOGGER.warning(
            "Coordinator %s: Initial data missing 'poolSync' or 'devices' keys."
            " Sensor setup may be incomplete.",
            coordinator.name,
        )
        # Still attempt to add sensors; they will become unavailable
        # if their specific data is missing.

    heatpump_id = parsed_data.heat_pump.device_id
    chlor_id = parsed_data.chlorinator.device_id

    sensors_to_add.extend(
        _build_sensor_entities(coordinator, SENSOR_DESCRIPTIONS_POOLSYNC, "controller")
    )

    if chlor_id and parsed_data.chlorinator.is_present:
        sensors_to_add.extend(
            _build_sensor_entities(
                coordinator,
                SENSOR_DESCRIPTIONS_CHLORSYNC,
                "chlorinator",
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
                "heat_pump",
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
    """Representation of a PoolSync sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        role: PoolSyncDeviceInfoRole,
        description: SensorEntityDescription,
        value_fn: Callable[[Any], Any] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.mac_address}_{description.key}"
        self._attr_device_info = coordinator.get_device_info(role)
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

    @property
    def extra_state_attributes(  # pyright: ignore[reportIncompatibleVariableOverride]
        self,
    ) -> dict[str, Any] | None:
        """Return additional state attributes for support-focused sensors."""
        if self.entity_description.key != "wifi_signal_status":
            return None

        rssi = get_sensor_value(ensure_parsed_data(self.coordinator), "wifi_rssi")
        if not isinstance(rssi, (int, float)):
            return None

        return {"rssi_dbm": rssi}

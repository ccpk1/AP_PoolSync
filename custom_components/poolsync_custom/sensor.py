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
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import (
    build_unique_id,
    ensure_parsed_data,
    get_equipment_runtime,
    get_sensor_value,
)

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
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
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
    (
        SensorEntityDescription(
            key="cell_rail_voltage",
            translation_key="cell_rail_voltage",
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
            key="temp_comp_output",
            translation_key="temperature_compensation_output",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="drv_model_num",
            translation_key="driver_model_number",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="drv_fw_version",
            translation_key="driver_firmware_version",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="drv_hw_version",
            translation_key="driver_hardware_version",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
)
SENSOR_DESCRIPTIONS_CHEMSYNC: tuple[SensorDescription, ...] = (
    (
        SensorEntityDescription(
            key="chem_ph",
            translation_key="ph",
            device_class=SensorDeviceClass.PH,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="chem_orp",
            translation_key="orp",
            native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="chem_board_temp",
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
            key="chem_acid_consumed",
            translation_key="acid_consumed",
            native_unit_of_measurement=UnitOfVolume.FLUID_OUNCES,
            device_class=SensorDeviceClass.VOLUME,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="chem_fw_version",
            translation_key="chem_firmware_version",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="chem_hw_version",
            translation_key="chem_hardware_version",
            entity_registry_enabled_default=False,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="chem_model_num",
            translation_key="chem_model_number",
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


def get_valid_entity_keys() -> dict[str, set[str]]:
    """Return the set of valid entity keys for each role, for orphan cleanup."""
    return {
        "controller": {d[0].key for d in SENSOR_DESCRIPTIONS_POOLSYNC},
        "chlorinator": {d[0].key for d in SENSOR_DESCRIPTIONS_CHLORSYNC},
        "chem_sync": {d[0].key for d in SENSOR_DESCRIPTIONS_CHEMSYNC},
        "heat_pump": {d[0].key for d in SENSOR_DESCRIPTIONS_HEATPUMP},
        "equipment": {d[0].key for d in SENSOR_DESCRIPTIONS_EQUIPMENT},
    }


SENSOR_DESCRIPTIONS_EQUIPMENT: tuple[SensorDescription, ...] = (
    (
        SensorEntityDescription(
            key="pump_rpm",
            translation_key="pump_rpm",
            native_unit_of_measurement="RPM",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="valve_position",
            translation_key="valve_position",
        ),
        None,
    ),
    (
        SensorEntityDescription(
            key="group_info",
            translation_key="group_info",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=True,
        ),
        None,
    ),
)


def _build_sensor_entities(
    coordinator: PoolSyncDataUpdateCoordinator,
    descriptions: Sequence[SensorDescription],
    role: str,
    device_index: int = 0,
    device_node_addr: int | None = None,
) -> list[PoolSyncSensor]:
    """Build sensor entities for a specific device instance."""
    sensors: list[PoolSyncSensor] = []

    for description, value_fn in descriptions:
        sensors.append(
            PoolSyncSensor(
                coordinator,
                role,
                description,
                value_fn,
                _device_index=device_index,
                _device_node_addr=device_node_addr,
            )
        )

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
    has_devices = isinstance(data.get("devices"), dict)

    if not poolsync_data_present or not has_devices:
        _LOGGER.warning(
            "Coordinator %s: Initial data missing 'poolSync' or 'devices' keys."
            " Sensor setup may be incomplete.",
            coordinator.name,
        )

    sensors_to_add.extend(
        _build_sensor_entities(coordinator, SENSOR_DESCRIPTIONS_POOLSYNC, "controller")
    )

    for index, device in enumerate(parsed_data.devices.get("chlorinator", [])):
        if device.is_present:
            sensors_to_add.extend(
                _build_sensor_entities(
                    coordinator,
                    SENSOR_DESCRIPTIONS_CHLORSYNC,
                    "chlorinator",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        elif has_devices:
            _LOGGER.warning(
                "Coordinator %s data is missing chlorinator device %s. Skipping chlorinator sensors.",
                coordinator.name,
                device.device_id,
            )

    for index, device in enumerate(parsed_data.devices.get("heat_pump", [])):
        if device.is_present:
            sensors_to_add.extend(
                _build_sensor_entities(
                    coordinator,
                    SENSOR_DESCRIPTIONS_HEATPUMP,
                    "heat_pump",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        elif has_devices:
            _LOGGER.warning(
                "Coordinator %s data is missing heat pump device %s. Skipping heat pump sensors.",
                coordinator.name,
                device.device_id,
            )

    for index, device in enumerate(parsed_data.devices.get("chem_sync", [])):
        if device.is_present:
            sensors_to_add.extend(
                _build_sensor_entities(
                    coordinator,
                    SENSOR_DESCRIPTIONS_CHEMSYNC,
                    "chem_sync",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        elif has_devices:
            _LOGGER.warning(
                "Coordinator %s data is missing chem_sync device %s. Skipping chem_sync sensors.",
                coordinator.name,
                device.device_id,
            )

    if sensors_to_add:
        async_add_entities(sensors_to_add)
        _LOGGER.info(
            "Added %d PoolSync sensors for %s", len(sensors_to_add), coordinator.name
        )

    # Equipment sensors: created on their own equipment devices
    if equip_runtime := get_equipment_runtime(parsed_data):
        equip_sensors: list[PoolSyncSensor] = []
        for equip in equip_runtime.equipment.values():
            device_info = coordinator.get_equipment_device_info(equip)
            prefix = f"{coordinator.mac_address}_equip_{equip.slot_key}_"
            if equip.is_pump:
                for desc, vfn in [
                    (d, v)
                    for d, v in SENSOR_DESCRIPTIONS_EQUIPMENT
                    if d.key == "pump_rpm"
                ]:
                    equip_sensors.append(
                        PoolSyncSensor(
                            coordinator,
                            "equipment",
                            desc,
                            vfn,
                            _device_info=device_info,
                            _unique_id=f"{prefix}{desc.key}",
                        )
                    )
            elif equip.is_valve:
                for desc, vfn in [
                    (d, v)
                    for d, v in SENSOR_DESCRIPTIONS_EQUIPMENT
                    if d.key == "valve_position"
                ]:
                    equip_sensors.append(
                        PoolSyncSensor(
                            coordinator,
                            "equipment",
                            desc,
                            vfn,
                            _device_info=device_info,
                            _unique_id=f"{prefix}{desc.key}",
                        )
                    )

        # Group info sensor on the controller device
        for desc, vfn in [
            (d, v) for d, v in SENSOR_DESCRIPTIONS_EQUIPMENT if d.key == "group_info"
        ]:
            equip_sensors.append(PoolSyncSensor(coordinator, "controller", desc, vfn))

        if equip_sensors:
            async_add_entities(equip_sensors)


class PoolSyncSensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], SensorEntity
):
    """Representation of a PoolSync sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        role: str,
        description: SensorEntityDescription,
        value_fn: Callable[[Any], Any] | None = None,
        *,
        _device_info: DeviceInfo | None = None,
        _unique_id: str | None = None,
        _device_index: int = 0,
        _device_node_addr: int | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._value_fn = value_fn
        self._role_key = role
        self._device_index = _device_index
        self._device_node_addr = _device_node_addr
        self._attr_unique_id = _unique_id or self._build_unique_id(
            coordinator.mac_address, role, description.key
        )
        self._attr_device_info = _device_info or coordinator.get_device_info(
            role, index=_device_index
        )
        self._update_attrs()

    def _build_unique_id(self, mac_address: str, role: str, key: str) -> str:
        """Build a stable unique ID, delegating to the shared function."""
        return build_unique_id(
            mac_address,
            role,
            key,
            device_index=self._device_index,
            device_node_addr=self._device_node_addr,
        )

    @callback
    def _update_attrs(self) -> None:
        """Update cached entity attributes from coordinator data."""
        parsed_data = ensure_parsed_data(self.coordinator)
        if self._device_index > 0:
            value = get_sensor_value(
                parsed_data,
                self.entity_description.key,
                role_key=self._role_key,
                index=self._device_index,
            )
        else:
            value = get_sensor_value(parsed_data, self.entity_description.key)
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
        parsed_data = ensure_parsed_data(self.coordinator)

        if self.entity_description.key == "wifi_signal_status":
            rssi = get_sensor_value(parsed_data, "wifi_rssi")
            if isinstance(rssi, (int, float)):
                return {"rssi_dbm": rssi}
            return None

        if self.entity_description.key == "group_info":
            equip_runtime = get_equipment_runtime(parsed_data)
            if equip_runtime is not None:
                return equip_runtime.active_group_attributes
            return None

        return None

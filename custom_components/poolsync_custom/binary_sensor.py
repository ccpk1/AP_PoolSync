"""Binary sensor platform for the PoolSync Custom integration."""

import logging
from collections.abc import Callable
from typing import Any, cast

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CHLORINATOR_ID,
    HEATPUMP_ID,
)
from .coordinator import PoolSyncDataUpdateCoordinator
from .sensor import _get_value_from_path  # Reuse helper

_LOGGER = logging.getLogger(__name__)

# Corrected BINARY_SENSOR_DESCRIPTIONS paths
BINARY_SENSOR_DESCRIPTIONS_POOLSYNC: tuple[
    tuple[
        BinarySensorEntityDescription,
        list[str | int],
        Callable[[Any], bool | None] | None,
    ],
    ...,
] = (
    # --- System Wide Binary Sensors (data from `poolSync`) ---
    (
        BinarySensorEntityDescription(
            key="poolsync_online",
            name="PoolSync Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        ["poolSync", "status", "online"],
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="service_mode_active",
            name="Service Mode",
            icon="mdi:account-wrench",
            entity_registry_enabled_default=True,
        ),
        ["poolSync", "config", "serviceMode"],
        lambda v: bool(v) if isinstance(v, int) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="system_fault",
            name="System Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        ["poolSync", "faults"],
        lambda v: bool(v) if isinstance(v, int) else None,
    ),
)
BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC: tuple[
    tuple[
        BinarySensorEntityDescription,
        list[str | int],
        Callable[[Any], bool | None] | None,
    ],
    ...,
] = (
    # --- ChlorSync Device Specific Binary Sensors (data from `devices.0`) ---
    (
        BinarySensorEntityDescription(
            key="chlorsync_online",
            name="ChlorSync Module Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        ["devices", CHLORINATOR_ID, "nodeAttr", "online"],
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),  # CORRECTED PATH
    (
        BinarySensorEntityDescription(
            key="chlorsync_fault",
            name="ChlorSync Module Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        ["devices", CHLORINATOR_ID, "faults"],
        lambda v: isinstance(v, list) and any(fault_code != 0 for fault_code in v),
    ),  # CORRECTED PATH
)
BINARY_SENSOR_DESCRIPTIONS_HEATPUMP: tuple[
    tuple[
        BinarySensorEntityDescription,
        list[str | int],
        Callable[[Any], bool | None] | None,
    ],
    ...,
] = (
    # --- ChlorSync Device Specific Binary Sensors (data from `devices.0`) ---
    (
        BinarySensorEntityDescription(
            key="heatpump_online",
            name="HeatPump Module Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        ["devices", HEATPUMP_ID, "nodeAttr", "online"],
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),  # CORRECTED PATH
    (
        BinarySensorEntityDescription(
            key="heatpump_fault",
            name="HeatPump Module Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        ["devices", HEATPUMP_ID, "faults"],
        lambda v: isinstance(v, list) and any(fault_code != 0 for fault_code in v),
    ),  # CORRECTED PATH
    (
        BinarySensorEntityDescription(
            key="heatpump_flow",
            name="HeatPump Flow",
            entity_registry_enabled_default=True,
        ),
        ["devices", HEATPUMP_ID, "status", "ctrlFlags"],
        lambda v: bool(v >= 1) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_compressor",
            name="HeatPump Compressor",
            entity_registry_enabled_default=True,
        ),
        ["devices", HEATPUMP_ID, "status", "stateFlags"],
        lambda v: bool(v == 8) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_fan",
            name="HeatPump Fan",
            entity_registry_enabled_default=True,
        ),
        ["devices", HEATPUMP_ID, "status", "stateFlags"],
        lambda v: bool(v == 8 or v == 520) if isinstance(v, (bool, int)) else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    binary_sensors_to_add: list[PoolSyncBinarySensor] = []

    if not coordinator.data or not (
        isinstance(coordinator.data.get("poolSync"), dict)
        and isinstance(coordinator.data.get("devices"), dict)
    ):
        _LOGGER.warning(
            "Coordinator %s: Initial data is missing 'poolSync' or 'devices' top-level keys. Binary sensor setup may be incomplete.",
            coordinator.name,
        )

    heatpump_id = HEATPUMP_ID
    chlor_id = CHLORINATOR_ID
    if coordinator.data and isinstance(coordinator.data.get("deviceType"), dict):
        deviceTypes = coordinator.data.get("deviceType")
        temp = [key for key, value in deviceTypes.items() if value == "heatPump"]
        heatpump_id = temp[0] if temp else "-1"
        temp = [key for key, value in deviceTypes.items() if value == "chlorSync"]
        chlor_id = temp[0] if temp else "-1"

    for description, data_path, value_fn in BINARY_SENSOR_DESCRIPTIONS_POOLSYNC:
        binary_sensors_to_add.append(
            PoolSyncBinarySensor(coordinator, description, data_path, value_fn)
        )

    if chlor_id != "-1":
        for description, data_path, value_fn in BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC:
            data_path[1] = chlor_id
            binary_sensors_to_add.append(
                PoolSyncBinarySensor(coordinator, description, data_path, value_fn)
            )

    if heatpump_id != "-1":
        for description, data_path, value_fn in BINARY_SENSOR_DESCRIPTIONS_HEATPUMP:
            data_path[1] = heatpump_id
            binary_sensors_to_add.append(
                PoolSyncBinarySensor(coordinator, description, data_path, value_fn)
            )

    if binary_sensors_to_add:
        async_add_entities(binary_sensors_to_add)
        _LOGGER.info(
            "Added %d PoolSync binary sensors for %s",
            len(binary_sensors_to_add),
            coordinator.name,
        )


class PoolSyncBinarySensor(
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: BinarySensorEntityDescription,
        data_path: list[str | int],
        value_fn: Callable[[Any], bool | None] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._data_path = data_path
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.mac_address}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        raw_value = _get_value_from_path(self.coordinator.data, self._data_path)
        if raw_value is None:
            return None
        if self._value_fn:
            try:
                return self._value_fn(raw_value)
            except Exception as e:
                _LOGGER.error(
                    "BinarySensor %s: Error processing value '%s' with value_fn: %s",
                    self.entity_description.key,
                    raw_value,
                    e,
                )
                return None
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, int):
            return bool(raw_value)
        return None

    @property
    def available(self) -> bool:
        coordinator_available = super().available
        is_on_state = self.is_on
        return coordinator_available and (is_on_state is not None)

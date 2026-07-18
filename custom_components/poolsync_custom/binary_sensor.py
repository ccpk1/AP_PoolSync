"""Binary sensor platform for the PoolSync Custom integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import (
    build_unique_id,
    ensure_parsed_data,
    get_binary_sensor_value,
    get_equipment_runtime,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator-based updates

type BinarySensorDescription = tuple[
    BinarySensorEntityDescription,
    Callable[[Any], bool | None] | None,
]

BINARY_SENSOR_DESCRIPTIONS_POOLSYNC: tuple[
    BinarySensorDescription,
    ...,
] = (
    (
        BinarySensorEntityDescription(
            key="poolsync_online",
            translation_key="online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="service_mode_active",
            translation_key="service_mode",
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, int) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="system_fault",
            translation_key="fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, int) else None,
    ),
)
BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC: tuple[
    BinarySensorDescription,
    ...,
] = (
    (
        BinarySensorEntityDescription(
            key="chlorsync_online",
            translation_key="node_connected",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="chlorsync_fault",
            translation_key="fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        lambda v: isinstance(v, list) and any(fault_code != 0 for fault_code in v),
    ),
)
BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC: tuple[
    BinarySensorDescription,
    ...,
] = (
    (
        BinarySensorEntityDescription(
            key="chem_sync_online",
            translation_key="node_connected",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="chem_sync_fault",
            translation_key="fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        lambda v: isinstance(v, list) and any(fault_code != 0 for fault_code in v),
    ),
    (
        BinarySensorEntityDescription(
            key="chem_sync_flow",
            translation_key="flow",
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
)
BINARY_SENSOR_DESCRIPTIONS_HEATPUMP: tuple[
    BinarySensorDescription,
    ...,
] = (
    (
        BinarySensorEntityDescription(
            key="heatpump_online",
            translation_key="node_connected",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_fault",
            translation_key="fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        lambda v: isinstance(v, list) and any(fault_code != 0 for fault_code in v),
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_flow",
            translation_key="flow",
            entity_registry_enabled_default=True,
        ),
        None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_compressor",
            translation_key="compressor",
            entity_registry_enabled_default=True,
        ),
        None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_fan",
            translation_key="fan",
            entity_registry_enabled_default=True,
        ),
        None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_ext_ctrl",
            translation_key="remote_control",
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, int) else None,
    ),
)


BINARY_SENSOR_DESCRIPTIONS_EQUIPMENT: tuple[
    BinarySensorDescription,
    ...,
] = (
    (
        BinarySensorEntityDescription(
            key="heatpump_in_group",
            translation_key="enabled_by_group",
            entity_registry_enabled_default=True,
        ),
        None,
    ),
    (
        BinarySensorEntityDescription(
            key="pump_priming",
            translation_key="priming",
            entity_registry_enabled_default=True,
        ),
        None,
    ),
)


def get_valid_entity_keys() -> dict[str, set[str]]:
    """Return the set of valid entity keys for each role, for orphan cleanup."""
    return {
        "controller": {d[0].key for d in BINARY_SENSOR_DESCRIPTIONS_POOLSYNC},
        "chlorinator": {d[0].key for d in BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC},
        "chem_sync": {d[0].key for d in BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC},
        "heat_pump": {d[0].key for d in BINARY_SENSOR_DESCRIPTIONS_HEATPUMP},
        "equipment": {d[0].key for d in BINARY_SENSOR_DESCRIPTIONS_EQUIPMENT},
    }


def _build_binary_sensors(
    coordinator: PoolSyncDataUpdateCoordinator,
    descriptions: tuple[BinarySensorDescription, ...],
    role: str,
    device_index: int = 0,
    device_node_addr: int | None = None,
) -> list[PoolSyncBinarySensor]:
    """Build binary sensors for a specific device instance."""
    sensors: list[PoolSyncBinarySensor] = []

    for description, value_fn in descriptions:
        sensors.append(
            PoolSyncBinarySensor(
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
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync binary sensors from a config entry."""
    del hass
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    binary_sensors_to_add: list[PoolSyncBinarySensor] = []
    parsed_data = ensure_parsed_data(coordinator, refresh=True)
    data = coordinator.data or {}
    devices = data.get("devices") if isinstance(data.get("devices"), dict) else None

    if not isinstance(data.get("poolSync"), dict) or devices is None:
        _LOGGER.warning(
            "Coordinator %s: Initial data missing 'poolSync' or 'devices' keys."
            " Binary sensor setup may be incomplete.",
            coordinator.name,
        )

    binary_sensors_to_add.extend(
        _build_binary_sensors(
            coordinator, BINARY_SENSOR_DESCRIPTIONS_POOLSYNC, "controller"
        )
    )

    for index, device in enumerate(parsed_data.devices.get("chlorinator", [])):
        if device.is_present:
            binary_sensors_to_add.extend(
                _build_binary_sensors(
                    coordinator,
                    BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC,
                    "chlorinator",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        elif devices is not None:
            _LOGGER.warning(
                "Coordinator %s data is missing chlorinator device %s."
                " Skipping chlorinator binary sensors.",
                coordinator.name,
                device.device_id,
            )

    for index, device in enumerate(parsed_data.devices.get("heat_pump", [])):
        if device.is_present:
            binary_sensors_to_add.extend(
                _build_binary_sensors(
                    coordinator,
                    BINARY_SENSOR_DESCRIPTIONS_HEATPUMP,
                    "heat_pump",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        elif devices is not None:
            _LOGGER.warning(
                "Coordinator %s data is missing heat pump device %s."
                " Skipping heat pump binary sensors.",
                coordinator.name,
                device.device_id,
            )

    for index, device in enumerate(parsed_data.devices.get("chem_sync", [])):
        if device.is_present:
            binary_sensors_to_add.extend(
                _build_binary_sensors(
                    coordinator,
                    BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC,
                    "chem_sync",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        elif devices is not None:
            _LOGGER.warning(
                "Coordinator %s data is missing chem_sync device %s."
                " Skipping chem_sync binary sensors.",
                coordinator.name,
                device.device_id,
            )

    if binary_sensors_to_add:
        async_add_entities(binary_sensors_to_add)
        _LOGGER.info(
            "Added %d PoolSync binary sensors for %s",
            len(binary_sensors_to_add),
            coordinator.name,
        )

    # Equipment binary sensors
    if equip_runtime := get_equipment_runtime(parsed_data):
        equip_binary: list[PoolSyncBinarySensor] = []
        for equip in equip_runtime.equipment.values():
            device_info = coordinator.get_equipment_device_info(equip)
            prefix = f"{coordinator.mac_address}_equip_{equip.slot_key}_"
            for desc, vfn in BINARY_SENSOR_DESCRIPTIONS_EQUIPMENT:
                if desc.key == "pump_priming" and not equip.is_pump:
                    continue
                if desc.key == "heatpump_in_group" and not equip.is_heat_pump:
                    continue
                equip_binary.append(
                    PoolSyncBinarySensor(
                        coordinator,
                        "equipment",
                        desc,
                        vfn,
                        _device_info=device_info,
                        _unique_id=f"{prefix}{desc.key}",
                    )
                )
        if equip_binary:
            async_add_entities(equip_binary)


class PoolSyncBinarySensor(
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], BinarySensorEntity
):
    """Representation of a PoolSync binary sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        role: str,
        description: BinarySensorEntityDescription,
        value_fn: Callable[[Any], bool | None] | None = None,
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
            raw_value = get_binary_sensor_value(
                parsed_data,
                self.entity_description.key,
                role_key=self._role_key,
                index=self._device_index,
            )
        else:
            raw_value = get_binary_sensor_value(
                parsed_data, self.entity_description.key
            )
        if raw_value is None:
            self._attr_is_on = None
            return

        if self._value_fn:
            try:
                self._attr_is_on = self._value_fn(raw_value)
            except (AttributeError, TypeError, ValueError) as err:
                _LOGGER.error(
                    "BinarySensor %s: Error processing value '%s' with value_fn: %s",
                    self.entity_description.key,
                    raw_value,
                    err,
                )
                self._attr_is_on = None
                return
        elif isinstance(raw_value, bool):
            self._attr_is_on = raw_value
        elif isinstance(raw_value, int):
            self._attr_is_on = bool(raw_value)
        else:
            self._attr_is_on = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        ensure_parsed_data(self.coordinator, refresh=True)
        self._update_attrs()
        super()._handle_coordinator_update()

    @property  # pyright: ignore[reportIncompatibleVariableOverride]
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.is_on is not None

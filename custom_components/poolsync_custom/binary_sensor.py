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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import (
    ensure_parsed_data,
    get_binary_sensor_value,
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
            name="PoolSync Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="service_mode_active",
            name="Service Mode",
            icon="mdi:account-wrench",
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, int) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="system_fault",
            name="System Fault",
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
            name="ChlorSync Module Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="chlorsync_fault",
            name="ChlorSync Module Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        lambda v: isinstance(v, list) and any(fault_code != 0 for fault_code in v),
    ),
)
BINARY_SENSOR_DESCRIPTIONS_HEATPUMP: tuple[
    BinarySensorDescription,
    ...,
] = (
    (
        BinarySensorEntityDescription(
            key="heatpump_online",
            name="Heat Pump Module Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_fault",
            name="Heat Pump Module Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_registry_enabled_default=True,
        ),
        lambda v: isinstance(v, list) and any(fault_code != 0 for fault_code in v),
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_flow",
            name="Heat Pump Flow",
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v >= 1) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_compressor",
            name="Heat Pump Compressor",
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v == 8) if isinstance(v, (bool, int)) else None,
    ),
    (
        BinarySensorEntityDescription(
            key="heatpump_fan",
            name="Heat Pump Fan",
            entity_registry_enabled_default=True,
        ),
        lambda v: bool(v == 8 or v == 520) if isinstance(v, (bool, int)) else None,
    ),
)


def _build_binary_sensors(
    coordinator: PoolSyncDataUpdateCoordinator,
    descriptions: tuple[BinarySensorDescription, ...],
) -> list[PoolSyncBinarySensor]:
    """Build binary sensors."""
    sensors: list[PoolSyncBinarySensor] = []

    for description, value_fn in descriptions:
        sensors.append(PoolSyncBinarySensor(coordinator, description, value_fn))

    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    del hass
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    binary_sensors_to_add: list[PoolSyncBinarySensor] = []
    parsed_data = ensure_parsed_data(coordinator, refresh=True)
    data = coordinator.data or {}
    devices = data.get("devices") if isinstance(data.get("devices"), dict) else None

    if not isinstance(data.get("poolSync"), dict) or devices is None:
        _LOGGER.warning(
            "Coordinator %s: Initial data is missing 'poolSync' or 'devices' top-level keys. Binary sensor setup may be incomplete.",
            coordinator.name,
        )

    heatpump_id = parsed_data.heat_pump.device_id
    chlor_id = parsed_data.chlorinator.device_id

    binary_sensors_to_add.extend(
        _build_binary_sensors(coordinator, BINARY_SENSOR_DESCRIPTIONS_POOLSYNC)
    )

    if chlor_id and parsed_data.chlorinator.is_present:
        binary_sensors_to_add.extend(
            _build_binary_sensors(coordinator, BINARY_SENSOR_DESCRIPTIONS_CHLORSYNC)
        )
    elif chlor_id and devices is not None:
        _LOGGER.warning(
            "Coordinator %s data is missing chlorinator device %s. Skipping chlorinator binary sensors.",
            coordinator.name,
            chlor_id,
        )

    if heatpump_id and parsed_data.heat_pump.is_present:
        binary_sensors_to_add.extend(
            _build_binary_sensors(coordinator, BINARY_SENSOR_DESCRIPTIONS_HEATPUMP)
        )
    elif heatpump_id and devices is not None:
        _LOGGER.warning(
            "Coordinator %s data is missing heat pump device %s. Skipping heat pump binary sensors.",
            coordinator.name,
            heatpump_id,
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
        value_fn: Callable[[Any], bool | None] | None = None,
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
        raw_value = get_binary_sensor_value(
            ensure_parsed_data(self.coordinator), self.entity_description.key
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

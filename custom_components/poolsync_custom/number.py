"""Number platform for the PoolSync Custom integration."""

# pyright: reportAbstractUsage=false

# pylint: disable=abstract-method

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, cast

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import (
    build_unique_id,
    ensure_parsed_data,
    get_equipment_runtime,
    get_number_value,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator-based updates

_WRITE_METHODS: dict[str, str] = {
    "chlor_output_control": "async_set_chlorinator_output",
    "temperature_output_control": "async_set_heat_pump_active_target",
    "chem_ph_setpoint": "async_set_chem_config",
    "chem_orp_setpoint": "async_set_chem_config",
    "chem_feed_rate": "async_set_chem_config",
    "chem_max_daily_feed": "async_set_chem_config",
}

type NumberDescription = tuple[NumberEntityDescription, Callable[[Any], Any] | None]

NUMBER_DESCRIPTIONS_CHLOR: tuple[NumberDescription, ...] = (
    (
        NumberEntityDescription(
            key="chlor_output_control",  # NUMBER_KEY_CHLOR_OUTPUT, # "chlor_output_control"
            translation_key="output",
            native_unit_of_measurement=PERCENTAGE,
            native_min_value=0,  # DEFAULT_CHLOR_OUTPUT_MIN, # e.g., 0
            native_max_value=100,  # DEFAULT_CHLOR_OUTPUT_MAX, # e.g., 100
            native_step=1,  # DEFAULT_CHLOR_OUTPUT_STEP,     # e.g., 1 or 5
            mode=NumberMode.SLIDER,  # Or NumberMode.BOX
        ),
        None,
    ),
)

NUMBER_DESCRIPTIONS_CHEMSYNC: tuple[NumberDescription, ...] = (
    (
        NumberEntityDescription(
            key="chem_ph_setpoint",
            translation_key="ph_setpoint",
            entity_category=EntityCategory.CONFIG,
            native_min_value=60,
            native_max_value=90,
            native_step=1,
            mode=NumberMode.BOX,
        ),
        None,
    ),
    (
        NumberEntityDescription(
            key="chem_orp_setpoint",
            translation_key="orp_setpoint",
            entity_category=EntityCategory.CONFIG,
            native_min_value=0,
            native_max_value=900,
            native_step=1,
            mode=NumberMode.BOX,
        ),
        None,
    ),
    (
        NumberEntityDescription(
            key="chem_feed_rate",
            translation_key="feed_rate",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement=PERCENTAGE,
            native_min_value=0,
            native_max_value=100,
            native_step=1,
            mode=NumberMode.SLIDER,
        ),
        None,
    ),
    (
        NumberEntityDescription(
            key="chem_max_daily_feed",
            translation_key="max_daily_feed",
            entity_category=EntityCategory.CONFIG,
            native_min_value=0,
            native_max_value=100,
            native_step=1,
            mode=NumberMode.SLIDER,
        ),
        None,
    ),
)

NUMBER_DESCRIPTIONS_EQUIPMENT: tuple[NumberDescription, ...] = (
    (
        NumberEntityDescription(
            key="pump_rpm_control",
            translation_key="pump_rpm_control",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement="RPM",
            native_min_value=0,
            native_max_value=3450,
            native_step=50,
            mode=NumberMode.BOX,
        ),
        None,
    ),
)

NUMBER_DESCRIPTIONS_HEATPUMP_F: tuple[NumberDescription, ...] = (
    (
        NumberEntityDescription(
            key="temperature_output_control",  # NUMBER_KEY_CHLOR_OUTPUT, # "chlor_output_control"
            translation_key="active_target_temperature",
            entity_category=EntityCategory.CONFIG,
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            native_min_value=40,  # e.g., 0
            native_max_value=104,  # e.g., 100
            native_step=1,  # e.g., 1 or 5
            mode=NumberMode.BOX,  # Or NumberMode.BOX
        ),
        None,
    ),
)


def _build_number_entities(
    coordinator: PoolSyncDataUpdateCoordinator,
    descriptions: Sequence[NumberDescription],
    role: str,
    device_index: int = 0,
    device_node_addr: int | None = None,
) -> list[PoolSyncChlorOutputNumberEntity]:
    """Build number entities for a specific PoolSync device instance."""
    number_entities: list[PoolSyncChlorOutputNumberEntity] = []

    parsed_data = ensure_parsed_data(coordinator)

    for description, value_fn in descriptions:
        current_value = get_number_value(parsed_data, description.key)
        if current_value is None:
            _LOGGER.debug(
                "Coordinator %s: Value for number entity %s is None."
                " Entity will show unavailable until data arrives.",
                coordinator.name,
                description.key,
            )
        else:
            _LOGGER.debug(
                "Coordinator %s: Initial value for number entity %s is %s.",
                coordinator.name,
                description.key,
                current_value,
            )

        number_entities.append(
            PoolSyncChlorOutputNumberEntity(
                coordinator,
                role,
                description,
                value_fn,
                _device_index=device_index,
                _device_node_addr=device_node_addr,
            )
        )

    return number_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync number entities based on a config entry."""
    del hass
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    _LOGGER.debug("Starting number platform setup for %s.", coordinator.name)

    number_entities: list[PoolSyncChlorOutputNumberEntity] = []

    if not coordinator.data:
        _LOGGER.debug(
            "Coordinator %s has no data. Cannot set up number entities.",
            coordinator.name,
        )
        return

    if not isinstance(coordinator.data.get("devices"), dict):
        _LOGGER.debug(
            "Coordinator %s data is missing 'devices' dictionary."
            " Cannot set up number entities.",
            coordinator.name,
        )
        return

    parsed_data = ensure_parsed_data(coordinator)

    for index, device in enumerate(parsed_data.devices.get("chlorinator", [])):
        if device.is_present:
            number_entities.extend(
                _build_number_entities(
                    coordinator,
                    NUMBER_DESCRIPTIONS_CHLOR,
                    "chlorinator",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        else:
            _LOGGER.debug(
                "Coordinator %s data is missing chlorinator device %s."
                " Skipping chlorinator number entities.",
                coordinator.name,
                device.device_id,
            )

    for index, device in enumerate(parsed_data.devices.get("chem_sync", [])):
        if device.is_present:
            number_entities.extend(
                _build_number_entities(
                    coordinator,
                    NUMBER_DESCRIPTIONS_CHEMSYNC,
                    "chem_sync",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )

    # Equipment number entities (pump RPM control)
    if equip_runtime := get_equipment_runtime(parsed_data):
        for equip in equip_runtime.equipment.values():
            if not equip.is_pump:
                continue
            device_info = coordinator.get_equipment_device_info(equip)
            prefix = f"{coordinator.mac_address}_equip_{equip.slot_key}_"
            for desc, vfn in NUMBER_DESCRIPTIONS_EQUIPMENT:
                number_entities.append(
                    PoolSyncChlorOutputNumberEntity(
                        coordinator,
                        "equipment",
                        desc,
                        vfn,
                        _device_info=device_info,
                        _unique_id=f"{prefix}{desc.key}",
                    )
                )

    for index, device in enumerate(parsed_data.devices.get("heat_pump", [])):
        if device.is_present:
            number_entities.extend(
                _build_number_entities(
                    coordinator,
                    NUMBER_DESCRIPTIONS_HEATPUMP_F,
                    "heat_pump",
                    device_index=index,
                    device_node_addr=device.node_addr,
                )
            )
        else:
            _LOGGER.debug(
                "Coordinator %s data is missing heat pump device %s."
                " Skipping heat pump number entities.",
                coordinator.name,
                device.device_id,
            )

    if number_entities:
        _LOGGER.debug("Adding %d number entities.", len(number_entities))
        async_add_entities(number_entities)
        _LOGGER.info(
            "Added %d PoolSync number entities for %s",
            len(number_entities),
            coordinator.name,
        )
    else:
        _LOGGER.debug(
            "No number entities were created for %s.",
            coordinator.name,
        )


class PoolSyncChlorOutputNumberEntity(  # type: ignore[abstract]
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], NumberEntity
):
    """Representation of a PoolSync Chlorinator Output Number entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        role: str,
        description: NumberEntityDescription,
        value_fn: Callable[[Any], Any] | None = None,
        *,
        _device_index: int = 0,
        _device_node_addr: int | None = None,
        _device_info: DeviceInfo | None = None,
        _unique_id: str | None = None,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._value_fn = (
            value_fn  # Not used for native_value here, but kept for pattern consistency
        )
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

        _LOGGER.debug(
            "NUMBER_ENTITY %s: Initialized. Unique ID: %s",
            self.entity_description.name,
            self._attr_unique_id,
        )

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
            value = get_number_value(
                parsed_data,
                self.entity_description.key,
                role_key=self._role_key,
                index=self._device_index,
            )
        else:
            value = get_number_value(parsed_data, self.entity_description.key)
        if value is None:
            self._attr_native_value = None
            self._attr_available = False
            return

        try:
            self._attr_native_value = float(value)
        except (ValueError, TypeError):
            _LOGGER.error(
                "NUMBER_ENTITY %s: could not convert value '%s' (type: %s) to float",
                self.entity_description.key,
                value,
                type(value).__name__,
            )
            self._attr_native_value = None
            self._attr_available = False
            return

        self._attr_available = super().available

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attrs()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Return True if the entity has a usable current value."""
        return super().available and self.native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        new_value = int(value)

        _LOGGER.info(
            "NUMBER_ENTITY %s: Attempting to set native_value to %d (from HA UI float value: %f, device_index: %d)",
            self.entity_description.key,
            new_value,
            value,
            self._device_index,
        )

        if not self.coordinator.password:
            _LOGGER.error(
                "NUMBER_ENTITY %s: Password not available on coordinator. Cannot set value.",
                self.entity_description.key,
            )
            raise HomeAssistantError("API password not available to set value.")

        try:
            if (method_name := _WRITE_METHODS.get(self.entity_description.key)) is None:
                raise HomeAssistantError(
                    f"Unsupported number command: {self.entity_description.key}"
                )

            method = getattr(self.coordinator, method_name)
            if method_name == "async_set_chem_config":
                if self._device_index > 0:
                    await method(
                        self.entity_description.key,
                        new_value,
                        index=self._device_index,
                    )
                else:
                    await method(self.entity_description.key, new_value)
            elif self._device_index > 0:
                await method(new_value, index=self._device_index)
            else:
                await method(new_value)

            _LOGGER.info(
                "NUMBER_ENTITY %s: Successfully set value to %d and requested refresh.",
                self.entity_description.key,
                new_value,
            )

        except HomeAssistantError:
            raise
        except Exception as e:
            _LOGGER.error(
                "NUMBER_ENTITY %s: Failed to set new value %d: %s",
                self.entity_description.key,
                new_value,
                e,
            )
            raise HomeAssistantError(
                f"Failed to set {self.entity_description.name} to {new_value}: {e}"
            ) from e

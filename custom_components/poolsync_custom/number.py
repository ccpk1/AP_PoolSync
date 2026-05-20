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
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError  # For service call errors
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.unit_system import METRIC_SYSTEM

from .const import (
    CHLORINATOR_ID,
    HEATPUMP_ID,
    # DEFAULT_CHLOR_OUTPUT_MIN,
    # DEFAULT_CHLOR_OUTPUT_MAX,
    # DEFAULT_CHLOR_OUTPUT_STEP,
    # NUMBER_KEY_CHLOR_OUTPUT,
)
from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import ensure_parsed_data, get_number_value

_LOGGER = logging.getLogger(__name__)

type NumberDescription = tuple[
    NumberEntityDescription, list[str | int], Callable[[Any], Any] | None
]

NUMBER_DESCRIPTIONS_CHLOR: tuple[NumberDescription, ...] = (
    (
        NumberEntityDescription(
            key="chlor_output_control",  # NUMBER_KEY_CHLOR_OUTPUT, # "chlor_output_control"
            name="Chlorinator Output",  # This will be the entity name
            icon="mdi:knob",  # Using a knob icon for control
            native_unit_of_measurement=PERCENTAGE,
            native_min_value=0,  # DEFAULT_CHLOR_OUTPUT_MIN, # e.g., 0
            native_max_value=100,  # DEFAULT_CHLOR_OUTPUT_MAX, # e.g., 100
            native_step=1,  # DEFAULT_CHLOR_OUTPUT_STEP,     # e.g., 1 or 5
            mode=NumberMode.SLIDER,  # Or NumberMode.BOX
        ),
        ["devices", CHLORINATOR_ID, "config", "chlorOutput"],
        None,
    ),  # Path to get current value
)

NUMBER_DESCRIPTIONS_HEATPUMP_F: tuple[NumberDescription, ...] = (
    (
        NumberEntityDescription(
            key="temperature_output_control",  # NUMBER_KEY_CHLOR_OUTPUT, # "chlor_output_control"
            name="Temperature Output",  # This will be the entity name
            icon="mdi:knob",  # Using a knob icon for control
            native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
            native_min_value=40,  # e.g., 0
            native_max_value=104,  # e.g., 100
            native_step=1,  # e.g., 1 or 5
            mode=NumberMode.BOX,  # Or NumberMode.BOX
        ),
        ["devices", HEATPUMP_ID, "config", "setpoint"],
        None,
    ),  # Path to get current value
    (
        NumberEntityDescription(
            key="heat_mode",  # NUMBER_KEY_CHLOR_OUTPUT, # "chlor_output_control"
            name="heat_mode",  # This will be the entity name
            icon="mdi:knob",  # Using a knob icon for control
            native_min_value=0,  # e.g., 0
            native_max_value=2,  # e.g., 100
            native_step=1,  # e.g., 1 or 5
            mode=NumberMode.BOX,  # Or NumberMode.BOX
        ),
        ["devices", HEATPUMP_ID, "config", "mode"],
        None,
    ),  # Path to get current value
)

NUMBER_DESCRIPTIONS_HEATPUMP_C: tuple[NumberDescription, ...] = (
    (
        NumberEntityDescription(
            key="temperature_output_control",  # NUMBER_KEY_CHLOR_OUTPUT, # "chlor_output_control"
            name="Temperature Output",  # This will be the entity name
            icon="mdi:knob",  # Using a knob icon for control
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            native_min_value=5,  # e.g., 0
            native_max_value=40,  # e.g., 100
            native_step=0.5,  # e.g., 1 or 5
            mode=NumberMode.SLIDER,  # Or NumberMode.BOX
        ),
        ["devices", HEATPUMP_ID, "config", "setpoint"],
        None,
    ),  # Path to get current value
    (
        NumberEntityDescription(
            key="heat_mode",  # NUMBER_KEY_CHLOR_OUTPUT, # "chlor_output_control"
            name="heat_mode",  # This will be the entity name
            icon="mdi:knob",  # Using a knob icon for control
            native_min_value=0,  # e.g., 0
            native_max_value=2,  # e.g., 100
            native_step=1,  # e.g., 1 or 5
            mode=NumberMode.BOX,  # Or NumberMode.BOX
        ),
        ["devices", HEATPUMP_ID, "config", "mode"],
        None,
    ),  # Path to get current value
)


def _build_number_entities(
    coordinator: PoolSyncDataUpdateCoordinator,
    descriptions: Sequence[NumberDescription],
    device_id: str,
) -> list[PoolSyncChlorOutputNumberEntity]:
    """Build number entities for a specific PoolSync device."""
    number_entities: list[PoolSyncChlorOutputNumberEntity] = []

    parsed_data = ensure_parsed_data(coordinator)

    for description, template_path, value_fn in descriptions:
        data_path = template_path.copy()
        data_path[1] = device_id

        current_value = get_number_value(parsed_data, description.key)
        if current_value is None:
            _LOGGER.warning(
                "NUMBER_PLATFORM: Coordinator %s: Value for number entity %s at path %s is None. Entity may be unavailable or show an unexpected state initially.",
                coordinator.name,
                description.key,
                data_path,
            )
        else:
            _LOGGER.debug(
                "NUMBER_PLATFORM: Coordinator %s: Initial value for number entity %s at path %s is %s.",
                coordinator.name,
                description.key,
                data_path,
                current_value,
            )

        number_entities.append(
            PoolSyncChlorOutputNumberEntity(
                coordinator, description, data_path, value_fn
            )
        )

    return number_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync number entities based on a config entry."""
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    _LOGGER.debug(
        "NUMBER_PLATFORM: Starting async_setup_entry for %s.", coordinator.name
    )

    number_entities: list[PoolSyncChlorOutputNumberEntity] = []

    _LOGGER.info(
        "NUMBER_PLATFORM: Starting async_setup_entry for %s.", coordinator.name
    )
    if not coordinator.data:
        _LOGGER.warning(
            "NUMBER_PLATFORM: Coordinator %s has no data. Cannot set up number entities.",
            coordinator.name,
        )
        return

    if not isinstance(coordinator.data.get("devices"), dict):
        _LOGGER.warning(
            "NUMBER_PLATFORM: Coordinator %s data is missing 'devices' dictionary. Cannot set up Chlorinator Output.",
            coordinator.name,
        )
        return

    _LOGGER.debug(
        "NUMBER_PLATFORM: Coordinator data includes a devices dictionary. Proceeding to create number entities."
    )

    parsed_data = ensure_parsed_data(coordinator)
    heatpump_id = parsed_data.heat_pump.device_id
    chlor_id = parsed_data.chlorinator.device_id

    if chlor_id and parsed_data.chlorinator.is_present:
        number_entities.extend(
            _build_number_entities(coordinator, NUMBER_DESCRIPTIONS_CHLOR, chlor_id)
        )
    elif chlor_id:
        _LOGGER.warning(
            "NUMBER_PLATFORM: Coordinator %s data is missing chlorinator device %s. Skipping chlorinator number entities.",
            coordinator.name,
            chlor_id,
        )

    is_metric = hass.config.units is METRIC_SYSTEM
    if heatpump_id and parsed_data.heat_pump.is_present:
        if is_metric:
            number_descriptions_heatpump = NUMBER_DESCRIPTIONS_HEATPUMP_C
        else:
            number_descriptions_heatpump = NUMBER_DESCRIPTIONS_HEATPUMP_F

        number_entities.extend(
            _build_number_entities(
                coordinator, number_descriptions_heatpump, heatpump_id
            )
        )
    elif heatpump_id:
        _LOGGER.warning(
            "NUMBER_PLATFORM: Coordinator %s data is missing heat pump device %s. Skipping heat pump number entities.",
            coordinator.name,
            heatpump_id,
        )

    if number_entities:
        _LOGGER.debug(
            "NUMBER_PLATFORM: Adding %d number entities.", len(number_entities)
        )
        async_add_entities(number_entities)
        _LOGGER.info(
            "NUMBER_PLATFORM: Added %d PoolSync number entities for %s",
            len(number_entities),
            coordinator.name,
        )
    else:
        _LOGGER.warning(
            "NUMBER_PLATFORM: No number entities were created for %s. Check descriptions and data paths.",
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
        description: NumberEntityDescription,
        data_path: list[str | int],
        value_fn: Callable[[Any], Any] | None = None,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._data_path = data_path
        self._value_fn = (
            value_fn  # Not used for native_value here, but kept for pattern consistency
        )

        self._attr_unique_id = f"{coordinator.mac_address}_{description.key}"
        self._attr_device_info = coordinator.device_info
        self._update_attrs()

        _LOGGER.debug(
            "NUMBER_ENTITY %s: Initialized. Unique ID: %s, Data Path: %s",
            self.entity_description.name,
            self._attr_unique_id,
            self._data_path,
        )

    @callback
    def _update_attrs(self) -> None:
        """Update cached entity attributes from coordinator data."""
        value = get_number_value(
            ensure_parsed_data(self.coordinator), self.entity_description.key
        )
        if value is None:
            self._attr_native_value = None
            self._attr_available = False
            return

        try:
            self._attr_native_value = float(value)
        except (ValueError, TypeError):
            _LOGGER.error(
                "NUMBER_ENTITY %s: could not convert value '%s' (type: %s) to float from path %s",
                self.entity_description.key,
                value,
                type(value).__name__,
                self._data_path,
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

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        new_value = int(value)

        _LOGGER.info(
            "NUMBER_ENTITY %s: Attempting to set native_value to %d (from HA UI float value: %f)",
            self.entity_description.key,
            new_value,
            value,
        )

        if not self.coordinator.password:
            _LOGGER.error(
                "NUMBER_ENTITY %s: Password not available on coordinator. Cannot set value.",
                self.entity_description.key,
            )
            raise HomeAssistantError("API password not available to set value.")

        try:
            if self.entity_description.key == "chlor_output_control":
                await self.coordinator.async_set_chlorinator_output(new_value)
            elif self.entity_description.key == "temperature_output_control":
                await self.coordinator.async_set_heat_pump_setpoint(new_value)
            elif self.entity_description.key == "heat_mode":
                await self.coordinator.async_set_heat_pump_mode(new_value)
            else:
                raise HomeAssistantError(
                    f"Unsupported number command: {self.entity_description.key}"
                )

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

"""Number platform for the PoolSync Custom integration."""

import logging
from typing import Any, Callable, Dict, List, Optional, Union, cast

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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.exceptions import HomeAssistantError  # For service call errors
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
from .sensor import _get_value_from_path  # Reuse helper from sensor.py

_LOGGER = logging.getLogger(__name__)

NUMBER_DESCRIPTIONS_CHLOR: tuple[
    NumberEntityDescription, List[str], Optional[Callable[[Any], Any]]
] = (
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

NUMBER_DESCRIPTIONS_HEATPUMP_F: tuple[
    NumberEntityDescription, List[str], Optional[Callable[[Any], Any]]
] = (
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

NUMBER_DESCRIPTIONS_HEATPUMP_C: tuple[
    NumberEntityDescription, List[str], Optional[Callable[[Any], Any]]
] = (
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

    if not isinstance(coordinator.data["devices"].get("0"), dict):
        _LOGGER.warning(
            "NUMBER_PLATFORM: Coordinator %s data 'devices' dictionary is missing '0' key or it's not a dict. "
            "Chlorinator Output number entity cannot be set up. devices content: %s",
            coordinator.name,
            coordinator.data["devices"],
        )
        return

    _LOGGER.debug(
        "NUMBER_PLATFORM: Coordinator data seems valid for device '0'. Proceeding to create number entities."
    )

    heatpump_id = HEATPUMP_ID
    chlor_id = CHLORINATOR_ID
    if coordinator.data and isinstance(coordinator.data.get("deviceType"), dict):
        deviceTypes = coordinator.data.get("deviceType")
        temp = [key for key, value in deviceTypes.items() if value == "heatPump"]
        heatpump_id = temp[0] if temp else "-1"
        temp = [key for key, value in deviceTypes.items() if value == "chlorSync"]
        chlor_id = temp[0] if temp else "-1"

    if chlor_id != "-1":
        for description, data_path, value_fn in NUMBER_DESCRIPTIONS_CHLOR:
            _LOGGER.debug(
                "NUMBER_PLATFORM: Processing number entity description for key: %s",
                description.key,
            )
            data_path[1] = chlor_id
            current_value = _get_value_from_path(coordinator.data, data_path)
            if current_value is None:
                _LOGGER.warning(
                    "NUMBER_PLATFORM: Coordinator %s: Value for number entity %s at path %s is None. "
                    "Entity may be unavailable or show an unexpected state initially.",
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

            try:
                entity_instance = PoolSyncChlorOutputNumberEntity(
                    coordinator, description, data_path, value_fn
                )
                number_entities.append(entity_instance)
                _LOGGER.debug(
                    "NUMBER_PLATFORM: Successfully created instance for %s.",
                    description.key,
                )
            except Exception as e:
                _LOGGER.exception(
                    "NUMBER_PLATFORM: Error creating instance for %s: %s",
                    description.key,
                    e,
                )

    is_metric = hass.config.units is METRIC_SYSTEM
    if heatpump_id != "-1":
        if is_metric:
            number_descriptions_heatpump = NUMBER_DESCRIPTIONS_HEATPUMP_C
        else:
            number_descriptions_heatpump = NUMBER_DESCRIPTIONS_HEATPUMP_F

        for description, data_path, value_fn in number_descriptions_heatpump:
            _LOGGER.debug(
                "NUMBER_PLATFORM: Processing number entity description for key: %s",
                description.key,
            )
            data_path[1] = heatpump_id
            current_value = _get_value_from_path(coordinator.data, data_path)
            if current_value is None:
                _LOGGER.warning(
                    "NUMBER_PLATFORM: Coordinator %s: Value for number entity %s at path %s is None. "
                    "Entity may be unavailable or show an unexpected state initially.",
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

            try:
                entity_instance = PoolSyncChlorOutputNumberEntity(
                    coordinator, description, data_path, value_fn
                )
                number_entities.append(entity_instance)
                _LOGGER.debug(
                    "NUMBER_PLATFORM: Successfully created instance for %s.",
                    description.key,
                )
            except Exception as e:
                _LOGGER.exception(
                    "NUMBER_PLATFORM: Error creating instance for %s: %s",
                    description.key,
                    e,
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


class PoolSyncChlorOutputNumberEntity(
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], NumberEntity
):
    """Representation of a PoolSync Chlorinator Output Number entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: NumberEntityDescription,
        data_path: List[str],
        value_fn: Optional[Callable[[Any], Any]] = None,
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

        _LOGGER.debug(
            "NUMBER_ENTITY %s: Initialized. Unique ID: %s, Data Path: %s",
            self.entity_description.name,
            self._attr_unique_id,
            self._data_path,
        )

    @property
    def native_value(self) -> Optional[float]:
        """Return the current value of the number entity."""
        value = _get_value_from_path(self.coordinator.data, self._data_path)
        # _LOGGER.debug("NUMBER_ENTITY %s: native_value raw from path %s: %s", self.entity_description.key, self._data_path, value)
        if value is None:
            return None
        try:
            num_value = float(value)
            return num_value
        except (ValueError, TypeError):
            _LOGGER.error(
                "NUMBER_ENTITY %s: could not convert value '%s' (type: %s) to float from path %s",
                self.entity_description.key,
                value,
                type(value).__name__,
                self._data_path,
            )
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        new_value = int(value)  # API expects an integer for percentage
        datapath = self._data_path
        _LOGGER.info(str(datapath))

        deviceId = datapath[1]
        keyId = datapath[3]

        _LOGGER.info(
            "NUMBER_ENTITY %s: Attempting to set native_value to %d (from HA UI float value: %f)",
            self.entity_description.key,
            new_value,
            value,
        )

        if not hasattr(self.coordinator, "_password") or not self.coordinator._password:
            _LOGGER.error(
                "NUMBER_ENTITY %s: Password not available on coordinator. Cannot set value.",
                self.entity_description.key,
            )
            raise HomeAssistantError("API password not available to set value.")

        current_api_password = self.coordinator._password
        _LOGGER.debug(
            "NUMBER_ENTITY %s: Using password from coordinator to set value.",
            self.entity_description.key,
        )

        try:
            _LOGGER.debug(
                "NUMBER_ENTITY %s: Calling api_client._request_patch with value %d",
                self.entity_description.key,
                new_value,
            )

            api_response = await self.coordinator.api_client._request_patch(
                deviceId=deviceId,
                keyId=keyId,
                value=new_value,
                password=current_api_password,
            )
            _LOGGER.info(
                "NUMBER_ENTITY %s: API call to set chlor_output to %d completed. Response: %s",
                self.entity_description.key,
                new_value,
                api_response,
            )

            _LOGGER.debug(
                "NUMBER_ENTITY %s: Requesting coordinator refresh after setting value.",
                self.entity_description.key,
            )
            await self.coordinator.async_request_refresh()
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
                f"Failed to set chlorine output to {new_value}%: {e}"
            ) from e

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        coordinator_available = super().available
        # Check if the specific data path for the current value exists
        value_exists = (
            _get_value_from_path(self.coordinator.data, self._data_path) is not None
        )
        is_available = coordinator_available and value_exists
        # _LOGGER.debug(
        #     "NUMBER_ENTITY %s: Availability check: coordinator_available=%s, value_exists_at_path=%s, final_available=%s",
        #     self.entity_description.key, coordinator_available, value_exists, is_available
        # )
        return is_available

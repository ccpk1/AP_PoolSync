"""Select platform for the PoolSync Custom integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import ensure_parsed_data, get_heat_pump_mode_options, get_select_value

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync select entities based on a config entry."""
    del hass
    coordinator = entry.runtime_data
    parsed_data = ensure_parsed_data(coordinator)

    if not parsed_data.heat_pump.is_present:
        return

    options = get_heat_pump_mode_options(parsed_data)
    if not options:
        return

    async_add_entities(
        [
            PoolSyncHeatModeSelect(
                coordinator,
                SelectEntityDescription(
                    key="heat_mode",
                    options=options,
                    translation_key="mode",
                ),
            )
        ]
    )


class PoolSyncHeatModeSelect(  # pyright: ignore[reportIncompatibleVariableOverride]
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], SelectEntity
):
    """Representation of a PoolSync heat-mode select."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: SelectEntityDescription,
    ) -> None:
        """Initialize the heat-mode select."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.mac_address}_{description.key}"
        self._attr_device_info = coordinator.get_device_info("heat_pump")
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        """Update cached entity attributes from coordinator data."""
        parsed_data = ensure_parsed_data(self.coordinator)
        self._attr_options = get_heat_pump_mode_options(parsed_data)
        self._attr_current_option = get_select_value(
            parsed_data, self.entity_description.key
        )
        self._attr_available = (
            super().available
            and self._attr_current_option is not None
            and self._attr_current_option in self._attr_options
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        ensure_parsed_data(self.coordinator, refresh=True)
        self._update_attrs()
        super()._handle_coordinator_update()

    def select_option(self, option: str) -> None:
        """Select a new heat mode from a synchronous context."""
        if self.hass is None:
            raise HomeAssistantError("Entity is not added to Home Assistant")

        self.hass.add_job(self.async_select_option, option)

    async def async_select_option(self, option: str) -> None:
        """Select a new heat mode."""
        if option not in self.options:
            raise HomeAssistantError(f"Unsupported heat pump mode: {option}")

        self._attr_current_option = option
        if self.hass is not None:
            self.async_write_ha_state()
        await self.coordinator.async_set_heat_pump_mode_context(option)

"""Select platform for the PoolSync Custom integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import (
    build_unique_id,
    ensure_parsed_data,
    get_chem_sync_mode_options,
    get_heat_pump_mode_options,
    get_select_value,
)

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

    entities: list[PoolSyncHeatModeSelect] = []

    # ChemSync system mode select
    chem_sys_mode_options = get_chem_sync_mode_options()
    for index, device in enumerate(parsed_data.devices.get("chem_sync", [])):
        if not device.is_present:
            continue
        entities.append(
            PoolSyncHeatModeSelect(
                coordinator,
                SelectEntityDescription(
                    key="chem_sys_mode",
                    options=chem_sys_mode_options,
                    translation_key="chem_sys_mode",
                    entity_category=EntityCategory.CONFIG,
                ),
                role="chem_sync",
                device_index=index,
                device_node_addr=device.node_addr,
            )
        )

    # Heat pump mode select
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices:
        if entities:
            async_add_entities(entities)
        return

    options = get_heat_pump_mode_options(parsed_data)
    if not options:
        if entities:
            async_add_entities(entities)
        return

    for index, device in enumerate(hp_devices):
        if not device.is_present:
            continue
        entities.append(
            PoolSyncHeatModeSelect(
                coordinator,
                SelectEntityDescription(
                    key="heat_mode",
                    options=options,
                    translation_key="mode",
                    entity_category=EntityCategory.CONFIG,
                ),
                device_index=index,
                device_node_addr=device.node_addr,
            )
        )

    if entities:
        async_add_entities(entities)


class PoolSyncHeatModeSelect(  # pyright: ignore[reportIncompatibleVariableOverride]
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], SelectEntity
):
    """Representation of a PoolSync heat-mode select."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: SelectEntityDescription,
        *,
        role: str = "heat_pump",
        device_index: int = 0,
        device_node_addr: int | None = None,
    ) -> None:
        """Initialize the heat-mode select."""
        super().__init__(coordinator)
        self.entity_description = description
        self._role_key = role
        self._device_index = device_index
        self._device_node_addr = device_node_addr
        self._attr_unique_id = self._build_unique_id(
            coordinator.mac_address, description.key
        )
        self._attr_device_info = coordinator.get_device_info(role, index=device_index)
        self._update_attrs()

    def _build_unique_id(self, mac_address: str, key: str) -> str:
        """Build a stable unique ID, delegating to the shared function."""
        return build_unique_id(
            mac_address,
            self._role_key,
            key,
            device_index=self._device_index,
            device_node_addr=self._device_node_addr,
        )

    @callback
    def _update_attrs(self) -> None:
        """Update cached entity attributes from coordinator data."""
        parsed_data = ensure_parsed_data(self.coordinator)
        if self._role_key == "chem_sync":
            self._attr_options = get_chem_sync_mode_options()
            self._attr_current_option = get_select_value(
                parsed_data,
                self.entity_description.key,
                role_key=self._role_key,
                index=self._device_index,
            )
        else:
            self._attr_options = get_heat_pump_mode_options(
                parsed_data, index=self._device_index
            )
            self._attr_current_option = get_select_value(
                parsed_data, self.entity_description.key, index=self._device_index
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
        """Select a new mode from a synchronous context."""
        if self.hass is None:
            raise HomeAssistantError("Entity is not added to Home Assistant")

        self.hass.add_job(self.async_select_option, option)

    async def async_select_option(self, option: str) -> None:
        """Select a new mode."""
        if option not in self.options:
            raise HomeAssistantError(f"Unsupported option: {option}")

        self._attr_current_option = option
        if self.hass is not None:
            self.async_write_ha_state()

        if self._role_key == "chem_sync":
            await self.coordinator.async_set_chem_config(
                self.entity_description.key,
                get_chem_sync_mode_options().index(option),
                index=self._device_index,
            )
        else:
            await self.coordinator.async_set_heat_pump_mode_context(
                option, index=self._device_index
            )

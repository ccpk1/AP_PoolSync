"""Button platform for the PoolSync Custom integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync button entities based on a config entry."""
    del hass
    coordinator = entry.runtime_data

    async_add_entities(
        [
            PoolSyncButton(
                coordinator,
                ButtonEntityDescription(
                    key="manual_refresh",
                    translation_key="manual_refresh",
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
            )
        ]
    )


class PoolSyncButton(CoordinatorEntity[PoolSyncDataUpdateCoordinator], ButtonEntity):
    """Representation of a PoolSync button."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.mac_address}_{description.key}"
        self._attr_device_info = coordinator.get_device_info("controller")

    async def async_press(self) -> None:
        """Manually refresh PoolSync data through the coordinator."""
        await self.coordinator.async_manual_refresh()

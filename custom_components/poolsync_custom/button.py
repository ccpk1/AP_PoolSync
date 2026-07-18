"""Button platform for the PoolSync Custom integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import build_unique_id, ensure_parsed_data

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync button entities based on a config entry."""
    del hass
    coordinator = entry.runtime_data

    buttons: list[PoolSyncButton] = [
        PoolSyncButton(
            coordinator,
            ButtonEntityDescription(
                key="manual_refresh",
                translation_key="manual_refresh",
                entity_category=EntityCategory.CONFIG,
            ),
        )
    ]

    # Device action buttons (gracefully skip if runtime data not available)
    try:
        parsed_data = ensure_parsed_data(coordinator)
    except HomeAssistantError:
        parsed_data = None

    if parsed_data is not None:
        # ChemSync action buttons
        for index, device in enumerate(parsed_data.devices.get("chem_sync", [])):
            if not device.is_present:
                continue
            for action_key, action_translation in (
                ("chem_prime_pump", "chem_prime_pump"),
                ("chem_boost", "chem_boost"),
            ):
                buttons.append(
                    PoolSyncButton(
                        coordinator,
                        ButtonEntityDescription(
                            key=action_key,
                            translation_key=action_translation,
                            entity_category=EntityCategory.CONFIG,
                        ),
                        role="chem_sync",
                        device_index=index,
                    )
                )

        # ChlorSync action buttons
        for index, device in enumerate(parsed_data.devices.get("chlorinator", [])):
            if not device.is_present:
                continue
            buttons.append(
                PoolSyncButton(
                    coordinator,
                    ButtonEntityDescription(
                        key="chlor_clear_cell_life",
                        translation_key="chlor_clear_cell_life",
                        entity_category=EntityCategory.CONFIG,
                    ),
                    role="chlorinator",
                    device_index=index,
                )
            )

    async_add_entities(buttons)


def get_valid_entity_keys() -> dict[str, set[str]]:
    """Return the set of valid entity keys for each role, for orphan cleanup."""
    return {
        "controller": {"manual_refresh"},
        "chem_sync": {"chem_prime_pump", "chem_boost"},
        "chlorinator": {"chlor_clear_cell_life"},
    }


class PoolSyncButton(CoordinatorEntity[PoolSyncDataUpdateCoordinator], ButtonEntity):  # type: ignore[abstract]  # pylint: disable=abstract-method
    """Representation of a PoolSync button."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: ButtonEntityDescription,
        *,
        role: str | None = None,
        device_index: int = 0,
        device_node_addr: int | None = None,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._role_key = role or "controller"
        self._device_index = device_index
        self._device_node_addr = device_node_addr
        self._attr_unique_id = build_unique_id(
            coordinator.mac_address,
            self._role_key,
            description.key,
            device_index=device_index,
            device_node_addr=device_node_addr,
        )
        self._attr_device_info = coordinator.get_device_info(
            self._role_key, index=device_index
        )

    async def async_press(self) -> None:
        """Execute the button action."""
        key = self.entity_description.key
        if key == "manual_refresh":
            await self.coordinator.async_manual_refresh()
        elif key == "chem_prime_pump":
            await self.coordinator.async_chem_prime_pump(index=self._device_index)
        elif key == "chem_boost":
            await self.coordinator.async_chem_boost(index=self._device_index)
        elif key == "chlor_clear_cell_life":
            await self.coordinator.async_chlor_clear_cell_life(index=self._device_index)

"""Switch platform for the PoolSync Custom integration."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import GROUP_IDX_STATE
from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import build_unique_id, ensure_parsed_data, get_equipment_runtime

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync switch entities based on a config entry."""
    del hass
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    parsed_data = ensure_parsed_data(coordinator)

    entities: list[PoolSyncGroupSwitch] = []

    # Group switches — one per heat pump device that has groups
    for hp_index, device in enumerate(parsed_data.devices.get("heat_pump", [])):
        if not device.is_present:
            continue
        equip_runtime = get_equipment_runtime(parsed_data)
        if equip_runtime is None or not isinstance(equip_runtime.raw_groups, dict):
            continue

        for group_key, group_data in equip_runtime.raw_groups.items():
            if not isinstance(group_data, dict):
                continue
            config = group_data.get("config")
            if not isinstance(config, list) or len(config) < 4:
                continue
            group_name = (
                config[0] if isinstance(config[0], str) else f"Group {group_key}"
            )

            entities.append(
                PoolSyncGroupSwitch(
                    coordinator,
                    SwitchEntityDescription(
                        key=f"group_{group_key}",
                        name=group_name,
                    ),
                    group_key=group_key,
                    group_name=group_name,
                    hp_index=hp_index,
                )
            )

    if entities:
        async_add_entities(entities)


def get_valid_entity_keys() -> dict[str, set[str]]:
    """Return the static set of valid entity keys for each role.

    Group switches are dynamic (one per defined group) and are handled
    separately by the cleanup function using parsed runtime data.
    """
    return {"heat_pump": set()}


class PoolSyncGroupSwitch(  # type: ignore[abstract]  # pylint: disable=abstract-method
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], SwitchEntity
):
    """Representation of a PoolSync group on/off switch."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: SwitchEntityDescription,
        *,
        group_key: str,
        group_name: str,
        hp_index: int = 0,
    ) -> None:
        """Initialize the group switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._group_key = group_key
        self._group_name = group_name
        self._hp_index = hp_index
        self._attr_unique_id = build_unique_id(
            coordinator.mac_address,
            "heat_pump",
            f"group_{group_key}",
            device_index=hp_index,
        )
        self._attr_device_info = coordinator.get_device_info(
            "heat_pump", index=hp_index
        )
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        """Update cached entity attributes from coordinator data."""
        parsed_data = ensure_parsed_data(self.coordinator)
        equip_runtime = get_equipment_runtime(parsed_data)
        if equip_runtime is None or not isinstance(equip_runtime.raw_groups, dict):
            self._attr_is_on = None
            self._attr_available = False
            return

        group_data = equip_runtime.raw_groups.get(self._group_key)
        if not isinstance(group_data, dict):
            self._attr_is_on = None
            self._attr_available = False
            return

        config = group_data.get("config")
        if not isinstance(config, list) or len(config) <= GROUP_IDX_STATE:
            self._attr_is_on = None
            self._attr_available = False
            return

        state = config[GROUP_IDX_STATE]
        self._attr_is_on = bool(state) if isinstance(state, int) else None
        self._attr_available = super().available and self._attr_is_on is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attrs()
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the group on."""
        await self.coordinator.async_set_group_state(
            self._group_key, True, index=self._hp_index
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the group off."""
        await self.coordinator.async_set_group_state(
            self._group_key, False, index=self._hp_index
        )

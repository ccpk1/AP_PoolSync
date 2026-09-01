"""Switch platform for the PoolSync Custom integration."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import GROUP_IDX_STATE
from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import (
    build_unique_id,
    ensure_parsed_data,
    get_equipment_runtime,
    get_group_duration,
    get_group_ends_at,
)

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

    # Group switches — one per group, attached to the controller device
    equip_runtime = get_equipment_runtime(parsed_data)
    if equip_runtime is not None and isinstance(equip_runtime.raw_groups, dict):
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
                        translation_key="group",
                    ),
                    group_key=group_key,
                    group_name=group_name,
                )
            )

    if entities:
        async_add_entities(entities)


class PoolSyncGroupSwitch(  # type: ignore[abstract]  # pylint: disable=abstract-method
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], SwitchEntity
):
    """Representation of a PoolSync group on/off switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: SwitchEntityDescription,
        *,
        group_key: str,
        group_name: str,
    ) -> None:
        """Initialize the group switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._group_key = group_key
        self._group_name = group_name
        self._attr_unique_id = build_unique_id(
            coordinator.mac_address,
            "controller",
            f"group_{group_key}",
        )
        self._attr_device_info = coordinator.get_device_info("controller")
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

        # Timing attributes (anti-noise: ends_at is a fixed timestamp that only
        # moves when the device extends/cancels the timer, so it rarely writes)
        duration = get_group_duration(equip_runtime, self._group_key)
        ends_at = get_group_ends_at(
            equip_runtime, self._group_key, dt_util.utcnow()
        )
        self._attr_extra_state_attributes = {}
        if duration is not None:
            self._attr_extra_state_attributes["duration"] = duration
        if ends_at is not None:
            self._attr_extra_state_attributes["ends_at"] = ends_at.isoformat()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attrs()
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the group on (uses the group's default duration)."""
        await self.coordinator.async_set_group_state(self._group_key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the group off."""
        await self.coordinator.async_set_group_state(self._group_key, False)

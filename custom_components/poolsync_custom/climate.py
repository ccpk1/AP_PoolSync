"""Climate platform for the PoolSync Custom integration."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
)
from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import (
    HEAT_PUMP_PRESET_POOL,
    PoolSyncHeatPumpClimateHvacMode,
    PoolSyncHeatPumpClimatePresetMode,
    ensure_parsed_data,
    get_heat_pump_climate_current_temperature,
    get_heat_pump_climate_hvac_action,
    get_heat_pump_climate_hvac_mode,
    get_heat_pump_climate_hvac_modes,
    get_heat_pump_climate_max_temp,
    get_heat_pump_climate_min_temp,
    get_heat_pump_climate_preset_mode,
    get_heat_pump_climate_preset_modes,
    get_heat_pump_climate_target_temperature,
)

PARALLEL_UPDATES = 0

_HVAC_MODE_MAP: dict[str, HVACMode] = {
    "off": HVACMode.OFF,
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "auto": HVACMode.AUTO,
}
_HVAC_ACTION_MAP: dict[str, HVACAction] = {
    "off": HVACAction.OFF,
    "idle": HVACAction.IDLE,
    "heating": HVACAction.HEATING,
    "cooling": HVACAction.COOLING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoolSync climate entities based on a config entry."""
    del hass
    coordinator = cast(PoolSyncDataUpdateCoordinator, entry.runtime_data)
    parsed_data = ensure_parsed_data(coordinator)

    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices:
        return

    entities: list[PoolSyncHeatPumpClimateEntity] = []
    for index, device in enumerate(hp_devices):
        if not device.is_present:
            continue
        entities.append(
            PoolSyncHeatPumpClimateEntity(
                coordinator,
                ClimateEntityDescription(
                    key="water_thermostat",
                    translation_key="water_thermostat",
                ),
                device_index=index,
                device_node_addr=device.node_addr,
            )
        )

    if entities:
        async_add_entities(entities)


class PoolSyncHeatPumpClimateEntity(  # pyright: ignore[reportIncompatibleVariableOverride]
    CoordinatorEntity[PoolSyncDataUpdateCoordinator], ClimateEntity, RestoreEntity
):
    """Representation of the PoolSync heat-pump climate entity."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_target_temperature_step = 1
    _attr_min_temp = 40
    _attr_max_temp = 104
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(
        self,
        coordinator: PoolSyncDataUpdateCoordinator,
        description: ClimateEntityDescription,
        device_index: int = 0,
        device_node_addr: int | None = None,
    ) -> None:
        """Initialize the heat-pump climate entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device_index = device_index
        self._device_node_addr = device_node_addr
        self._attr_unique_id = self._build_unique_id(
            coordinator.mac_address, description.key
        )
        self._attr_device_info = coordinator.get_device_info(
            "heat_pump", index=device_index
        )
        self._last_on_preset_mode: PoolSyncHeatPumpClimatePresetMode = (
            HEAT_PUMP_PRESET_POOL
        )
        self._update_attrs()

    def _build_unique_id(self, mac_address: str, key: str) -> str:
        """Build a stable unique ID, preserving BC for first-instance entities."""
        if self._device_index == 0:
            return f"{mac_address}_{key}"
        if self._device_node_addr is not None:
            return f"{mac_address}_heat_pump_{self._device_node_addr}_{key}"
        return f"{mac_address}_heat_pump_{self._device_index}_{key}"

    async def async_added_to_hass(self) -> None:
        """Restore last preset state when the entity is added."""
        await super().async_added_to_hass()

        if self._attr_preset_mode is not None:
            self._last_on_preset_mode = cast(
                PoolSyncHeatPumpClimatePresetMode, self._attr_preset_mode
            )
            return

        if (last_state := await self.async_get_last_state()) is None:
            return

        if (preset_mode := last_state.attributes.get(ATTR_PRESET_MODE)) in {
            "pool",
            "spa",
        }:
            self._last_on_preset_mode = cast(
                PoolSyncHeatPumpClimatePresetMode, preset_mode
            )
            self._attr_preset_mode = preset_mode
            self._attr_target_temperature = get_heat_pump_climate_target_temperature(
                ensure_parsed_data(self.coordinator),
                self._last_on_preset_mode,
                index=self._device_index,
            )

    @callback
    def _update_attrs(self) -> None:
        """Update cached climate attributes from coordinator data."""
        parsed_data = ensure_parsed_data(self.coordinator)
        hp_index = self._device_index

        hvac_modes = get_heat_pump_climate_hvac_modes(parsed_data, index=hp_index)
        self._attr_hvac_modes = [_HVAC_MODE_MAP[mode] for mode in hvac_modes]

        preset_modes = get_heat_pump_climate_preset_modes(parsed_data, index=hp_index)
        self._attr_preset_modes = list(preset_modes)

        runtime_preset_mode = get_heat_pump_climate_preset_mode(
            parsed_data, index=hp_index
        )
        if runtime_preset_mode is not None:
            self._last_on_preset_mode = runtime_preset_mode

        hvac_mode = get_heat_pump_climate_hvac_mode(parsed_data, index=hp_index)
        self._attr_hvac_mode = _HVAC_MODE_MAP.get(hvac_mode) if hvac_mode else None

        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_preset_mode = self._last_on_preset_mode
        else:
            self._attr_preset_mode = runtime_preset_mode

        self._attr_hvac_action = _HVAC_ACTION_MAP.get(
            get_heat_pump_climate_hvac_action(parsed_data, index=hp_index) or ""
        )
        self._attr_current_temperature = get_heat_pump_climate_current_temperature(
            parsed_data, index=hp_index
        )
        self._attr_target_temperature = get_heat_pump_climate_target_temperature(
            parsed_data,
            cast(
                PoolSyncHeatPumpClimatePresetMode | None,
                self._attr_preset_mode,
            ),
            index=hp_index,
        )
        self._attr_min_temp = get_heat_pump_climate_min_temp(
            parsed_data, index=hp_index
        )
        self._attr_max_temp = get_heat_pump_climate_max_temp(
            parsed_data, index=hp_index
        )
        self._attr_available = (
            super().available
            and self._attr_current_temperature is not None
            and self._attr_target_temperature is not None
            and self._attr_hvac_mode is not None
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        ensure_parsed_data(self.coordinator, refresh=True)
        self._update_attrs()
        super()._handle_coordinator_update()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode for the heat pump."""
        if hvac_mode not in self.hvac_modes:
            raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")

        target_preset = (
            self._last_on_preset_mode
            if self.hvac_mode == HVACMode.OFF
            else cast(
                PoolSyncHeatPumpClimatePresetMode,
                self.preset_mode or self._last_on_preset_mode,
            )
        )
        await self.coordinator.async_set_heat_pump_climate_mode(
            hvac_mode=cast(PoolSyncHeatPumpClimateHvacMode, hvac_mode.value),
            preset_mode=target_preset,
            index=self._device_index,
        )

    def set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode from a synchronous context."""
        if self.hass is None:
            raise HomeAssistantError("Entity is not added to Home Assistant")

        self.hass.add_job(self.async_set_hvac_mode, hvac_mode)

    async def async_turn_on(self) -> None:
        """Turn the heat pump on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    def turn_on(self) -> None:
        """Turn the heat pump on from a synchronous context."""
        if self.hass is None:
            raise HomeAssistantError("Entity is not added to Home Assistant")

        self.hass.add_job(self.async_turn_on)

    async def async_turn_off(self) -> None:
        """Turn the heat pump off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    def turn_off(self) -> None:
        """Turn the heat pump off from a synchronous context."""
        if self.hass is None:
            raise HomeAssistantError("Entity is not added to Home Assistant")

        self.hass.add_job(self.async_turn_off)

    def toggle(self) -> None:
        """Toggle the heat pump from a synchronous context."""
        if self.hvac_mode == HVACMode.OFF:
            self.turn_on()
            return

        self.turn_off()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the body context preset mode."""
        if preset_mode not in (self.preset_modes or []):
            raise HomeAssistantError(f"Unsupported preset mode: {preset_mode}")

        self._last_on_preset_mode = cast(PoolSyncHeatPumpClimatePresetMode, preset_mode)

        if (hvac_mode := self.hvac_mode) is None:
            raise HomeAssistantError(
                "Cannot set preset mode while heat pump mode is unknown"
            )

        if hvac_mode == HVACMode.OFF:
            self._attr_preset_mode = preset_mode
            self._attr_target_temperature = get_heat_pump_climate_target_temperature(
                ensure_parsed_data(self.coordinator),
                self._last_on_preset_mode,
            )
            if self.hass is not None:
                self.async_write_ha_state()
            return

        await self.coordinator.async_set_heat_pump_climate_mode(
            hvac_mode=cast(PoolSyncHeatPumpClimateHvacMode, hvac_mode.value),
            preset_mode=self._last_on_preset_mode,
            index=self._device_index,
        )

    def set_preset_mode(self, preset_mode: str) -> None:
        """Set the body context preset from a synchronous context."""
        if self.hass is None:
            raise HomeAssistantError("Entity is not added to Home Assistant")

        self.hass.add_job(self.async_set_preset_mode, preset_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature for the active or selected body."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            raise HomeAssistantError(f"Expected attribute {ATTR_TEMPERATURE}")

        await self.coordinator.async_set_heat_pump_active_target(
            int(temperature),
            preset_mode=cast(
                PoolSyncHeatPumpClimatePresetMode,
                self.preset_mode or self._last_on_preset_mode,
            ),
            index=self._device_index,
        )

    def set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature from a synchronous context."""
        if self.hass is None:
            raise HomeAssistantError("Entity is not added to Home Assistant")

        self.hass.add_job(self.async_set_temperature, **kwargs)

    def set_fan_mode(self, fan_mode: str) -> None:
        """Fan modes are not supported by the PoolSync heat pump climate."""
        raise NotImplementedError(fan_mode)

    def set_humidity(self, humidity: int) -> None:
        """Humidity control is not supported by the PoolSync heat pump climate."""
        raise NotImplementedError(humidity)

    def set_swing_mode(self, swing_mode: str) -> None:
        """Swing modes are not supported by the PoolSync heat pump climate."""
        raise NotImplementedError(swing_mode)

    def set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Horizontal swing is not supported by the PoolSync heat pump climate."""
        raise NotImplementedError(swing_horizontal_mode)

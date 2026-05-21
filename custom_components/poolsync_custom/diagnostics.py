"""Diagnostics support for the PoolSync Custom integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import PoolSyncConfigEntry
from .const import API_RESPONSE_MAC_ADDRESS, DOMAIN
from .runtime import ensure_parsed_data, get_heat_pump_runtime

TO_REDACT = {
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    API_RESPONSE_MAC_ADDRESS,
    "bssid",
    "cellSerialNum",
    "drvSerialNum",
    "latitude",
    "longitude",
    "macAddr",
    "serialNum",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PoolSyncConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    result: dict[str, Any] = {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
    }

    coordinator = entry.runtime_data if hasattr(entry, "runtime_data") else None
    if coordinator is None:
        return result

    result["coordinator"] = {
        "last_update_success": coordinator.last_update_success,
        "last_exception": (
            str(coordinator.last_exception) if coordinator.last_exception else None
        ),
        "name": coordinator.name,
        "update_interval_seconds": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
    }

    if coordinator.data is not None:
        result["runtime_data"] = async_redact_data(coordinator.data, TO_REDACT)

        if heat_pump_runtime := get_heat_pump_runtime(ensure_parsed_data(coordinator)):
            result["heat_pump_debug"] = {
                "active_target_temperature": heat_pump_runtime.active_target_temperature,
                "capabilities": {
                    "model_number": heat_pump_runtime.capabilities.model_number,
                    "profile": heat_pump_runtime.capabilities.profile,
                    "supports_cooling": heat_pump_runtime.capabilities.supports_cooling,
                    "supports_pool_spa_mode": heat_pump_runtime.capabilities.supports_pool_spa_mode,
                    "supports_separate_spa_setpoint": heat_pump_runtime.capabilities.supports_separate_spa_setpoint,
                },
                "compressor_running": heat_pump_runtime.compressor_running,
                "ctrl_flags_raw": heat_pump_runtime.ctrl_flags_raw,
                "fan_running": heat_pump_runtime.fan_running,
                "has_flow": heat_pump_runtime.has_flow,
                "mode_context": heat_pump_runtime.mode_context,
                "mode_value": heat_pump_runtime.mode_value,
                "pool_setpoint": heat_pump_runtime.pool_setpoint,
                "pool_spa_mode": heat_pump_runtime.pool_spa_mode,
                "spa_setpoint": heat_pump_runtime.spa_setpoint,
                "state_flags_raw": heat_pump_runtime.state_flags_raw,
            }

    if device := dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, coordinator.mac_address)}
    ):
        result["device"] = {
            "entry_type": str(device.entry_type) if device.entry_type else None,
            "hw_version": device.hw_version,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "name": device.name,
            "name_by_user": device.name_by_user,
            "sw_version": device.sw_version,
        }

    return result

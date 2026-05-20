"""Diagnostics support for the PoolSync Custom integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import PoolSyncConfigEntry
from .const import API_RESPONSE_MAC_ADDRESS, DOMAIN

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

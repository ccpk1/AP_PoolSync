"""Diagnostics support for the PoolSync Custom integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import PoolSyncConfigEntry
from .const import API_RESPONSE_MAC_ADDRESS, DOMAIN
from .runtime import (
    ensure_parsed_data,
    get_equipment_runtime,
    get_heat_pump_runtime,
    get_pump_priming,
    get_pump_rpm,
    get_pump_rpm_max,
    get_pump_rpm_min,
    get_sensor_value,
    get_valve_position_name,
    get_valve_position_options,
)

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
        "last_failure_class": coordinator.last_failure_class,
        "last_failure_context": coordinator.last_failure_context,
        "last_failure_detail": coordinator.last_failure_detail,
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
        parsed_data = ensure_parsed_data(coordinator)

        # --- Heat pump derived state ---
        if heat_pump_runtime := get_heat_pump_runtime(parsed_data):
            result["heat_pump_debug"] = {
                "active_target_temperature": heat_pump_runtime.active_target_temperature,
                "active_fault_code": get_sensor_value(parsed_data, "hp_fault_code"),
                "capabilities": {
                    "model_number": heat_pump_runtime.capabilities.model_number,
                    "profile": heat_pump_runtime.capabilities.profile,
                    "supports_heating": heat_pump_runtime.capabilities.supports_heating,
                    "supports_cooling": heat_pump_runtime.capabilities.supports_cooling,
                    "supports_pool_spa_mode": heat_pump_runtime.capabilities.supports_pool_spa_mode,
                    "supports_separate_spa_setpoint": heat_pump_runtime.capabilities.supports_separate_spa_setpoint,
                },
                "compressor_running": heat_pump_runtime.compressor_running,
                "ctrl_flags_raw": heat_pump_runtime.ctrl_flags_raw,
                "faults_raw": (
                    _hp_device.data.get("faults")
                    if (_hp_devices := parsed_data.devices.get("heat_pump", []))
                    and (_hp_device := _hp_devices[0])
                    and _hp_device.data is not None
                    else None
                ),
                "fan_running": heat_pump_runtime.fan_running,
                "has_flow": heat_pump_runtime.has_flow,
                "mode_context": heat_pump_runtime.mode_context,
                "mode_value": heat_pump_runtime.mode_value,
                "pool_setpoint": heat_pump_runtime.pool_setpoint,
                "pool_spa_mode": heat_pump_runtime.pool_spa_mode,
                "spa_setpoint": heat_pump_runtime.spa_setpoint,
                "state_flags_raw": heat_pump_runtime.state_flags_raw,
            }

        # --- Equipment derived state ---
        if equip_runtime := get_equipment_runtime(parsed_data):
            equip_debug: dict[str, Any] = {
                "active_group_names": equip_runtime.active_group_names,
                "active_group_attributes": equip_runtime.active_group_attributes,
                "pump_rpm": get_pump_rpm(equip_runtime),
                "pump_rpm_min": get_pump_rpm_min(equip_runtime),
                "pump_rpm_max": get_pump_rpm_max(equip_runtime),
                "pump_priming": get_pump_priming(equip_runtime),
                "valve_position": get_valve_position_name(equip_runtime),
                "valve_position_options": get_valve_position_options(equip_runtime),
            }
            # Include raw equipment entries for debugging
            equip_debug["equipment"] = {
                sk: {
                    "type": e.equip_type,
                    "name": e.name,
                    "is_pump": e.is_pump,
                    "is_valve": e.is_valve,
                    "is_heat_pump": e.is_heat_pump,
                    "raw": e.raw,
                }
                for sk, e in equip_runtime.equipment.items()
            }
            result["equipment_debug"] = equip_debug

        # --- All mapped sensor values ---
        sensor_values: dict[str, Any] = {}
        for key in (
            "board_temp",
            "wifi_rssi",
            "wifi_signal_status",
            "system_datetime",
            "firmware_version",
            "hardware_version",
        ):
            sensor_values[key] = get_sensor_value(parsed_data, key)

        # Chlorinator mapped values
        chlor_devices = parsed_data.devices.get("chlorinator", [])
        if chlor_devices:
            for idx in range(len(chlor_devices)):
                prefix = f"chlorinator_{idx}_"
                for key in (
                    "water_temp",
                    "salt_ppm",
                    "chlor_board_temp",
                    "flow_rate",
                    "chlor_output_setting",
                    "boost_remaining",
                    "cell_fwd_current",
                    "cell_rev_current",
                    "cell_output_voltage",
                    "cell_serial_number",
                    "cell_firmware_version",
                    "cell_hardware_version",
                    "cell_rail_voltage",
                    "temp_comp_output",
                    "drv_model_num",
                    "drv_fw_version",
                    "drv_hw_version",
                ):
                    sensor_values[f"{prefix}{key}"] = get_sensor_value(
                        parsed_data, key, role_key="chlorinator", index=idx
                    )

        # ChemSync mapped values
        chem_devices = parsed_data.devices.get("chem_sync", [])
        if chem_devices:
            for idx in range(len(chem_devices)):
                prefix = f"chem_sync_{idx}_"
                for key in (
                    "chem_ph",
                    "chem_orp",
                    "chem_board_temp",
                    "chem_acid_consumed",
                    "chem_fw_version",
                    "chem_hw_version",
                    "chem_model_num",
                ):
                    sensor_values[f"{prefix}{key}"] = get_sensor_value(
                        parsed_data, key, role_key="chem_sync", index=idx
                    )

        # Heat pump mapped values
        hp_devices = parsed_data.devices.get("heat_pump", [])
        if hp_devices:
            for idx in range(len(hp_devices)):
                prefix = f"heat_pump_{idx}_"
                for key in (
                    "hp_water_temp",
                    "hp_air_temp",
                    "hp_board_temp",
                    "hp_mode",
                    "hp_setpoint_temp",
                    "hp_pool_setpoint_temp",
                    "hp_spa_setpoint_temp",
                    "hp_water_temp2",
                    "hp_ds1_temp",
                    "hp_ds2_temp",
                    "hp_fault_code",
                    "hp_top_fault_code",
                    "hp_top_fault_count",
                ):
                    sensor_values[f"{prefix}{key}"] = get_sensor_value(
                        parsed_data, key, role_key="heat_pump", index=idx
                    )

        result["mapped_sensor_values"] = sensor_values

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

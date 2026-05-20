"""Runtime parsing helpers for the PoolSync Custom integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from homeassistant.exceptions import HomeAssistantError

from .const import CHLORINATOR_ID, HEATPUMP_ID

type PoolSyncDeviceRole = Literal["chlorinator", "heat_pump"]


@dataclass(frozen=True, slots=True)
class PoolSyncSystemData:
    """Normalized PoolSync system payload."""

    data: dict[str, Any] | None

    @property
    def is_present(self) -> bool:
        """Return whether system payload is present."""
        return self.data is not None

    @property
    def config(self) -> dict[str, Any] | None:
        """Return system config data."""
        if self.data is None:
            return None
        config = self.data.get("config")
        return config if isinstance(config, dict) else None

    @property
    def status(self) -> dict[str, Any] | None:
        """Return system status data."""
        if self.data is None:
            return None
        status = self.data.get("status")
        return status if isinstance(status, dict) else None

    @property
    def system(self) -> dict[str, Any] | None:
        """Return system metadata."""
        if self.data is None:
            return None
        system = self.data.get("system")
        return system if isinstance(system, dict) else None

    @property
    def stats(self) -> dict[str, Any] | None:
        """Return system stats."""
        if self.data is None:
            return None
        stats = self.data.get("stats")
        return stats if isinstance(stats, dict) else None


@dataclass(frozen=True, slots=True)
class PoolSyncDeviceRoleData:
    """Normalized device-role payload."""

    role: str
    device_id: str | None
    data: dict[str, Any] | None

    @property
    def is_detected(self) -> bool:
        """Return whether a device ID is resolved for this role."""
        return self.device_id is not None

    @property
    def is_present(self) -> bool:
        """Return whether the resolved device payload exists."""
        return self.data is not None

    @property
    def config(self) -> dict[str, Any] | None:
        """Return device config data."""
        if self.data is None:
            return None
        config = self.data.get("config")
        return config if isinstance(config, dict) else None

    @property
    def status(self) -> dict[str, Any] | None:
        """Return device status data."""
        if self.data is None:
            return None
        status = self.data.get("status")
        return status if isinstance(status, dict) else None

    @property
    def system(self) -> dict[str, Any] | None:
        """Return device system data."""
        if self.data is None:
            return None
        system = self.data.get("system")
        return system if isinstance(system, dict) else None

    @property
    def node_attr(self) -> dict[str, Any] | None:
        """Return device node attributes."""
        if self.data is None:
            return None
        node_attr = self.data.get("nodeAttr")
        return node_attr if isinstance(node_attr, dict) else None


@dataclass(frozen=True, slots=True)
class PoolSyncParsedData:
    """Normalized read model for the latest PoolSync payload."""

    system: PoolSyncSystemData
    chlorinator: PoolSyncDeviceRoleData
    heat_pump: PoolSyncDeviceRoleData


def ensure_parsed_data(
    coordinator: Any, *, refresh: bool = False
) -> PoolSyncParsedData:
    """Return parsed runtime data for a coordinator-like object."""
    parsed_data = getattr(coordinator, "parsed_data", None)
    if not refresh and isinstance(parsed_data, PoolSyncParsedData):
        return parsed_data

    data = getattr(coordinator, "data", None)
    if not isinstance(data, dict):
        raise HomeAssistantError("PoolSync runtime data is not available")

    parsed_data = parse_poolsync_runtime_data(data)
    coordinator.parsed_data = parsed_data
    return parsed_data


def get_role_data(
    parsed_data: PoolSyncParsedData, role: PoolSyncDeviceRole
) -> PoolSyncDeviceRoleData:
    """Return normalized data for a known device role."""
    return parsed_data.chlorinator if role == "chlorinator" else parsed_data.heat_pump


def _get_dict_value(section: dict[str, Any] | None, key: str) -> Any:
    """Return a value from a parsed section when available."""
    return section.get(key) if section is not None else None


def _resolve_device_role_ids(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve heat pump and chlorinator device IDs from payload data."""
    heatpump_id: str | None = HEATPUMP_ID
    chlorinator_id: str | None = CHLORINATOR_ID

    if isinstance(data.get("deviceType"), dict):
        device_types = cast(dict[str, str], data["deviceType"])
        heatpump_id = next(
            (key for key, value in device_types.items() if value == "heatPump"),
            None,
        )
        chlorinator_id = next(
            (key for key, value in device_types.items() if value == "chlorSync"),
            None,
        )

    return heatpump_id, chlorinator_id


def parse_poolsync_runtime_data(data: dict[str, Any]) -> PoolSyncParsedData:
    """Parse raw PoolSync payload into normalized runtime data."""
    raw_devices = data.get("devices")
    devices: dict[str, Any]
    if isinstance(raw_devices, dict):
        devices = cast(dict[str, Any], raw_devices)
    else:
        devices = {}

    raw_system_data = data.get("poolSync")
    system_data = (
        cast(dict[str, Any], raw_system_data)
        if isinstance(raw_system_data, dict)
        else None
    )

    heatpump_id, chlorinator_id = _resolve_device_role_ids(data)

    chlorinator_data = (
        cast(dict[str, Any], devices[chlorinator_id])
        if chlorinator_id is not None
        and chlorinator_id in devices
        and isinstance(devices.get(chlorinator_id), dict)
        else None
    )
    heatpump_data = (
        cast(dict[str, Any], devices[heatpump_id])
        if heatpump_id is not None
        and heatpump_id in devices
        and isinstance(devices.get(heatpump_id), dict)
        else None
    )

    return PoolSyncParsedData(
        system=PoolSyncSystemData(system_data),
        chlorinator=PoolSyncDeviceRoleData(
            role="chlorinator",
            device_id=chlorinator_id,
            data=chlorinator_data,
        ),
        heat_pump=PoolSyncDeviceRoleData(
            role="heat_pump",
            device_id=heatpump_id,
            data=heatpump_data,
        ),
    )


_NUMBER_VALUE_GETTERS: dict[str, Callable[[PoolSyncParsedData], Any]] = {
    "chlor_output_control": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.config, "chlorOutput"
    ),
    "temperature_output_control": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.config, "setpoint"
    ),
    "heat_mode": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.config, "mode"
    ),
}


_BINARY_SENSOR_VALUE_GETTERS: dict[str, Callable[[PoolSyncParsedData], Any]] = {
    "poolsync_online": lambda parsed_data: _get_dict_value(
        parsed_data.system.status, "online"
    ),
    "service_mode_active": lambda parsed_data: _get_dict_value(
        parsed_data.system.config, "serviceMode"
    ),
    "system_fault": lambda parsed_data: _get_dict_value(
        parsed_data.system.data, "faults"
    ),
    "chlorsync_online": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.node_attr, "online"
    ),
    "chlorsync_fault": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.data, "faults"
    ),
    "heatpump_online": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.node_attr, "online"
    ),
    "heatpump_fault": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.data, "faults"
    ),
    "heatpump_flow": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.status, "ctrlFlags"
    ),
    "heatpump_compressor": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.status, "stateFlags"
    ),
    "heatpump_fan": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.status, "stateFlags"
    ),
}


_SENSOR_VALUE_GETTERS: dict[str, Callable[[PoolSyncParsedData], Any]] = {
    "board_temp": lambda parsed_data: _get_dict_value(
        parsed_data.system.status, "boardTemp"
    ),
    "wifi_rssi": lambda parsed_data: _get_dict_value(parsed_data.system.status, "rssi"),
    "system_datetime": lambda parsed_data: _get_dict_value(
        parsed_data.system.status, "dateTime"
    ),
    "firmware_version": lambda parsed_data: _get_dict_value(
        parsed_data.system.system, "fwVersion"
    ),
    "hardware_version": lambda parsed_data: _get_dict_value(
        parsed_data.system.system, "hwVersion"
    ),
    "uptime_seconds": lambda parsed_data: _get_dict_value(
        parsed_data.system.stats, "upTimeSecs"
    ),
    "water_temp": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "waterTemp"
    ),
    "salt_ppm": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "saltPPM"
    ),
    "flow_rate": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "flowRate"
    ),
    "chlor_output_setting": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.config, "chlorOutput"
    ),
    "boost_remaining": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "boostRemaining"
    ),
    "cell_fwd_current": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "fwdCurrent"
    ),
    "cell_rev_current": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "revCurrent"
    ),
    "cell_output_voltage": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "outVoltage"
    ),
    "cell_serial_number": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.system, "cellSerialNum"
    ),
    "cell_firmware_version": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.system, "cellFwVersion"
    ),
    "cell_hardware_version": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.system, "cellHwVersion"
    ),
    "hp_water_temp": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.status, "waterTemp"
    ),
    "hp_air_temp": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.status, "airTemp"
    ),
    "hp_mode": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.config, "mode"
    ),
    "hp_setpoint_temp": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.config, "setpoint"
    ),
}


def get_number_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a number value from parsed runtime data."""
    getter = _NUMBER_VALUE_GETTERS.get(key)
    return getter(parsed_data) if getter is not None else None


def get_binary_sensor_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a binary sensor source value from parsed runtime data."""
    getter = _BINARY_SENSOR_VALUE_GETTERS.get(key)
    return getter(parsed_data) if getter is not None else None


def get_sensor_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a sensor source value from parsed runtime data."""
    getter = _SENSOR_VALUE_GETTERS.get(key)
    return getter(parsed_data) if getter is not None else None

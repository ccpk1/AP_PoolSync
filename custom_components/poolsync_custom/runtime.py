"""Runtime parsing helpers for the PoolSync Custom integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from homeassistant.exceptions import HomeAssistantError

from .const import CHLORINATOR_ID, HEATPUMP_ID


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


def _get_role_data(
    parsed_data: PoolSyncParsedData, role: str
) -> PoolSyncDeviceRoleData:
    """Return normalized data for a known device role."""
    return parsed_data.chlorinator if role == "chlorinator" else parsed_data.heat_pump


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


def get_number_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a number value from parsed runtime data."""
    if key == "chlor_output_control":
        config = parsed_data.chlorinator.config
        return config.get("chlorOutput") if config is not None else None

    if key == "temperature_output_control":
        config = parsed_data.heat_pump.config
        return config.get("setpoint") if config is not None else None

    if key == "heat_mode":
        config = parsed_data.heat_pump.config
        return config.get("mode") if config is not None else None

    return None


def get_binary_sensor_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a binary sensor source value from parsed runtime data."""
    if key == "poolsync_online":
        status = parsed_data.system.status
        return status.get("online") if status is not None else None

    if key == "service_mode_active":
        config = parsed_data.system.config
        return config.get("serviceMode") if config is not None else None

    if key == "system_fault":
        return (
            parsed_data.system.data.get("faults") if parsed_data.system.data else None
        )

    if key == "chlorsync_online":
        node_attr = parsed_data.chlorinator.node_attr
        return node_attr.get("online") if node_attr is not None else None

    if key == "chlorsync_fault":
        return (
            parsed_data.chlorinator.data.get("faults")
            if parsed_data.chlorinator.data is not None
            else None
        )

    if key == "heatpump_online":
        node_attr = parsed_data.heat_pump.node_attr
        return node_attr.get("online") if node_attr is not None else None

    if key == "heatpump_fault":
        return (
            parsed_data.heat_pump.data.get("faults")
            if parsed_data.heat_pump.data is not None
            else None
        )

    status = parsed_data.heat_pump.status
    if status is None:
        return None

    if key == "heatpump_flow":
        return status.get("ctrlFlags")
    if key in {"heatpump_compressor", "heatpump_fan"}:
        return status.get("stateFlags")

    return None


def get_sensor_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a sensor source value from parsed runtime data."""
    if key == "board_temp":
        status = parsed_data.system.status
        return status.get("boardTemp") if status is not None else None

    if key == "wifi_rssi":
        status = parsed_data.system.status
        return status.get("rssi") if status is not None else None

    if key == "system_datetime":
        status = parsed_data.system.status
        return status.get("dateTime") if status is not None else None

    if key == "firmware_version":
        system = parsed_data.system.system
        return system.get("fwVersion") if system is not None else None

    if key == "hardware_version":
        system = parsed_data.system.system
        return system.get("hwVersion") if system is not None else None

    if key == "uptime_seconds":
        stats = parsed_data.system.stats
        return stats.get("upTimeSecs") if stats is not None else None

    if key == "water_temp":
        status = parsed_data.chlorinator.status
        return status.get("waterTemp") if status is not None else None

    if key == "salt_ppm":
        status = parsed_data.chlorinator.status
        return status.get("saltPPM") if status is not None else None

    if key == "flow_rate":
        status = parsed_data.chlorinator.status
        return status.get("flowRate") if status is not None else None

    if key == "chlor_output_setting":
        config = parsed_data.chlorinator.config
        return config.get("chlorOutput") if config is not None else None

    if key == "boost_remaining":
        status = parsed_data.chlorinator.status
        return status.get("boostRemaining") if status is not None else None

    if key == "cell_fwd_current":
        status = parsed_data.chlorinator.status
        return status.get("fwdCurrent") if status is not None else None

    if key == "cell_rev_current":
        status = parsed_data.chlorinator.status
        return status.get("revCurrent") if status is not None else None

    if key == "cell_output_voltage":
        status = parsed_data.chlorinator.status
        return status.get("outVoltage") if status is not None else None

    if key == "cell_serial_number":
        system = parsed_data.chlorinator.system
        return system.get("cellSerialNum") if system is not None else None

    if key == "cell_firmware_version":
        system = parsed_data.chlorinator.system
        return system.get("cellFwVersion") if system is not None else None

    if key == "cell_hardware_version":
        system = parsed_data.chlorinator.system
        return system.get("cellHwVersion") if system is not None else None

    if key == "hp_water_temp":
        status = parsed_data.heat_pump.status
        return status.get("waterTemp") if status is not None else None

    if key == "hp_air_temp":
        status = parsed_data.heat_pump.status
        return status.get("airTemp") if status is not None else None

    if key == "hp_mode":
        config = parsed_data.heat_pump.config
        return config.get("mode") if config is not None else None

    if key == "hp_setpoint_temp":
        config = parsed_data.heat_pump.config
        return config.get("setpoint") if config is not None else None

    return None

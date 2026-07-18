"""Runtime parsing helpers for the PoolSync Custom integration."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from homeassistant.exceptions import HomeAssistantError

from .const import (
    EQUIP_IDX_PARAM_8,
    EQUIP_IDX_PARAM_9,
    EQUIP_IDX_PARAM_14,
    EQUIP_IDX_STATE,
    EQUIP_TYPE_CHLORINATOR,
    EQUIP_TYPE_HEAT_PUMP,
    EQUIP_TYPE_LIGHT,
    EQUIP_TYPE_RELAY,
    EQUIP_TYPE_VALVE,
    EQUIP_TYPE_VS_PUMP,
    GROUP_IDX_NAME,
    GROUP_IDX_STATE,
    PUMP_RPM_FACTOR,
    VALVE_IDX_POSITIONS_START,
    WIFI_RSSI_FAIR_MIN,
    WIFI_RSSI_GOOD_MIN,
)

_LOGGER = logging.getLogger(__name__)

type PoolSyncDeviceRole = str
type PoolSyncHeatPumpModeContext = Literal[
    "off", "heat_pool", "heat_spa", "cool_pool", "auto_pool"
]
type PoolSyncWifiSignalStatus = Literal["good", "fair", "poor"]
type PoolSyncHeatPumpClimatePresetMode = Literal["pool", "spa"]
type PoolSyncHeatPumpClimateHvacMode = Literal["off", "heat", "cool", "auto"]
type PoolSyncHeatPumpClimateHvacAction = Literal["off", "idle", "heating", "cooling"]

HEAT_PUMP_MODE_OFF = "off"
HEAT_PUMP_MODE_HEAT_POOL = "heat_pool"
HEAT_PUMP_MODE_HEAT_SPA = "heat_spa"
HEAT_PUMP_MODE_COOL_POOL = "cool_pool"
HEAT_PUMP_MODE_AUTO_POOL = "auto_pool"
HEAT_PUMP_PRESET_POOL = "pool"
HEAT_PUMP_PRESET_SPA = "spa"

HEAT_PUMP_CONFIG_MODE_HEAT = 1
HEAT_PUMP_CONFIG_MODE_COOL = 2
HEAT_PUMP_CONFIG_MODE_AUTO = 3
HEAT_PUMP_POOL_SPA_MODE_SPA = 1
HEAT_PUMP_CTRL_FLAGS_COMPRESSOR = 4
HEAT_PUMP_CTRL_FLAGS_FAN = 8


@dataclass(frozen=True, slots=True)
class DeviceTypeInfo:
    """Metadata for a known PoolSync device type."""

    api_device_type: str
    role_key: str
    default_name: str
    default_model: str


DEVICE_TYPE_REGISTRY: dict[str, DeviceTypeInfo] = {
    "chlorSync": DeviceTypeInfo(
        api_device_type="chlorSync",
        role_key="chlorinator",
        default_name="ChlorSync",
        default_model="ChlorSync",
    ),
    "heatPump": DeviceTypeInfo(
        api_device_type="heatPump",
        role_key="heat_pump",
        default_name="Heat Pump",
        default_model="Heat Pump",
    ),
    "chemSync": DeviceTypeInfo(
        api_device_type="chemSync",
        role_key="chem_sync",
        default_name="ChemSync",
        default_model="ChemSync",
    ),
}

# Reverse lookup: role_key → DeviceTypeInfo
# Built from DEVICE_TYPE_REGISTRY so it stays in sync automatically.
ROLE_KEY_REGISTRY: dict[str, DeviceTypeInfo] = {
    info.role_key: info for info in DEVICE_TYPE_REGISTRY.values()
}


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

    role: PoolSyncDeviceRole
    device_id: str | None
    data: dict[str, Any] | None
    node_addr: int | None = None
    index: int = 0

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
    devices: dict[str, list[PoolSyncDeviceRoleData]]

    @property
    def chlorinator(self) -> PoolSyncDeviceRoleData:
        """Return the first chlorinator device, or an empty sentinel."""
        devices = self.devices.get("chlorinator", [])
        if devices:
            return devices[0]
        return PoolSyncDeviceRoleData(role="chlorinator", device_id=None, data=None)

    @property
    def heat_pump(self) -> PoolSyncDeviceRoleData:
        """Return the first heat pump device, or an empty sentinel."""
        devices = self.devices.get("heat_pump", [])
        if devices:
            return devices[0]
        return PoolSyncDeviceRoleData(role="heat_pump", device_id=None, data=None)


@dataclass(frozen=True, slots=True)
class PoolSyncHeatPumpCapabilities:
    """Capability profile for a parsed heat-pump model."""

    model_number: str | None
    profile: str
    supports_pool_spa_mode: bool
    supports_separate_spa_setpoint: bool
    supports_heating: bool
    supports_cooling: bool


@dataclass(frozen=True, slots=True)
class PoolSyncAquaCalFeatureProfile:
    """Operational capabilities decoded from the AquaCal feature slot."""

    name: str
    supports_heating: bool
    supports_cooling: bool


@dataclass(frozen=True, slots=True)
class PoolSyncAquaCalControlProfile:
    """Control capabilities decoded from the AquaCal control slot."""

    name: str
    supports_pool_spa_mode: bool
    supports_separate_spa_setpoint: bool


@dataclass(frozen=True, slots=True)
class PoolSyncAquaCalModelProfile:
    """Combined capabilities decoded from AquaCal model nomenclature."""

    profile: str
    supports_pool_spa_mode: bool
    supports_separate_spa_setpoint: bool
    supports_heating: bool
    supports_cooling: bool


@dataclass(frozen=True, slots=True)
class PoolSyncHeatPumpRuntime:
    """Derived runtime state for a parsed heat pump."""

    capabilities: PoolSyncHeatPumpCapabilities
    ctrl_flags_raw: int | None
    state_flags_raw: int | None
    has_flow: bool | None
    compressor_running: bool | None
    fan_running: bool | None
    mode_value: int | None
    pool_spa_mode: int | None
    mode_context: PoolSyncHeatPumpModeContext | None
    pool_setpoint: int | float | None
    spa_setpoint: int | float | None
    active_target_temperature: int | float | None


type PoolSyncEquipmentRole = Literal["equipment"]


@dataclass(frozen=True, slots=True)
class PoolSyncEquipmentData:
    """Parsed view of a single equipment entry from equip[N]."""

    slot_key: str
    equip_type: int
    name: str
    raw: list[Any]

    # --- Type checks ---

    @property
    def is_pump(self) -> bool:
        """Return whether this is a variable-speed pump."""
        return self.equip_type == EQUIP_TYPE_VS_PUMP

    @property
    def is_valve(self) -> bool:
        """Return whether this is a motorized valve."""
        return self.equip_type == EQUIP_TYPE_VALVE

    @property
    def is_heat_pump(self) -> bool:
        """Return whether this is a heat pump equipment entry."""
        return self.equip_type == EQUIP_TYPE_HEAT_PUMP

    @property
    def is_relay(self) -> bool:
        """Return whether this is a generic relay."""
        return self.equip_type == EQUIP_TYPE_RELAY

    @property
    def is_chlorinator(self) -> bool:
        """Return whether this is a chlorinator equipment entry."""
        return self.equip_type == EQUIP_TYPE_CHLORINATOR

    @property
    def is_light(self) -> bool:
        """Return whether this is a light equipment entry."""
        return self.equip_type == EQUIP_TYPE_LIGHT

    # --- Pump properties ---

    @property
    def pump_rpm(self) -> int | None:
        """Current pump RPM (state × 50). None if not a pump or not running."""
        if not self.is_pump:
            return None
        speed = self.get_int(EQUIP_IDX_STATE)
        return speed * PUMP_RPM_FACTOR if speed > 0 else None

    @property
    def pump_is_priming(self) -> bool | None:
        """Whether pump is in priming mode. None if not a pump."""
        if not self.is_pump:
            return None
        return self.get_int(EQUIP_IDX_PARAM_14) != 0

    @property
    def pump_rpm_min(self) -> int | None:
        """Minimum RPM for this pump. None if not a pump."""
        if not self.is_pump:
            return None
        val = self.get_int(EQUIP_IDX_PARAM_8)
        return val * PUMP_RPM_FACTOR if val > 0 else None

    @property
    def pump_rpm_max(self) -> int | None:
        """Maximum RPM for this pump. None if not a pump."""
        if not self.is_pump:
            return None
        val = self.get_int(EQUIP_IDX_PARAM_9)
        return val * PUMP_RPM_FACTOR if val > 0 else None

    # --- Valve properties ---

    @property
    def valve_positions(self) -> list[tuple[str, int]]:
        """Named position pairs from the valve equipment entry."""
        if not self.is_valve:
            return []
        positions: list[tuple[str, int]] = []
        idx = VALVE_IDX_POSITIONS_START
        while idx + 1 < len(self.raw):
            pos_name = self.raw[idx]
            pos_val = self.raw[idx + 1]
            if isinstance(pos_name, str) and isinstance(pos_val, int):
                positions.append((pos_name, pos_val))
            idx += 2
        return positions

    @property
    def valve_position_options(self) -> list[str] | None:
        """Available position names. None if not a valve."""
        if not self.is_valve:
            return None
        options = [name for name, _ in self.valve_positions]
        return options if options else None

    # --- Heat pump properties ---

    @property
    def hp_state(self) -> int | None:
        """Heat pump on/off state. None if not a heat pump."""
        if not self.is_heat_pump:
            return None
        return self.get_int(EQUIP_IDX_STATE)

    # --- Generic helpers ---

    def get_int(self, index: int, default: int = 0) -> int:
        """Safely read an int from a raw array index."""
        if index < len(self.raw):
            value = self.raw[index]
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return default

    def get_str(self, index: int, default: str = "") -> str:
        """Safely read a string from a raw array index."""
        if index < len(self.raw) and isinstance(self.raw[index], str):
            return self.raw[index]
        return default


@dataclass(frozen=True, slots=True)
class PoolSyncEquipmentRuntime:
    """Derived runtime state for all equipment under the heat pump."""

    equipment: dict[str, PoolSyncEquipmentData]
    raw_groups: dict[str, Any] | None

    @property
    def has_equipment(self) -> bool:
        """Return whether any equipment is present."""
        return len(self.equipment) > 0

    @property
    def active_group_names(self) -> list[str]:
        """Return the names of all currently active groups.

        Groups are additive — multiple groups can be active simultaneously.
        The device merges their equipment settings (highest temp, fastest
        RPM, lowest valve position).
        """
        if not isinstance(self.raw_groups, dict):
            return []
        active: list[str] = []
        for _group_key, group_data in self.raw_groups.items():
            if not isinstance(group_data, dict):
                continue
            config = group_data.get("config")
            if not isinstance(config, list) or len(config) <= GROUP_IDX_STATE:
                continue
            active_state = config[GROUP_IDX_STATE]
            if isinstance(active_state, int) and active_state > 0:
                name = config[GROUP_IDX_NAME] if len(config) > GROUP_IDX_NAME else None
                if isinstance(name, str):
                    active.append(name)
        return active

    @property
    def active_group_attributes(self) -> dict[str, Any] | None:
        """Return attributes for the currently active group, or full group dump."""
        if not isinstance(self.raw_groups, dict):
            return None
        result: dict[str, Any] = {}
        for group_key, group_data in self.raw_groups.items():
            if not isinstance(group_data, dict):
                continue
            config = group_data.get("config")
            equip = group_data.get("equip")
            result[group_key] = {
                "config": config,
                "equip": equip,
            }
        return result


def _parse_raw_equipment(
    raw_equip: dict[str, Any] | None,
) -> dict[str, PoolSyncEquipmentData]:
    """Parse device equip dict into typed equipment entries."""
    if not isinstance(raw_equip, dict):
        return {}

    result: dict[str, PoolSyncEquipmentData] = {}
    for slot_key, raw_entry in raw_equip.items():
        if not isinstance(raw_entry, list) or len(raw_entry) < 2:
            continue
        equip_type = raw_entry[0]
        if isinstance(equip_type, bool) or not isinstance(equip_type, int):
            continue
        name = raw_entry[1]
        if not isinstance(name, str):
            continue
        result[slot_key] = PoolSyncEquipmentData(
            slot_key=slot_key,
            equip_type=equip_type,
            name=name,
            raw=raw_entry,
        )
    return result


def get_equipment_runtime(
    parsed_data: PoolSyncParsedData,
) -> PoolSyncEquipmentRuntime | None:
    """Return parsed equipment runtime, or None when no equipment present."""
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or not hp_devices[0].is_present:
        return None

    hp_data = hp_devices[0].data
    raw_equip = hp_data.get("equip") if hp_data else None
    equipment = _parse_raw_equipment(raw_equip)
    if not equipment:
        return None

    raw_groups = hp_data.get("groups") if hp_data else None

    return PoolSyncEquipmentRuntime(
        equipment=equipment,
        raw_groups=raw_groups if isinstance(raw_groups, dict) else None,
    )


def get_pump_rpm(equip_runtime: PoolSyncEquipmentRuntime | None) -> int | None:
    """Return the current pump RPM from the first VS pump found in equipment."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if (rpm := equip.pump_rpm) is not None:
            return rpm
    return None


def get_pump_priming(equip_runtime: PoolSyncEquipmentRuntime | None) -> bool | None:
    """Return whether the first VS pump is in priming mode."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if (priming := equip.pump_is_priming) is not None:
            return priming
    return None


def get_pump_rpm_min(equip_runtime: PoolSyncEquipmentRuntime | None) -> int | None:
    """Return min RPM for the first VS pump."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if (rpm_min := equip.pump_rpm_min) is not None:
            return rpm_min
    return None


def get_pump_rpm_max(equip_runtime: PoolSyncEquipmentRuntime | None) -> int | None:
    """Return max RPM for the first VS pump."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if (rpm_max := equip.pump_rpm_max) is not None:
            return rpm_max
    return None


def get_valve_position_name(
    equip_runtime: PoolSyncEquipmentRuntime | None,
) -> str | None:
    """Return the current valve position name from active groups.

    When multiple groups are active, the first group that sets the valve
    position wins (order is undefined by the device).
    """
    if equip_runtime is None:
        return None
    if not isinstance(equip_runtime.raw_groups, dict):
        return None

    # Find the valve equipment first to get its position mapping
    valve_positions: list[tuple[str, int]] = []
    valve_slot: str | None = None
    for slot_key, equip in equip_runtime.equipment.items():
        if equip.is_valve:
            valve_positions = equip.valve_positions
            valve_slot = slot_key
            break

    if not valve_positions or valve_slot is None:
        return None

    # Scan all active groups for a valve position setting
    for _group_key, group_data in equip_runtime.raw_groups.items():
        if not isinstance(group_data, dict):
            continue
        config = group_data.get("config")
        if not isinstance(config, list) or len(config) <= GROUP_IDX_STATE:
            continue
        if not isinstance(config[GROUP_IDX_STATE], int) or config[GROUP_IDX_STATE] == 0:
            continue

        # This is an active group — check for valve setting
        equip_map = group_data.get("equip")
        if not isinstance(equip_map, dict):
            continue
        valve_setting = equip_map.get(valve_slot)
        if not isinstance(valve_setting, list) or len(valve_setting) < 1:
            continue
        position_value = valve_setting[0]
        if not isinstance(position_value, int):
            continue

        # Map position value through valve's named positions
        for pos_name, pos_val in valve_positions:
            if pos_val == position_value:
                return pos_name
        return str(position_value)

    return None


def get_valve_position_options(
    equip_runtime: PoolSyncEquipmentRuntime | None,
) -> list[str] | None:
    """Return available position names for the first valve."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if (options := equip.valve_position_options) is not None:
            return options
    return None


def get_hp_in_group(equip_runtime: PoolSyncEquipmentRuntime | None) -> bool | None:
    """Return whether the heat pump is enabled by the active group."""
    if equip_runtime is None:
        return None
    hp_equip = equip_runtime.equipment.get("0")
    if hp_equip is None or not hp_equip.is_heat_pump:
        return None
    return hp_equip.hp_state != 0


_AQUACAL_MODEL_NUMBER_PATTERN = re.compile(
    r"^(?P<brand>[A-Z]{0,2})(?P<unit>\d{3,4})"
    r"(?P<voltage>[A-Z])(?P<feature>[A-Z])(?P<control>[A-Z]).+$"
)

_AQUACAL_FEATURE_PROFILES: dict[str, PoolSyncAquaCalFeatureProfile] = {
    "H": PoolSyncAquaCalFeatureProfile(
        name="heat_only", supports_heating=True, supports_cooling=False
    ),
    "R": PoolSyncAquaCalFeatureProfile(
        name="heat_cool", supports_heating=True, supports_cooling=True
    ),
    "C": PoolSyncAquaCalFeatureProfile(
        name="cool_only", supports_heating=False, supports_cooling=True
    ),
}

_AQUACAL_CONTROL_PROFILES: dict[str, PoolSyncAquaCalControlProfile] = {
    "D": PoolSyncAquaCalControlProfile(
        name="digital",
        supports_pool_spa_mode=True,
        supports_separate_spa_setpoint=True,
    ),
    "V": PoolSyncAquaCalControlProfile(
        name="variable_speed",
        supports_pool_spa_mode=True,
        supports_separate_spa_setpoint=True,
    ),
    "A": PoolSyncAquaCalControlProfile(
        name="analog",
        supports_pool_spa_mode=False,
        supports_separate_spa_setpoint=False,
    ),
}


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
    parsed_data: PoolSyncParsedData,
    role_key: str,
    index: int = 0,
) -> PoolSyncDeviceRoleData | None:
    """Return normalized data for a device role at a given index."""
    devices = parsed_data.devices.get(role_key, [])
    if index < len(devices):
        return devices[index]
    return None


def _get_dict_value(section: dict[str, Any] | None, key: str) -> Any:
    """Return a value from a parsed section when available."""
    return section.get(key) if section is not None else None


def _get_int_value(section: dict[str, Any] | None, key: str) -> int | None:
    """Return an integer value from a parsed section when available."""
    value = _get_dict_value(section, key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _get_number_value(section: dict[str, Any] | None, key: str) -> int | float | None:
    """Return a numeric value from a parsed section when available."""
    value = _get_dict_value(section, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _get_first_active_fault_code(section: dict[str, Any] | None) -> int | None:
    """Return the first non-zero fault code from a device payload."""
    faults = _get_dict_value(section, "faults")
    if not isinstance(faults, list):
        return None

    for fault_code in faults:
        if isinstance(fault_code, bool) or not isinstance(fault_code, int):
            continue
        if fault_code != 0:
            return fault_code

    return None


def _get_top_fault_info(
    section: dict[str, Any] | None,
) -> tuple[int, int] | None:
    """Return (code_index, count) for the highest faultCounts entry.

    Returns None when faultCounts is missing, empty, or all-zero.
    """
    counts = _get_dict_value(section, "faultCounts")
    if not isinstance(counts, list) or not counts:
        return None

    top_index = 0
    top_count = 0
    for index, value in enumerate(counts):
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value > top_count:
            top_count = value
            top_index = index

    if top_count == 0:
        return None
    return (top_index, top_count)


# Sentinel values used by different PoolSync models to indicate
# "sensor not present".  Documented values: -40 (090), 0 (T75),
# 127 (SQ160R).
_TEMP_SENTINELS = frozenset({-40, 0, 127})


def _get_temp_value(section: dict[str, Any] | None, key: str) -> int | float | None:
    """Return a temperature value, treating known sentinels as unavailable."""
    value = _get_number_value(section, key)
    if value is not None and value in _TEMP_SENTINELS:
        return None
    return value


def _heat_pump_has_flow(ctrl_flags_raw: int) -> bool:
    """Return whether the heat pump reports active water flow."""
    return ctrl_flags_raw != 0


def _heat_pump_compressor_running(ctrl_flags_raw: int) -> bool:
    """Return whether the heat pump controller has engaged the compressor."""
    return (ctrl_flags_raw & HEAT_PUMP_CTRL_FLAGS_COMPRESSOR) != 0


def _heat_pump_fan_running(ctrl_flags_raw: int) -> bool:
    """Return whether the heat pump controller has engaged the fan."""
    return (ctrl_flags_raw & HEAT_PUMP_CTRL_FLAGS_FAN) != 0


def _resolve_device_types(data: dict[str, Any]) -> dict[str, list[str]]:
    """Resolve all known device types from the deviceType map.

    Returns {role_key: [device_id, ...]} for every registered device type
    found in the API payload. Unknown device types are logged and skipped.
    Device iteration is sorted by numeric key for deterministic ordering.
    """
    result: dict[str, list[str]] = {}

    device_types = data.get("deviceType")
    if not isinstance(device_types, dict):
        return result

    for device_id in sorted(
        device_types,
        key=lambda k: (
            (0, int(k)) if isinstance(k, str) and k.isdigit() else (1, str(k))
        ),
    ):
        api_type = device_types[device_id]
        if not isinstance(api_type, str):
            continue

        info = DEVICE_TYPE_REGISTRY.get(api_type)
        if info is None:
            _LOGGER.debug(
                "Unrecognized PoolSync device type %r at key %s",
                api_type,
                device_id,
            )
            continue

        result.setdefault(info.role_key, []).append(device_id)

    return result


def _extract_node_addr(device_data: dict[str, Any] | None) -> int | None:
    """Extract nodeAddr from a device payload, if present."""
    if device_data is None:
        return None
    node_attr = device_data.get("nodeAttr")
    if isinstance(node_attr, dict):
        addr = node_attr.get("nodeAddr")
        if isinstance(addr, int):
            return addr
    return None


def _resolve_device(
    parsed_data: PoolSyncParsedData,
    role_key: str | None,
    index: int = 0,
) -> PoolSyncDeviceRoleData | None:
    """Resolve a specific device by role key and index."""
    if role_key is None:
        return None
    devices = parsed_data.devices.get(role_key, [])
    if index < len(devices):
        return devices[index]
    return None


def _dv(
    role_key: str, section_attr: str, field: str, index: int = 0
) -> Callable[..., Any]:
    """Return a value getter for a device-scoped field.

    Accepts extra keyword arguments (role_key, index) from the public
    getter functions so it can be called through the standard lookup path.
    When kwargs contain a non-None role_key or non-zero index, those
    override the factory defaults.

    Usage: _dv("chlorinator", "status", "waterTemp")
           _dv("chlorinator", "status", "waterTemp", index=1)
    """

    def _getter(
        parsed_data: PoolSyncParsedData,
        **kwargs: Any,
    ) -> Any:
        effective_role = kwargs.get("role_key") or role_key
        effective_index = kwargs.get("index", 0) or index
        device = _resolve_device(parsed_data, effective_role, effective_index)
        if device is None:
            return None
        return _get_dict_value(getattr(device, section_attr), field)

    return _getter


def _decode_aquacal_model_profile(
    model_number: str | None,
) -> PoolSyncAquaCalModelProfile | None:
    """Return a capability profile decoded from AquaCal model nomenclature."""
    if model_number is None:
        return None

    normalized_model_number = model_number.strip().upper()
    if not (match := _AQUACAL_MODEL_NUMBER_PATTERN.fullmatch(normalized_model_number)):
        return None

    feature_code = match.group("feature")
    control_code = match.group("control")

    if feature_code not in _AQUACAL_FEATURE_PROFILES:
        return None

    if control_code not in _AQUACAL_CONTROL_PROFILES:
        return None

    feature_profile = _AQUACAL_FEATURE_PROFILES[feature_code]
    control_profile = _AQUACAL_CONTROL_PROFILES[control_code]

    return PoolSyncAquaCalModelProfile(
        profile=f"aquacal_{feature_profile.name}_{control_profile.name}",
        supports_pool_spa_mode=control_profile.supports_pool_spa_mode,
        supports_separate_spa_setpoint=(control_profile.supports_separate_spa_setpoint),
        supports_heating=feature_profile.supports_heating,
        supports_cooling=feature_profile.supports_cooling,
    )


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

    device_type_map = _resolve_device_types(data)
    parsed_devices: dict[str, list[PoolSyncDeviceRoleData]] = {}

    for role_key, device_ids in device_type_map.items():
        role_devices: list[PoolSyncDeviceRoleData] = []
        for index, device_id in enumerate(device_ids):
            device_data = (
                cast(dict[str, Any], devices[device_id])
                if device_id in devices and isinstance(devices.get(device_id), dict)
                else None
            )
            node_addr = _extract_node_addr(device_data)

            role_devices.append(
                PoolSyncDeviceRoleData(
                    role=role_key,
                    device_id=device_id,
                    data=device_data,
                    node_addr=node_addr,
                    index=index,
                )
            )
        parsed_devices[role_key] = role_devices

    return PoolSyncParsedData(
        system=PoolSyncSystemData(system_data),
        devices=parsed_devices,
    )


def get_heat_pump_capabilities(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> PoolSyncHeatPumpCapabilities | None:
    """Return the capability profile for the parsed heat pump."""
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or not hp_devices[index].is_present:
        return None

    model_number = _get_dict_value(hp_devices[index].system, "modelNum")
    if not isinstance(model_number, str):
        model_number = None

    config = hp_devices[index].config
    model_profile = _decode_aquacal_model_profile(model_number)

    payload_supports_pool_spa_mode = (
        _get_dict_value(config, "poolSpaMode") is not None
        or _get_dict_value(config, "spaSetpoint") is not None
    )
    payload_supports_separate_spa_setpoint = (
        _get_dict_value(config, "spaSetpoint") is not None
    )

    return PoolSyncHeatPumpCapabilities(
        model_number=model_number,
        profile=(
            model_profile.profile if model_profile is not None else "unknown_heat_pump"
        ),
        supports_pool_spa_mode=(
            model_profile.supports_pool_spa_mode
            if model_profile is not None
            else payload_supports_pool_spa_mode
        ),
        supports_separate_spa_setpoint=(
            model_profile.supports_separate_spa_setpoint
            if model_profile is not None
            else payload_supports_separate_spa_setpoint
        ),
        supports_heating=(
            model_profile.supports_heating if model_profile is not None else True
        ),
        supports_cooling=(
            model_profile.supports_cooling if model_profile is not None else False
        ),
    )


def get_heat_pump_runtime(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> PoolSyncHeatPumpRuntime | None:
    """Return derived runtime state for the parsed heat pump."""
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or not hp_devices[index].is_present:
        return None

    capabilities = get_heat_pump_capabilities(parsed_data, index=index)
    if capabilities is None:
        return None

    hp_status = hp_devices[index].status
    hp_config = hp_devices[index].config
    ctrl_flags_raw = _get_int_value(hp_status, "ctrlFlags")
    state_flags_raw = _get_int_value(hp_status, "stateFlags")
    mode_value = _get_int_value(hp_config, "mode")
    pool_spa_mode = _get_int_value(hp_config, "poolSpaMode")
    pool_setpoint = _get_number_value(hp_config, "setpoint")
    spa_setpoint = _get_number_value(hp_config, "spaSetpoint")

    if mode_value is None:
        mode_context = None
    elif mode_value == HEAT_PUMP_CONFIG_MODE_HEAT:
        if (
            capabilities.supports_pool_spa_mode
            and pool_spa_mode == HEAT_PUMP_POOL_SPA_MODE_SPA
        ):
            mode_context = HEAT_PUMP_MODE_HEAT_SPA
        else:
            mode_context = HEAT_PUMP_MODE_HEAT_POOL
    elif (
        mode_value == HEAT_PUMP_CONFIG_MODE_COOL
        and pool_spa_mode != HEAT_PUMP_POOL_SPA_MODE_SPA
    ):
        mode_context = HEAT_PUMP_MODE_COOL_POOL
    elif (
        mode_value == HEAT_PUMP_CONFIG_MODE_AUTO
        and pool_spa_mode != HEAT_PUMP_POOL_SPA_MODE_SPA
    ):
        mode_context = HEAT_PUMP_MODE_AUTO_POOL
    else:
        mode_context = HEAT_PUMP_MODE_OFF

    if mode_context in {
        HEAT_PUMP_MODE_HEAT_POOL,
        HEAT_PUMP_MODE_COOL_POOL,
        HEAT_PUMP_MODE_AUTO_POOL,
    }:
        active_target_temperature = pool_setpoint
    elif mode_context == HEAT_PUMP_MODE_HEAT_SPA:
        active_target_temperature = spa_setpoint
    else:
        active_target_temperature = None

    return PoolSyncHeatPumpRuntime(
        capabilities=capabilities,
        ctrl_flags_raw=ctrl_flags_raw,
        state_flags_raw=state_flags_raw,
        has_flow=_heat_pump_has_flow(ctrl_flags_raw)
        if ctrl_flags_raw is not None
        else None,
        compressor_running=_heat_pump_compressor_running(ctrl_flags_raw)
        if ctrl_flags_raw is not None
        else None,
        fan_running=_heat_pump_fan_running(ctrl_flags_raw)
        if ctrl_flags_raw is not None
        else None,
        mode_value=mode_value,
        pool_spa_mode=pool_spa_mode,
        mode_context=mode_context,
        pool_setpoint=pool_setpoint,
        spa_setpoint=spa_setpoint,
        active_target_temperature=active_target_temperature,
    )


def get_heat_pump_mode_options(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> list[str]:
    """Return supported heat-pump mode options for the current device."""
    runtime = get_heat_pump_runtime(parsed_data, index=index)
    if runtime is None:
        return []

    options = [HEAT_PUMP_MODE_OFF]

    if runtime.capabilities.supports_heating or runtime.mode_context in {
        HEAT_PUMP_MODE_HEAT_POOL,
        HEAT_PUMP_MODE_HEAT_SPA,
    }:
        options.append(HEAT_PUMP_MODE_HEAT_POOL)

    if runtime.capabilities.supports_cooling or runtime.mode_context in {
        HEAT_PUMP_MODE_COOL_POOL,
        HEAT_PUMP_MODE_AUTO_POOL,
    }:
        options.append(HEAT_PUMP_MODE_COOL_POOL)

    if (
        runtime.capabilities.supports_heating and runtime.capabilities.supports_cooling
    ) or runtime.mode_context == HEAT_PUMP_MODE_AUTO_POOL:
        options.append(HEAT_PUMP_MODE_AUTO_POOL)

    if (
        runtime.capabilities.supports_heating
        and runtime.capabilities.supports_pool_spa_mode
    ):
        options.append(HEAT_PUMP_MODE_HEAT_SPA)

    return options


def get_heat_pump_climate_preset_modes(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> list[PoolSyncHeatPumpClimatePresetMode]:
    """Return the supported climate preset modes for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data, index=index)
    if runtime is None:
        return []

    preset_modes: list[PoolSyncHeatPumpClimatePresetMode] = [HEAT_PUMP_PRESET_POOL]
    if runtime.capabilities.supports_pool_spa_mode:
        preset_modes.append(HEAT_PUMP_PRESET_SPA)
    return preset_modes


def get_heat_pump_climate_preset_mode(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> PoolSyncHeatPumpClimatePresetMode | None:
    """Return the active climate preset mode for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data, index=index)
    if runtime is None:
        return None

    if runtime.mode_context == HEAT_PUMP_MODE_HEAT_SPA:
        return HEAT_PUMP_PRESET_SPA

    if runtime.mode_context in {
        HEAT_PUMP_MODE_HEAT_POOL,
        HEAT_PUMP_MODE_COOL_POOL,
        HEAT_PUMP_MODE_AUTO_POOL,
    }:
        return HEAT_PUMP_PRESET_POOL

    return None


def get_heat_pump_climate_hvac_modes(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> list[PoolSyncHeatPumpClimateHvacMode]:
    """Return the supported climate HVAC modes for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data, index=index)
    if runtime is None:
        return []

    hvac_modes: list[PoolSyncHeatPumpClimateHvacMode] = ["off"]

    if runtime.capabilities.supports_heating or runtime.mode_context in {
        HEAT_PUMP_MODE_HEAT_POOL,
        HEAT_PUMP_MODE_HEAT_SPA,
    }:
        hvac_modes.append("heat")

    if (
        runtime.capabilities.supports_cooling
        or runtime.mode_context == HEAT_PUMP_MODE_COOL_POOL
    ):
        hvac_modes.append("cool")

    if (
        runtime.capabilities.supports_heating and runtime.capabilities.supports_cooling
    ) or runtime.mode_context == HEAT_PUMP_MODE_AUTO_POOL:
        hvac_modes.append("auto")

    return hvac_modes


def get_heat_pump_climate_hvac_mode(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> PoolSyncHeatPumpClimateHvacMode | None:
    """Return the active climate HVAC mode for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data, index=index)
    if runtime is None or runtime.mode_context is None:
        return None

    if runtime.mode_context == HEAT_PUMP_MODE_OFF:
        return "off"
    if runtime.mode_context in {HEAT_PUMP_MODE_HEAT_POOL, HEAT_PUMP_MODE_HEAT_SPA}:
        return "heat"
    if runtime.mode_context == HEAT_PUMP_MODE_COOL_POOL:
        return "cool"
    if runtime.mode_context == HEAT_PUMP_MODE_AUTO_POOL:
        return "auto"

    return None


def get_heat_pump_climate_hvac_action(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> PoolSyncHeatPumpClimateHvacAction | None:
    """Return the active climate HVAC action for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data, index=index)
    if runtime is None or runtime.mode_context is None:
        return None

    if runtime.mode_context == HEAT_PUMP_MODE_OFF:
        return "off"

    if runtime.mode_context in {HEAT_PUMP_MODE_HEAT_POOL, HEAT_PUMP_MODE_HEAT_SPA}:
        return "heating" if runtime.compressor_running else "idle"

    if runtime.mode_context == HEAT_PUMP_MODE_COOL_POOL:
        return "cooling" if runtime.compressor_running else "idle"

    if runtime.mode_context == HEAT_PUMP_MODE_AUTO_POOL:
        if not runtime.compressor_running:
            return "idle"
        if runtime.capabilities.supports_cooling:
            return "cooling"
        return "heating"

    return None


def get_heat_pump_climate_current_temperature(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> int | float | None:
    """Return the current climate temperature for the heat pump."""
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or not hp_devices[index].is_present:
        return None
    return _get_number_value(hp_devices[index].status, "waterTemp")


def get_heat_pump_climate_target_temperature(
    parsed_data: PoolSyncParsedData,
    preset_mode: PoolSyncHeatPumpClimatePresetMode | None = None,
    index: int = 0,
) -> int | float | None:
    """Return the climate target temperature for the active or selected body."""
    runtime = get_heat_pump_runtime(parsed_data, index=index)
    if runtime is None:
        return None

    if runtime.active_target_temperature is not None:
        return runtime.active_target_temperature

    if (
        preset_mode == HEAT_PUMP_PRESET_SPA
        and runtime.capabilities.supports_separate_spa_setpoint
    ):
        return runtime.spa_setpoint

    return runtime.pool_setpoint


def get_wifi_signal_status(
    parsed_data: PoolSyncParsedData,
) -> PoolSyncWifiSignalStatus | None:
    """Return a qualitative Wi-Fi signal status from the controller RSSI."""
    rssi = _get_number_value(parsed_data.system.status, "rssi")

    if rssi is None:
        return None

    if rssi >= WIFI_RSSI_GOOD_MIN:
        return "good"

    if rssi >= WIFI_RSSI_FAIR_MIN:
        return "fair"

    return "poor"


_NUMBER_VALUE_GETTERS: dict[str, Callable[..., Any]] = {
    "chlor_output_control": _dv("chlorinator", "config", "chlorOutput"),
    "chem_ph_setpoint": _dv("chem_sync", "config", "phSetpoint"),
    "chem_orp_setpoint": _dv("chem_sync", "config", "orpSetpoint"),
    "chem_max_daily_feed": _dv("chem_sync", "config", "maxDailyFeed"),
    "temperature_output_control": lambda parsed_data, **kwargs: (
        runtime.active_target_temperature
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "pool_temperature_output_control": lambda parsed_data, **kwargs: (
        runtime.pool_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "spa_temperature_output_control": lambda parsed_data, **kwargs: (
        runtime.spa_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "pump_rpm_control": lambda parsed_data, **kwargs: get_pump_rpm(
        get_equipment_runtime(parsed_data)
    ),
}


_BINARY_SENSOR_VALUE_GETTERS: dict[str, Callable[..., Any]] = {
    "poolsync_online": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.status, "online"
    ),
    "service_mode_active": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.config, "serviceMode"
    ),
    "system_fault": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.data, "faults"
    ),
    "chlorsync_online": _dv("chlorinator", "node_attr", "online"),
    "chlorsync_fault": _dv("chlorinator", "data", "faults"),
    "chem_sync_online": _dv("chem_sync", "node_attr", "online"),
    "chem_sync_fault": _dv("chem_sync", "data", "faults"),
    "chem_sync_flow": _dv("chem_sync", "config", "flowSensorEnable"),
    "heatpump_online": _dv("heat_pump", "node_attr", "online"),
    "heatpump_fault": _dv("heat_pump", "data", "faults"),
    "heatpump_flow": lambda parsed_data, **kwargs: (
        runtime.has_flow
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "heatpump_compressor": lambda parsed_data, **kwargs: (
        runtime.compressor_running
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "heatpump_fan": lambda parsed_data, **kwargs: (
        runtime.fan_running
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "heatpump_ext_ctrl": _dv("heat_pump", "config", "extCtrlMode"),
    "heatpump_in_group": lambda parsed_data, **kwargs: get_hp_in_group(
        get_equipment_runtime(parsed_data)
    ),
    "pump_priming": lambda parsed_data, **kwargs: get_pump_priming(
        get_equipment_runtime(parsed_data)
    ),
}


_SENSOR_VALUE_GETTERS: dict[str, Callable[..., Any]] = {
    "board_temp": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.status, "boardTemp"
    ),
    "wifi_rssi": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.status, "rssi"
    ),
    "wifi_signal_status": lambda parsed_data, **kwargs: get_wifi_signal_status(
        parsed_data
    ),
    "system_datetime": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.status, "dateTime"
    ),
    "firmware_version": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.system, "fwVersion"
    ),
    "hardware_version": lambda parsed_data, **kwargs: _get_dict_value(
        parsed_data.system.system, "hwVersion"
    ),
    # The device-reported upTimeSecs never seemed to reset, even after reboot and
    # full power removal, so we intentionally do not expose it as a sensor.
    "water_temp": _dv("chlorinator", "status", "waterTemp"),
    "salt_ppm": _dv("chlorinator", "status", "saltPPM"),
    "chlor_board_temp": _dv("chlorinator", "status", "boardTemp"),
    "flow_rate": _dv("chlorinator", "status", "flowRate"),
    "chlor_output_setting": _dv("chlorinator", "config", "chlorOutput"),
    "boost_remaining": _dv("chlorinator", "status", "boostRemaining"),
    "cell_fwd_current": _dv("chlorinator", "status", "fwdCurrent"),
    "cell_rev_current": _dv("chlorinator", "status", "revCurrent"),
    "cell_output_voltage": _dv("chlorinator", "status", "outVoltage"),
    "cell_serial_number": _dv("chlorinator", "system", "cellSerialNum"),
    "cell_firmware_version": _dv("chlorinator", "system", "cellFwVersion"),
    "cell_hardware_version": _dv("chlorinator", "system", "cellHwVersion"),
    "cell_rail_voltage": _dv("chlorinator", "status", "cellRailVoltage"),
    "temp_comp_output": _dv("chlorinator", "status", "tempCompOutput"),
    "drv_model_num": _dv("chlorinator", "system", "drvModelNum"),
    "drv_fw_version": _dv("chlorinator", "system", "drvFwVersion"),
    "drv_hw_version": _dv("chlorinator", "system", "drvHwVersion"),
    "chem_ph": _dv("chem_sync", "status", "ph"),
    "chem_orp": _dv("chem_sync", "status", "orp"),
    "chem_board_temp": _dv("chem_sync", "status", "boardTemp"),
    "chem_acid_consumed": _dv("chem_sync", "status", "acidConsumed"),
    "chem_fw_version": _dv("chem_sync", "system", "fwVersion"),
    "chem_hw_version": _dv("chem_sync", "system", "hwVersion"),
    "chem_model_num": _dv("chem_sync", "system", "modelNum"),
    "hp_water_temp": _dv("heat_pump", "status", "waterTemp"),
    "hp_air_temp": _dv("heat_pump", "status", "airTemp"),
    "hp_board_temp": _dv("heat_pump", "status", "boardTemp"),
    "hp_mode": lambda parsed_data, **kwargs: (
        runtime.mode_context
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "hp_setpoint_temp": lambda parsed_data, **kwargs: (
        runtime.active_target_temperature
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "hp_fault_code": lambda parsed_data, **kwargs: _get_first_active_fault_code(
        hp_devices[idx].data
        if (hp_devices := parsed_data.devices.get("heat_pump", []))
        and (idx := kwargs.get("index", 0)) < len(hp_devices)
        else None
    ),
    "hp_pool_setpoint_temp": lambda parsed_data, **kwargs: (
        runtime.pool_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "hp_spa_setpoint_temp": lambda parsed_data, **kwargs: (
        runtime.spa_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data, index=kwargs.get("index", 0)))
        else None
    ),
    "hp_water_temp2": _dv("heat_pump", "status", "waterTemp2"),
    "hp_ds1_temp": _dv("heat_pump", "status", "ds1Temp"),
    "hp_ds2_temp": _dv("heat_pump", "status", "ds2Temp"),
    "hp_top_fault_code": lambda parsed_data, **kwargs: (
        top[0]
        if (
            top := _get_top_fault_info(
                hp_devices[idx].data
                if (hp_devices := parsed_data.devices.get("heat_pump", []))
                and (idx := kwargs.get("index", 0)) < len(hp_devices)
                else None
            )
        )
        else None
    ),
    "hp_top_fault_count": lambda parsed_data, **kwargs: (
        top[1]
        if (
            top := _get_top_fault_info(
                hp_devices[idx].data
                if (hp_devices := parsed_data.devices.get("heat_pump", []))
                and (idx := kwargs.get("index", 0)) < len(hp_devices)
                else None
            )
        )
        else None
    ),
    "pump_rpm": lambda parsed_data, **kwargs: get_pump_rpm(
        get_equipment_runtime(parsed_data)
    ),
    "pump_rpm_min": lambda parsed_data, **kwargs: get_pump_rpm_min(
        get_equipment_runtime(parsed_data)
    ),
    "pump_rpm_max": lambda parsed_data, **kwargs: get_pump_rpm_max(
        get_equipment_runtime(parsed_data)
    ),
    "valve_position": lambda parsed_data, **kwargs: get_valve_position_name(
        get_equipment_runtime(parsed_data)
    ),
    "group_info": lambda parsed_data, **kwargs: (
        ",".join(er.active_group_names)
        if (er := get_equipment_runtime(parsed_data)) and er.active_group_names
        else None
    ),
}


def get_heat_pump_climate_min_temp(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> int | float:
    """Return the device-reported minimum setpoint, or a safe default."""
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or not hp_devices[index].is_present:
        return 40
    min_temp = _get_number_value(hp_devices[index].config, "setpointMin")
    if isinstance(min_temp, (int, float)) and min_temp > 0:
        return min_temp
    return 40


def get_heat_pump_climate_max_temp(
    parsed_data: PoolSyncParsedData,
    index: int = 0,
) -> int | float:
    """Return the device-reported maximum setpoint, or a safe default."""
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or not hp_devices[index].is_present:
        return 104
    max_temp = _get_number_value(hp_devices[index].config, "setpointMax")
    if isinstance(max_temp, (int, float)) and max_temp > 0:
        return max_temp
    return 104


def build_unique_id(
    mac_address: str,
    role: str,
    key: str,
    device_index: int = 0,
    device_node_addr: int | None = None,
) -> str:
    """Build a stable unique ID for a PoolSync entity.

    Preserves backward compatibility by using the simple {mac}_{key}
    format for every first-instance entity (index 0), regardless of
    role. Subsequent instances append role and nodeAddr (or index)
    to avoid collisions.
    """
    if device_index == 0:
        return f"{mac_address}_{key}"
    if device_node_addr is not None:
        return f"{mac_address}_{role}_{device_node_addr}_{key}"
    return f"{mac_address}_{role}_{device_index}_{key}"


def _get_device_raw_value(
    parsed_data: PoolSyncParsedData,
    role_key: str,
    index: int,
    section_attr: str,
    field: str,
) -> Any:
    """Read a field from a specific device's section."""
    device = _resolve_device(parsed_data, role_key, index)
    if device is None:
        return None
    section = getattr(device, section_attr)
    return _get_dict_value(section, field)


def get_number_value(
    parsed_data: PoolSyncParsedData,
    key: str,
    role_key: str | None = None,
    index: int = 0,
) -> Any:
    """Return a number value from parsed runtime data."""
    getter = _NUMBER_VALUE_GETTERS.get(key)
    if getter is None:
        return None
    return getter(parsed_data, role_key=role_key, index=index)


def get_binary_sensor_value(
    parsed_data: PoolSyncParsedData,
    key: str,
    role_key: str | None = None,
    index: int = 0,
) -> Any:
    """Return a binary sensor source value from parsed runtime data."""
    getter = _BINARY_SENSOR_VALUE_GETTERS.get(key)
    if getter is None:
        return None
    return getter(parsed_data, role_key=role_key, index=index)


def get_sensor_value(
    parsed_data: PoolSyncParsedData,
    key: str,
    role_key: str | None = None,
    index: int = 0,
) -> Any:
    """Return a sensor source value from parsed runtime data."""
    getter = _SENSOR_VALUE_GETTERS.get(key)
    if getter is None:
        return None
    return getter(parsed_data, role_key=role_key, index=index)


def get_chem_sync_mode_options() -> list[str]:
    """Return ChemSync system mode options (from APK: OFF, PH_TIMED, PH_PROBE, TOTAL_CONTROL)."""
    return ["off", "ph_timed", "ph_probe", "total_control"]


def get_select_value(
    parsed_data: PoolSyncParsedData,
    key: str,
    *,
    role_key: str | None = None,
    index: int = 0,
) -> Any:
    """Return a select value from parsed runtime data."""
    if key == "chem_sys_mode" and role_key == "chem_sync":
        raw_value = _dv("chem_sync", "config", "sysMode")(
            parsed_data, role_key="chem_sync", index=index
        )
        options = get_chem_sync_mode_options()
        if isinstance(raw_value, int) and 0 <= raw_value < len(options):
            return options[raw_value]
        return None

    if key != "heat_mode":
        return None

    runtime = get_heat_pump_runtime(parsed_data, index=index)
    return runtime.mode_context if runtime is not None else None

"""Runtime parsing helpers for the PoolSync Custom integration."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from homeassistant.exceptions import HomeAssistantError

from .const import (
    CHLORINATOR_ID,
    EQUIP_TYPE_HEAT_PUMP,
    EQUIP_TYPE_VALVE,
    EQUIP_TYPE_VS_PUMP,
    HEATPUMP_ID,
    PUMP_IDX_CURRENT_SPEED,
    PUMP_IDX_PRIMING_FLAG,
    PUMP_RPM_FACTOR,
    VALVE_IDX_POSITIONS_START,
    WIFI_RSSI_FAIR_MIN,
    WIFI_RSSI_GOOD_MIN,
)

type PoolSyncDeviceRole = Literal["chlorinator", "heat_pump"]
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

    @property
    def is_pump(self) -> bool:
        """Return whether this is a variable-speed pump."""
        return self.equip_type == EQUIP_TYPE_VS_PUMP

    @property
    def is_valve(self) -> bool:
        """Return whether this is a motorized valve."""
        return self.equip_type == EQUIP_TYPE_VALVE

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
    def active_group_name(self) -> str | None:
        """Return the name of the currently active group, if any."""
        if not isinstance(self.raw_groups, dict):
            return None
        for _group_key, group_data in self.raw_groups.items():
            if not isinstance(group_data, dict):
                continue
            config = group_data.get("config")
            if not isinstance(config, list) or len(config) < 4:
                continue
            active_state = config[3]
            if isinstance(active_state, int) and active_state > 0:
                name = config[0]
                return name if isinstance(name, str) else None
        return None

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
    if not parsed_data.heat_pump.is_present:
        return None

    raw_equip = (
        parsed_data.heat_pump.data.get("equip") if parsed_data.heat_pump.data else None
    )  # type: ignore[union-attr]
    equipment = _parse_raw_equipment(raw_equip)
    if not equipment:
        return None

    raw_groups = (
        parsed_data.heat_pump.data.get("groups") if parsed_data.heat_pump.data else None
    )  # type: ignore[union-attr]

    return PoolSyncEquipmentRuntime(
        equipment=equipment,
        raw_groups=raw_groups if isinstance(raw_groups, dict) else None,
    )


def get_pump_rpm(equip_runtime: PoolSyncEquipmentRuntime | None) -> int | None:
    """Return the current pump RPM from the first VS pump found in equipment."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if equip.is_pump:
            speed = equip.get_int(PUMP_IDX_CURRENT_SPEED)
            if speed > 0:
                return speed * PUMP_RPM_FACTOR
    return None


def get_pump_priming(equip_runtime: PoolSyncEquipmentRuntime | None) -> bool | None:
    """Return whether the first VS pump is in priming mode."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if equip.is_pump:
            return equip.get_int(PUMP_IDX_PRIMING_FLAG) != 0
    return None


def get_pump_rpm_min(equip_runtime: PoolSyncEquipmentRuntime | None) -> int | None:
    """Return min RPM for the first VS pump."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if equip.is_pump:
            val = equip.get_int(8)
            return val * PUMP_RPM_FACTOR if val > 0 else None
    return None


def get_pump_rpm_max(equip_runtime: PoolSyncEquipmentRuntime | None) -> int | None:
    """Return max RPM for the first VS pump."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if equip.is_pump:
            val = equip.get_int(9)
            return val * PUMP_RPM_FACTOR if val > 0 else None
    return None


def get_valve_position_name(
    equip_runtime: PoolSyncEquipmentRuntime | None,
) -> str | None:
    """Return the current valve position name from the active group."""
    if equip_runtime is None or equip_runtime.active_group_name is None:
        return None
    if not isinstance(equip_runtime.raw_groups, dict):
        return None

    # Find the valve equipment first to get its position mapping
    valve: PoolSyncEquipmentData | None = None
    valve_slot: str | None = None
    for slot_key, equip in equip_runtime.equipment.items():
        if equip.is_valve:
            valve = equip
            valve_slot = slot_key
            break

    if valve is None or valve_slot is None:
        return None

    # Find the active group and read its valve position setting
    for _group_key, group_data in equip_runtime.raw_groups.items():
        if not isinstance(group_data, dict):
            continue
        config = group_data.get("config")
        if not isinstance(config, list) or len(config) < 4:
            continue
        if not isinstance(config[3], int) or config[3] == 0:
            continue

        # This is the active group — read valve position
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
        idx = VALVE_IDX_POSITIONS_START
        while idx + 1 < len(valve.raw):
            pos_name = valve.raw[idx]
            pos_val = valve.raw[idx + 1]
            if isinstance(pos_name, str) and isinstance(pos_val, int):
                if pos_val == position_value:
                    return pos_name
            idx += 2
        return str(position_value)

    return None


def get_valve_position_options(
    equip_runtime: PoolSyncEquipmentRuntime | None,
) -> list[str] | None:
    """Return available position names for the first valve."""
    if equip_runtime is None:
        return None
    for equip in equip_runtime.equipment.values():
        if equip.is_valve:
            options: list[str] = []
            idx = VALVE_IDX_POSITIONS_START
            while idx < len(equip.raw):
                pos_name = equip.raw[idx]
                if isinstance(pos_name, str):
                    options.append(pos_name)
                idx += 2
            return options if options else None
    return None


def get_hp_in_group(equip_runtime: PoolSyncEquipmentRuntime | None) -> bool | None:
    """Return whether the heat pump is enabled by the active group."""
    if equip_runtime is None:
        return None
    hp_equip = equip_runtime.equipment.get("0")
    if hp_equip is None or hp_equip.equip_type != EQUIP_TYPE_HEAT_PUMP:
        return None
    return hp_equip.get_int(7) != 0


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
    parsed_data: PoolSyncParsedData, role: PoolSyncDeviceRole
) -> PoolSyncDeviceRoleData:
    """Return normalized data for a known device role."""
    return parsed_data.chlorinator if role == "chlorinator" else parsed_data.heat_pump


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


def get_heat_pump_capabilities(
    parsed_data: PoolSyncParsedData,
) -> PoolSyncHeatPumpCapabilities | None:
    """Return the capability profile for the parsed heat pump."""
    if not parsed_data.heat_pump.is_present:
        return None

    model_number = _get_dict_value(parsed_data.heat_pump.system, "modelNum")
    if not isinstance(model_number, str):
        model_number = None

    config = parsed_data.heat_pump.config
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
) -> PoolSyncHeatPumpRuntime | None:
    """Return derived runtime state for the parsed heat pump."""
    if not parsed_data.heat_pump.is_present:
        return None

    capabilities = get_heat_pump_capabilities(parsed_data)
    if capabilities is None:
        return None

    ctrl_flags_raw = _get_int_value(parsed_data.heat_pump.status, "ctrlFlags")
    state_flags_raw = _get_int_value(parsed_data.heat_pump.status, "stateFlags")
    mode_value = _get_int_value(parsed_data.heat_pump.config, "mode")
    pool_spa_mode = _get_int_value(parsed_data.heat_pump.config, "poolSpaMode")
    pool_setpoint = _get_number_value(parsed_data.heat_pump.config, "setpoint")
    spa_setpoint = _get_number_value(parsed_data.heat_pump.config, "spaSetpoint")

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


def get_heat_pump_mode_options(parsed_data: PoolSyncParsedData) -> list[str]:
    """Return supported heat-pump mode options for the current device."""
    runtime = get_heat_pump_runtime(parsed_data)
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
) -> list[PoolSyncHeatPumpClimatePresetMode]:
    """Return the supported climate preset modes for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data)
    if runtime is None:
        return []

    preset_modes: list[PoolSyncHeatPumpClimatePresetMode] = [HEAT_PUMP_PRESET_POOL]
    if runtime.capabilities.supports_pool_spa_mode:
        preset_modes.append(HEAT_PUMP_PRESET_SPA)
    return preset_modes


def get_heat_pump_climate_preset_mode(
    parsed_data: PoolSyncParsedData,
) -> PoolSyncHeatPumpClimatePresetMode | None:
    """Return the active climate preset mode for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data)
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
) -> list[PoolSyncHeatPumpClimateHvacMode]:
    """Return the supported climate HVAC modes for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data)
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
) -> PoolSyncHeatPumpClimateHvacMode | None:
    """Return the active climate HVAC mode for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data)
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
) -> PoolSyncHeatPumpClimateHvacAction | None:
    """Return the active climate HVAC action for the heat pump."""
    runtime = get_heat_pump_runtime(parsed_data)
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
            return None
        return "heating"

    return None


def get_heat_pump_climate_current_temperature(
    parsed_data: PoolSyncParsedData,
) -> int | float | None:
    """Return the current climate temperature for the heat pump."""
    return _get_number_value(parsed_data.heat_pump.status, "waterTemp")


def get_heat_pump_climate_target_temperature(
    parsed_data: PoolSyncParsedData,
    preset_mode: PoolSyncHeatPumpClimatePresetMode | None = None,
) -> int | float | None:
    """Return the climate target temperature for the active or selected body."""
    runtime = get_heat_pump_runtime(parsed_data)
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


_NUMBER_VALUE_GETTERS: dict[str, Callable[[PoolSyncParsedData], Any]] = {
    "chlor_output_control": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.config, "chlorOutput"
    ),
    "temperature_output_control": lambda parsed_data: (
        runtime.active_target_temperature
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "pool_temperature_output_control": lambda parsed_data: (
        runtime.pool_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "spa_temperature_output_control": lambda parsed_data: (
        runtime.spa_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "pump_rpm_control": lambda parsed_data: get_pump_rpm(
        get_equipment_runtime(parsed_data)
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
    "heatpump_flow": lambda parsed_data: (
        runtime.has_flow if (runtime := get_heat_pump_runtime(parsed_data)) else None
    ),
    "heatpump_compressor": lambda parsed_data: (
        runtime.compressor_running
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "heatpump_fan": lambda parsed_data: (
        runtime.fan_running if (runtime := get_heat_pump_runtime(parsed_data)) else None
    ),
    "heatpump_ext_ctrl": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.config, "extCtrlMode"
    ),
    "heatpump_in_group": lambda parsed_data: get_hp_in_group(
        get_equipment_runtime(parsed_data)
    ),
    "pump_priming": lambda parsed_data: get_pump_priming(
        get_equipment_runtime(parsed_data)
    ),
}


_SENSOR_VALUE_GETTERS: dict[str, Callable[[PoolSyncParsedData], Any]] = {
    "board_temp": lambda parsed_data: _get_dict_value(
        parsed_data.system.status, "boardTemp"
    ),
    "wifi_rssi": lambda parsed_data: _get_dict_value(parsed_data.system.status, "rssi"),
    "wifi_signal_status": get_wifi_signal_status,
    "system_datetime": lambda parsed_data: _get_dict_value(
        parsed_data.system.status, "dateTime"
    ),
    "firmware_version": lambda parsed_data: _get_dict_value(
        parsed_data.system.system, "fwVersion"
    ),
    "hardware_version": lambda parsed_data: _get_dict_value(
        parsed_data.system.system, "hwVersion"
    ),
    # The device-reported upTimeSecs never seemed to reset, even after reboot and
    # full power removal, so we intentionally do not expose it as a sensor.
    "water_temp": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "waterTemp"
    ),
    "salt_ppm": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "saltPPM"
    ),
    "chlor_board_temp": lambda parsed_data: _get_dict_value(
        parsed_data.chlorinator.status, "boardTemp"
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
    "hp_board_temp": lambda parsed_data: _get_dict_value(
        parsed_data.heat_pump.status, "boardTemp"
    ),
    "hp_mode": lambda parsed_data: (
        runtime.mode_context
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "hp_setpoint_temp": lambda parsed_data: (
        runtime.active_target_temperature
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "hp_fault_code": lambda parsed_data: _get_first_active_fault_code(
        parsed_data.heat_pump.data
    ),
    "hp_pool_setpoint_temp": lambda parsed_data: (
        runtime.pool_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "hp_spa_setpoint_temp": lambda parsed_data: (
        runtime.spa_setpoint
        if (runtime := get_heat_pump_runtime(parsed_data))
        else None
    ),
    "hp_water_temp2": lambda parsed_data: _get_temp_value(
        parsed_data.heat_pump.status, "waterTemp2"
    ),
    "hp_ds1_temp": lambda parsed_data: _get_temp_value(
        parsed_data.heat_pump.status, "ds1Temp"
    ),
    "hp_ds2_temp": lambda parsed_data: _get_temp_value(
        parsed_data.heat_pump.status, "ds2Temp"
    ),
    "hp_top_fault_code": lambda parsed_data: (
        top[0] if (top := _get_top_fault_info(parsed_data.heat_pump.data)) else None
    ),
    "hp_top_fault_count": lambda parsed_data: (
        top[1] if (top := _get_top_fault_info(parsed_data.heat_pump.data)) else None
    ),
    "pump_rpm": lambda parsed_data: get_pump_rpm(get_equipment_runtime(parsed_data)),
    "pump_rpm_min": lambda parsed_data: get_pump_rpm_min(
        get_equipment_runtime(parsed_data)
    ),
    "pump_rpm_max": lambda parsed_data: get_pump_rpm_max(
        get_equipment_runtime(parsed_data)
    ),
    "valve_position": lambda parsed_data: get_valve_position_name(
        get_equipment_runtime(parsed_data)
    ),
    "group_info": lambda parsed_data: (
        er.active_group_name if (er := get_equipment_runtime(parsed_data)) else None
    ),
}


def get_heat_pump_climate_min_temp(
    parsed_data: PoolSyncParsedData,
) -> int | float:
    """Return the device-reported minimum setpoint, or a safe default."""
    min_temp = _get_number_value(parsed_data.heat_pump.config, "setpointMin")
    if isinstance(min_temp, (int, float)) and min_temp > 0:
        return min_temp
    return 40


def get_heat_pump_climate_max_temp(
    parsed_data: PoolSyncParsedData,
) -> int | float:
    """Return the device-reported maximum setpoint, or a safe default."""
    max_temp = _get_number_value(parsed_data.heat_pump.config, "setpointMax")
    if isinstance(max_temp, (int, float)) and max_temp > 0:
        return max_temp
    return 104


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


def get_select_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a select value from parsed runtime data."""
    if key == "heat_mode":
        runtime = get_heat_pump_runtime(parsed_data)
        return runtime.mode_context if runtime is not None else None

    if key == "valve_position":
        return get_valve_position_name(get_equipment_runtime(parsed_data))

    return None

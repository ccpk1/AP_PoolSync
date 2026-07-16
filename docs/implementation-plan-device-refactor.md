# Implementation Plan: Multi-Device Architecture Refactor

> **Status:** Phase 1 ✅ Complete | Phase 2 ✅ Complete | Code review fixes ✅ Complete | Doc updates pending

## Overview

This document describes a phased refactor of the PoolSync integration's device model to support:

- **Phase 1 (Issue #2):** Multiple devices of the same type (e.g., two ChlorSync chlorinators; multiple heat pumps) — **Implemented**
- **Phase 2 (Issue #1):** New device types (e.g., ChemSync pH/ORP) — **Implemented**

The architecture replaces the current hardcoded-role approach with a registration-driven model that is self-documenting, type-safe, and extensible without touching multiple files.

---

## Design Decisions

### Identifier strategy: MAC-based with role/nodeAddr suffix

Entity unique IDs and device registry identifiers are prefixed with the PoolSync controller's **MAC address**, which is the standard HA pattern for hub-based integrations. This is stable for the life of the controller and already captured during push-link pairing before any device-level serial numbers are available. If the controller hardware is replaced, the MAC changes and all IDs shift — this is expected and consistent with how HA handles hub replacement in every other integration.

The suffix uses the **`nodeAddr`** field from the device's `nodeAttr` when available, falling back to a numeric index. `nodeAddr` is a hardware-level identifier assigned by the PoolSync bus and does not change. This is more stable than relying on iteration order or API key names.

### Backward compatibility

The **first instance** of each legacy role (`chlorinator`, `heat_pump`) keeps its existing identifier format (`{mac}_chlorinator`, `{mac}_heat_pump`). Any existing entity registrations, automations, and dashboards continue to work without migration. Second and subsequent instances use the new disambiguated format (`{mac}_chlorinator_19`).

### Multiple heat pumps

The architecture naturally supports multiple heat pumps (e.g., one for the pool, one for the spa) because the data model stores `list[PoolSyncDeviceRoleData]` per role. Each heat pump gets its own device in the registry, its own climate entity, its own select entity, etc. This is an uncommon configuration but costs nothing extra to support.

---

## Phase 1: Multi-Device Architecture

### 1.1 `DeviceTypeInfo` Registry — `runtime.py`

A frozen dataclass and a dict that serve as the single source of truth for every known PoolSync device type.

```python
@dataclass(frozen=True, slots=True)
class DeviceTypeInfo:
    """Metadata for a known PoolSync device type."""

    api_device_type: str          # Value of deviceType key in API response: "chlorSync", "heatPump"
    role_key: str                 # Internal key: "chlorinator", "heat_pump"
    default_name: str             # "ChlorSync", "Heat Pump"
    default_model: str            # "ChlorSync", "Heat Pump"


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
}
```

**Properties:**
- Single dict. Adding a device type is one block, one file.
- `role_key` is the stable internal key used in identifiers, unique IDs, and entity migration.
- `api_device_type` is the exact string from the API response.

### 1.2 `PoolSyncDeviceRoleData` — Add `node_addr` and `index` fields

The `role` field type changes from the restrictive `Literal["chlorinator", "heat_pump"]` to plain `str` so the type doesn't need extension for every new device type.

```python
type PoolSyncDeviceRole = str   # Was: Literal["chlorinator", "heat_pump"]

@dataclass(frozen=True, slots=True)
class PoolSyncDeviceRoleData:
    role: PoolSyncDeviceRole
    device_id: str | None           # The API device key (e.g., "1", "2")
    data: dict[str, Any] | None    # The full device payload
    node_addr: int | None = None   # From nodeAttr.nodeAddr; used for disambiguation
    index: int = 0                 # Ordinal position among same-type devices (0-based)
```

**Why `index`:** Used for friendly-name deduplication only ("ChlorSync 2"). Unique IDs use `nodeAddr` when available, which is more stable.

### 1.3 `PoolSyncParsedData` — Dict-based devices

Replace the three fixed fields with a dict keyed by `role_key`:

```python
@dataclass(frozen=True, slots=True)
class PoolSyncParsedData:
    """Normalized read model for the latest PoolSync payload."""

    system: PoolSyncSystemData
    devices: dict[str, list[PoolSyncDeviceRoleData]]   # {role_key: [dev0, dev1, ...]}
```

The single `chlorinator: PoolSyncDeviceRoleData` field becomes `devices["chlorinator"]: list[...]`.

**Legacy property accessors** (temporary, for minimal diff in other files):

```python
@property
def chlorinator(self) -> PoolSyncDeviceRoleData | None:
    """Return the first chlorinator, for backward compatibility."""
    devices = self.devices.get("chlorinator", [])
    return devices[0] if devices else PoolSyncDeviceRoleData(
        role="chlorinator", device_id=None, data=None
    )

@property
def heat_pump(self) -> PoolSyncDeviceRoleData | None:
    """Return the first heat pump, for backward compatibility."""
    devices = self.devices.get("heat_pump", [])
    return devices[0] if devices else PoolSyncDeviceRoleData(
        role="heat_pump", device_id=None, data=None
    )
```

These are **deleted after Phase 2** when all consumers are migrated to iterate `parsed_data.devices` directly.

### 1.4 `_resolve_device_types()` — Replace `_resolve_device_role_ids()`

```python
def _resolve_device_types(data: dict[str, Any]) -> dict[str, list[str]]:
    """Resolve all known device types from deviceType map.

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
        key=lambda k: int(k) if isinstance(k, str) and k.isdigit() else k,
    ):
        api_type = device_types[device_id]
        if not isinstance(api_type, str):
            continue

        info = DEVICE_TYPE_REGISTRY.get(api_type)
        if info is None:
            _LOGGER.debug("Unrecognized PoolSync device type %r at key %s", api_type, device_id)
            continue

        result.setdefault(info.role_key, []).append(device_id)

    return result
```

**Key behaviors:**
- Iterates **all** entries in `deviceType`, not just the first match per type.
- **Sorted by numeric device ID** so `index` assignment is deterministic across refreshes — a new device pairing won't reshuffle existing devices' indices.
- Unknown types are logged at DEBUG (not silently swallowed).
- Returns `{role_key: [device_id, ...]}` — naturally handles zero, one, or many.
- Idempotent and stateless.

### 1.5 `parse_poolsync_runtime_data()` — Updated

```python
def parse_poolsync_runtime_data(data: dict[str, Any]) -> PoolSyncParsedData:
    raw_devices = data.get("devices")
    devices: dict[str, Any] = (
        cast(dict[str, Any], raw_devices) if isinstance(raw_devices, dict) else {}
    )
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

            role_devices.append(PoolSyncDeviceRoleData(
                role=cast(PoolSyncDeviceRole, role_key),
                device_id=device_id,
                data=device_data,
                node_addr=node_addr,
                index=index,
            ))
        parsed_devices[role_key] = role_devices

    return PoolSyncParsedData(
        system=PoolSyncSystemData(system_data),
        devices=parsed_devices,
    )
```

### 1.6 `_extract_node_addr()` — New helper

```python
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
```

---

### 1.7 `get_role_data()` — Updated for multi-device

```python
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
```

Legacy callers that pass `"chlorinator"` or `"heat_pump"` without an index continue to work, getting device 0.

---

### 1.8 Value getters — Factory function pattern (avoids rewriting 40 lambdas)

Rather than changing the signature of every lambda in `_SENSOR_VALUE_GETTERS`, `_BINARY_SENSOR_VALUE_GETTERS`, and `_NUMBER_VALUE_GETTERS` (40+ entries), we add a **factory function** and a **device resolver** helper. The factory returns a closure that captures `role_key` and `index` at entity-creation time.

```python
def _resolve_device(
    parsed_data: PoolSyncParsedData,
    role_key: str | None,
    index: int = 0,
) -> PoolSyncDeviceRoleData | None:
    """Resolve a specific device by role and index."""
    if role_key is None:
        return None
    devices = parsed_data.devices.get(role_key, [])
    if index < len(devices):
        return devices[index]
    return None


def _dv(
    role_key: str, section_attr: str, field: str, index: int = 0
) -> Callable[[PoolSyncParsedData], Any]:
    """Return a value getter that reads a field from a device role's section.

    Usage: _dv("chlorinator", "status", "waterTemp")
           _dv("chlorinator", "status", "waterTemp", index=1)  # for second unit
    """
    return lambda parsed_data: _get_dict_value(
        getattr(_resolve_device(parsed_data, role_key, index), section_attr),
        field,
    )
```

Then each value-getter dict entry becomes a clean one-liner:

```python
# Before:
"water_temp": lambda parsed_data: _get_dict_value(
    parsed_data.chlorinator.status, "waterTemp"
),

# After:
"water_temp": _dv("chlorinator", "status", "waterTemp"),

# Second chlorinator's entities use a different index at creation time:
"water_temp": _dv("chlorinator", "status", "waterTemp", index=1),
```

**How entities get the right index:** When `async_setup_entry()` in each platform iterates the device list, it passes `device_index` through to the entity constructor. The entity calls `_dv(role_key, section, field, index=self._device_index)` to create its value getter, or more practically, stores `self._device_index` and resolves values at runtime.

`get_sensor_value()` / `get_binary_sensor_value()` / `get_number_value()` no longer need `role_key`/`index` parameters because the factory already baked those into the getter closure at construction time. The public API stays clean:

```python
def get_sensor_value(parsed_data: PoolSyncParsedData, key: str) -> Any:
    """Return a sensor source value from parsed runtime data."""
    getter = _SENSOR_VALUE_GETTERS.get(key)
    return getter(parsed_data) if getter is not None else None
```

**Controller-scoped value getters** (system sensors, Wi-Fi, etc.) don't use the factory and remain unchanged — they read from `parsed_data.system` directly.

---

### 1.9 `coordinator.py` — Generic device info and identifiers

#### `PoolSyncDeviceInfoRole` — Replaced with `str`

The `PoolSyncDeviceInfoRole` literal type is replaced with plain `str` so it doesn't need extension for new device types. The controller is still handled as a special case via `get_device_info()`.

#### `get_role_data()` — Now returns `None` for missing roles

```python
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
```

**Caller audit** (both need null-handling):
1. `coordinator._get_attached_device_info()` — already chains through `if role_data is not None`
2. `coordinator._get_write_role_device_id()` — raises `HomeAssistantError` when role data is missing

#### Identifier generation — Backward-compatible, keyed by nodeAddr

```python
def _get_device_identifier(
    self,
    role_key: str,
    node_addr: int | None = None,
    index: int = 0,
) -> tuple[str, str]:
    """Return a stable device registry identifier.

    Preserves backward compatibility for the first instance of each
    legacy role_key by not appending a suffix. Subsequent instances
    use nodeAddr when available (more stable than index), falling
    back to the numeric index.
    """
    domain = DOMAIN
    if role_key == "chlorinator" and index == 0:
        return (domain, f"{self.mac_address}_chlorinator")   # ← BC path
    if role_key == "heat_pump" and index == 0:
        return (domain, f"{self.mac_address}_heat_pump")     # ← BC path
    if node_addr is not None:
        return (domain, f"{self.mac_address}_{role_key}_{node_addr}")
    return (domain, f"{self.mac_address}_{role_key}_{index}")
```

**Why `nodeAddr` over `index`:** `nodeAddr` is a hardware-level bus identifier assigned by the PoolSync controller. It doesn't change if devices are paired/unpaired. If a chlorinator with `nodeAddr=18` is the second unit today and a third is added at `nodeAddr=22` tomorrow, unit 18 keeps its identifier `{mac}_chlorinator_18`. With a pure-index scheme it would have been `{mac}_chlorinator_1` and would need migration if another device appeared at a lower index.

#### Device name — Deduplication logic

```python
def _unique_device_name(
    self,
    base_name: str,
    role_key: str,
    index: int,
    all_names: list[str],
) -> str:
    """Return a unique friendly name, appending a suffix for duplicates.

    all_names contains the normalized names for every device of this
    role_key, so the suffix count is deterministic.
    """
    if index == 0:
        return base_name
    # Count how many devices share this normalized name (including this one)
    count = sum(1 for name in all_names[:index + 1] if name == base_name)
    if count > 1:
        return f"{base_name} {count}"
    return base_name
```

Place this in `_get_attached_device_info()` which receives the full list of devices for that role. The `_normalize_attached_name` inner function continues to handle vendor-default normalization (e.g. "ChlorSync™" → "ChlorSync").

#### Write paths — Target the right device

The coordinator's write methods (`async_set_chlorinator_output`, etc.) currently target the single chlorinator. They need an optional `index` parameter (defaulting to 0) so that a number entity for the second chlorinator can write to the correct device.

```python
async def async_set_chlorinator_output(self, value: int, index: int = 0) -> None:
    """Set the chlorinator output level."""
    device_id = self._get_write_role_device_id(
        role="chlorinator", index=index, description="chlorinator output"
    )
    ...
```

`_get_write_role_device_id()` similarly gains an `index` parameter and resolves via `get_role_data(parsed_data, role, index=index)`.

#### Heat pump write paths — Same pattern

All heat-pump write methods (`async_set_heat_pump_setpoint`, `async_set_heat_pump_mode`, etc.) also gain an `index` parameter defaulting to 0. This supports multiple heat pumps without code changes to the controllers.

#### `async_set_pump_rpm()` — Direct access updated

Currently uses `parsed_data.heat_pump.device_id`. Updated to `parsed_data.devices["heat_pump"][0].device_id`:

```python
async def async_set_pump_rpm(self, value: int) -> None:
    parsed_data = self.get_parsed_data()
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or hp_devices[0].device_id is None:
        raise HomeAssistantError("Pump write target is not available")
    ...
```

---

### 1.10 Entity platforms — Iterate all devices per role

Each platform's `async_setup_entry()` migrates from:

```python
chlor_id = parsed_data.chlorinator.device_id
if chlor_id and parsed_data.chlorinator.is_present:
    entities.extend(_build_entities(coordinator, DESCRIPTIONS, "chlorinator"))
```

To:

```python
for index, device in enumerate(parsed_data.devices.get("chlorinator", [])):
    if device.is_present:
        entities.extend(
            _build_entities(
                coordinator, DESCRIPTIONS, "chlorinator",
                device_index=index,
            )
        )
```

Entities receive `device_index` and pass it through to their value getter and unique ID.

#### Entity unique IDs — Backward-compatible, keyed by nodeAddr

```python
# In PoolSyncSensor.__init__() and similar entity base classes:
_device_index: int = 0,
_device_node_addr: int | None = None,

self._attr_unique_id = _unique_id or self._build_unique_id(role, description.key, _device_index, _device_node_addr)

def _build_unique_id(self, role: str, key: str, index: int, node_addr: int | None) -> str:
    """Build a stable unique ID, preserving BC for first-instance entities."""
    if role in ("chlorinator", "heat_pump") and index == 0:
        return f"{self.coordinator.mac_address}_{key}"
    if node_addr is not None:
        return f"{self.coordinator.mac_address}_{role}_{node_addr}_{key}"
    return f"{self.coordinator.mac_address}_{role}_{index}_{key}"
```

#### Entity device info — Same pattern

Each entity passes its `device_index` to `coordinator.get_device_info(role_key, index=device_index)`, which resolves the correct device identifier via `_get_device_identifier()`.

---

### 1.11 `__init__.py` — Entity migration

`_ROLE_ENTITY_KEYS` needs to be updated to include the new prefixed unique ID patterns for second-instance entities. The migration function resolves each entity's target device based on unique ID format:

```python
_ROLE_ENTITY_KEYS: dict[str, frozenset[str]] = {
    "chlorinator": frozenset({
        # First-instance keys (BC: no role prefix)
        "water_temp", "salt_ppm", ...,
        # Second-instance keys use {role}_{nodeAddr}_{key} format
        # These are handled by prefix matching, not exact key matching
    }),
    ...
}


def _async_migrate_entity_device_assignments(...) -> None:
    ...
    role_device_ids: dict[str, str] = {}
    for role_key, device_list in parsed_data.devices.items():
        if role_key not in ("chlorinator", "heat_pump"):
            continue
        for index, device in enumerate(device_list):
            # Create each device in the registry
            role_device = device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **coordinator.get_device_info(role_key, index=index),
            )
            role_device_ids[f"{role_key}_{index}"] = role_device.id

    for entity_entry in er.async_entries_for_config_entry(...):
        ...
        # Match entity to device by unique ID pattern
        # {mac}_water_temp → chlorinator_0
        # {mac}_chlorinator_19_water_temp → chlorinator_1 (or whatever index matches nodeAddr 19)
        entity_suffix = entity_entry.unique_id.removeprefix(unique_id_prefix)
        target_key = _resolve_migration_target(entity_suffix, parsed_data)
        if target_key and target_key in role_device_ids:
            ...  # update device assignment
```

A helper `_resolve_migration_target()` parses the entity suffix to determine which role+index it belongs to:

```python
def _resolve_migration_target(
    entity_suffix: str,
    parsed_data: PoolSyncParsedData,
) -> str | None:
    """Map an entity unique ID suffix to a {role}_{index} target.

    Suffix formats:
      "water_temp"           → first chlorinator (index 0)
      "chlorinator_19_water_temp" → chlorinator whose nodeAddr == 19
      "hp_water_temp"        → first heat pump (index 0)
      "heat_pump_42_water_temp" → heat pump whose nodeAddr == 42
    """
    for role_key, device_list in parsed_data.devices.items():
        # Check first-instance format (BC): simple key match
        if entity_suffix in _ROLE_ENTITY_KEYS.get(role_key, frozenset()):
            return f"{role_key}_0"
        # Check second-instance format: {role_key}_{nodeAddr}_{key}
        for index, device in enumerate(device_list):
            if device.node_addr is not None:
                prefix = f"{role_key}_{device.node_addr}_"
                stripped = entity_suffix.removeprefix(prefix)
                if stripped != entity_suffix and stripped in _ROLE_ENTITY_KEYS.get(role_key, frozenset()):
                    return f"{role_key}_{index}"
    return None
```

---

### 1.12 `diagnostics.py` — Update direct `parsed_data.heat_pump` references

Two references need updating:
- `parsed_data.heat_pump.data.get("faults")` → `parsed_data.devices["heat_pump"][0].data.get("faults")`
- The `if parsed_data.heat_pump.data is not None` guard → `if parsed_data.devices.get("heat_pump")`

### 1.13 `runtime.py` — `get_equipment_runtime()` internal references

Uses `parsed_data.heat_pump.data` and `parsed_data.heat_pump.data.get("equip")`. Since equipment data is always associated with a heat pump, update to `parsed_data.devices["heat_pump"][0]`:

```python
def get_equipment_runtime(parsed_data: PoolSyncParsedData) -> PoolSyncEquipmentRuntime | None:
    hp_devices = parsed_data.devices.get("heat_pump", [])
    if not hp_devices or not hp_devices[0].is_present:
        return None

    raw_equip = hp_devices[0].data.get("equip") if hp_devices[0].data else None
    equipment = _parse_raw_equipment(raw_equip)
    if not equipment:
        return None

    raw_groups = hp_devices[0].data.get("groups") if hp_devices[0].data else None
    return PoolSyncEquipmentRuntime(
        equipment=equipment,
        raw_groups=raw_groups if isinstance(raw_groups, dict) else None,
    )
```

All heat-pump-specific runtime functions (`get_heat_pump_runtime`, `get_heat_pump_capabilities`, `get_heat_pump_climate_*`, etc.) follow the same pattern: replace `parsed_data.heat_pump` with `hp_devices[0]` where `hp_devices = parsed_data.devices.get("heat_pump", [])`.

### 1.14 Climate and select platforms — Multiple heat pumps

`climate.py` and `select.py` currently create a single entity. With multiple heat pumps, they create one per detected heat pump device:

```python
# In async_setup_entry():
for index, device in enumerate(parsed_data.devices.get("heat_pump", [])):
    if not device.is_present:
        continue
    entities.append(PoolSyncHeatPumpClimateEntity(
        coordinator, description, device_index=index,
    ))
```

Each climate entity gets its own `device_index` so unique IDs and device info resolve correctly. The same pattern applies to the heat-mode `select` entity.

### 1.15 Number entity — Multi-device support (chlorinator and heat pump)

`NUMBER_DESCRIPTIONS_CHLOR` and `NUMBER_DESCRIPTIONS_HEATPUMP_F` are each a single tuple. For N chlorinators or M heat pumps, N+M number entities are created with the same descriptions but different `device_index`. Each targets a different device on write.

The `PoolSyncChlorOutputNumberEntity` stores `self._device_index` and calls the coordinator with it:

```python
async def async_set_native_value(self, value: float) -> None:
    await self.coordinator.async_set_chlorinator_output(
        int(value), index=self._device_index
    )
```

---

## Phase 2: ChemSync Support

Phase 2 becomes trivial after Phase 1 because the architecture handles both issues.

### 2.1 Register the device type

In `runtime.py`, add one block to `DEVICE_TYPE_REGISTRY`:

```python
"chemSync": DeviceTypeInfo(
    api_device_type="chemSync",
    role_key="chem_sync",
    default_name="ChemSync",
    default_model="ChemSync",
),
```

### 2.2 Add value getters

In `_SENSOR_VALUE_GETTERS`, add entries for pH, ORP, board temp, and acid consumed, each resolving via `_resolve_device(parsed_data, role_key, index)` with `role_key="chem_sync"`.

In `_BINARY_SENSOR_VALUE_GETTERS`, add entries for online, fault, and flow.

In `_NUMBER_VALUE_GETTERS`, add entries for pH setpoint and ORP setpoint (these are optional/write-conditional).

### 2.3 Add entity descriptions

In `sensor.py`:
```python
SENSOR_DESCRIPTIONS_CHEMSYNC: tuple[SensorDescription, ...] = (
    # ph — SensorDeviceClass.PH, no unit
    # orp — unitless mV
    # board_temp — °C, diagnostic
    # acid_consumed — unitless, MEASUREMENT
)
```

In `binary_sensor.py`:
```python
BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC = (
    # online — CONNECTIVITY
    # fault — PROBLEM
    # flow — no device class
)
```

### 2.4 Wire up in `async_setup_entry()` in each platform

Already handled by the Phase 1 iteration pattern — just add the `role_key` to the platform's supported-roles list.

### 2.5 Add translations and icons

- `translations/en.json`: Add `sensor.ph`, `sensor.orp`, `sensor.acid_consumed` names
- `icons.json`: Add `mdi:ph` (pH), `mdi:flash` (ORP), `mdi:flask` (acid consumed)

### 2.6 Remove legacy property accessors from `PoolSyncParsedData`

After migrating all consumers, delete the `.chlorinator` and `.heat_pump` property shims.

---

## Migration Concerns

### Existing users with a single chlorinator

| Concern | Impact |
|---|---|
| Device registry identifier | Unchanged: `{mac}_chlorinator` |
| Entity unique IDs | Unchanged: `{mac}_water_temp` etc. |
| Entity device assignment | Unchanged: migration in `__init__.py` handles it |
| Automation/reference stability | No breakage — nothing changes for single-device users |

### Existing users with a single heat pump

Same analysis — zero impact.

### Users who will benefit from Phase 1

Users with multiple chlorinators (pool + spa) will see the second one appear automatically after the update, with its own device and entities. No manual intervention needed.

---

## File Change Summary

### Phase 1

| File | Nature of change |
|---|---|
| `runtime.py` | `DeviceTypeInfo` dataclass + registry; change `PoolSyncDeviceRole` to `str`; replace `PoolSyncParsedData` fields with dict; replace `_resolve_device_role_ids()` with `_resolve_device_types()` (sorted iteration); add `_extract_node_addr()` helper; add `_resolve_device()` helper; add `_dv()` factory function; update `get_role_data()` with index param and None return; update value getters with `_dv()` factory; add legacy property shims; update `get_equipment_runtime()` internals; update all heat-pump runtime functions |
| `coordinator.py` | `_get_device_identifier()` with BC logic + nodeAddr key; `_unique_device_name()` with dedup; replace `PoolSyncDeviceInfoRole` literal with `str`; write methods gain `index` param; `_get_write_role_device_id()` gains `index`; `_get_attached_device_info()` uses registry for defaults and receives full device list for name dedup; `get_device_info()` gains `index` param; update `async_set_pump_rpm()` |
| `sensor.py` | `_build_sensor_entities()` gains `device_index`; `async_setup_entry()` iterates per-device lists; entity class stores `_device_index` and `_device_node_addr`; unique ID generation with BC |
| `binary_sensor.py` | Same pattern as sensor |
| `number.py` | Same pattern; write path passes `index` to coordinator; both chlorinator and heat pump number entities iterate per-device |
| `climate.py` | Iterate all heat pump devices; create one climate entity per device with `device_index` |
| `select.py` | Iterate all heat pump devices; create one select entity per device with `device_index` |
| `__init__.py` | Update `_ROLE_ENTITY_KEYS`; rewrite `_async_migrate_entity_device_assignments()` with concrete mapping logic for both BC and disambiguated unique ID formats |
| `diagnostics.py` | Update `parsed_data.heat_pump` → `parsed_data.devices["heat_pump"][0]` |
| `const.py` | No changes needed |

### Phase 2

| File | Nature of change |
|---|---|
| `runtime.py` | Add `"chemSync"` to `DEVICE_TYPE_REGISTRY`; add value getters via `_dv()` factory |
| `sensor.py` | Add `SENSOR_DESCRIPTIONS_CHEMSYNC`; add to iteration in `async_setup_entry` |
| `binary_sensor.py` | Add `BINARY_SENSOR_DESCRIPTIONS_CHEMSYNC`; add to iteration |
| `number.py` | Add optional pH/ORP setpoint descriptions; add to iteration |
| `coordinator.py` | No changes — Phase 1 pattern handles it |
| `translations/en.json` | Add new entity names |
| `icons.json` | Add new entity icons |
| `runtime.py` | Remove legacy `PoolSyncParsedData.chlorinator` / `.heat_pump` property shims |

---

## Reverse Engineering Doc Updates

After Phase 1 implementation, update `docs/poolsync-reverse-engineering.md`:

| Section | Update |
|---|---|
| **1.4 (ChlorSync Sensors)** | Add note about multiple chlorinator support: entities are created per detected device, disambiguated by `nodeAddr` in unique IDs |
| **1.5 (ChlorSync Controls)** | Add note about `index` parameter for targeting specific devices on write |
| **2.1 (Device Role Detection)** | Document that `_resolve_device_role_ids()` has been replaced by `_resolve_device_types()` using the `DEVICE_TYPE_REGISTRY`; unknown device types are now logged at DEBUG instead of silently dropped; device iteration is sorted for deterministic ordering |
| **New: Device Architecture** | Add a new section documenting the `DeviceTypeInfo` registry pattern, the dict-based `PoolSyncParsedData`, how device identifiers are generated with backward compatibility (first instance keeps legacy format), the `nodeAddr`-based disambiguation strategy, and the name deduplication logic |
| **New: Multiple Heat Pumps** | Document that heat pump iteration now supports multiple devices, each getting its own climate entity and mode select |
| **Architecture: Unknown Device Types** | Document that unrecognized `deviceType` values are logged at DEBUG and gracefully skipped — forward compatibility with future PoolSync firmware |

## Quality Scale Implications

This refactor directly addresses the `dynamic-devices: todo` rule in `quality_scale.yaml`. After implementation, the rule can be marked `done`:

```yaml
dynamic-devices:
  status: done
  comment: Multiple devices of the same type (e.g., 2× ChlorSync) are now supported via dict-based PoolSyncParsedData.devices with sorted iteration and nodeAddr-based disambiguation.
```

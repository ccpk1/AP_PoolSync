# Implementation Plan: Gold-Level Write Controls (Groups & Pump)

> **Status:** Planning — awaiting approval before implementation

## Overview

Implements the confirmed write payloads (user packet capture, 2026-09-01) for group and pump control, replacing the superseded/incorrect write formats currently in the coordinator. Adds the pump-mode select, duration-aware group switches, a `set_group_state` service, and timing attributes.

**Confirmed write formats (source of truth):**

```json
// Pump — equip.{slot} = [rpm/50, flag]
{"equip": {"1": [36, 4294967295]}}   // manual override to 1800 RPM
{"equip": {"1": [0, 0]}}             // back to auto
{"equip": {"1": [0, 4294967295]}}    // turn pump off

// Groups — groups.{key}.state = [on/off, duration-seconds]
{"groups": {"1": {"state": [1, 21600]}}}   // Waterfall ON, 6h
{"groups": {"1": {"state": [1, 3480]}}}    // Waterfall ON, 58 min
{"groups": {"1": {"state": [0, 0]}}}       // Waterfall OFF
{"groups": {"3": {"state": [1, 28800]}}}   // Ambiance ON, 8h
```

**Design principle:** Groups are **timed scenes** — the app always sends a duration when turning a group on. We therefore **always send a real duration** (the group's configured `timeSet` default) and never `[1, 0]` (indefinite, unproven). Users override the duration via the service.

---

## Entity & Service Naming (Gold Quality)

### Unique ID vs Entity ID (clarified)

| | **Unique ID** (`unique_id`) | **Entity ID** (`entity_id`) |
|---|---|---|---|
| Purpose | Stable internal tracker (never changes) | User-facing identifier (`switch.waterfall`) |
| Visible? | No (entity registry only) | Yes (dashboards, automations) |
| Format | `{mac}_group_{key}`, `{mac}_equip_1_pump_rpm_control` | Derived from device name + entity name; users can rename freely |

All `{mac}_...` values in this plan are **unique IDs** — internal and stable. The display names drive the **entity IDs**, which users can rename anyway.

### Device-attachment model (corrected — semantically grounded)

The device model from the actual diagnostics:

```
devices[0].nodeAttr.name = "Heat Pump"     ← the AquaCal heat pump (pid 9986)
devices[0].equip[1]  = "CIRCULATION PUMP"  ← type 0 (pump)
devices[0].equip[3]  = "RETURN VALVE"      ← type 1 (valve)
devices[0].groups     = POOL, WATERFALL, FILTRATION, AMBIANCE, CLEANER  ← scenes
```

The heat pump device is the **AquaCal unit**. The pump, valve, and groups are *reported under* `devices[0]` only because that's where the API nests them — **not** because they're physically part of the heat pump. The waterfall is a **scene** (pump RPM + valve position combo) orchestrated by the **PoolSync controller**, not a heat-pump feature.

**Therefore:**
- **Pump controls** → attach to the pump's own **equipment device** (`{mac}_equip_1`, "CIRCULATION PUMP") — already the case for `sensor.pump_rpm`, `sensor.valve_position`, `number.pump_rpm_control`.
- **Group/scene controls** → attach to the **controller device** ("PoolSync") — already the case for `sensor.group_info`.
- **Never** attach group entities to the heat pump device ("Heat Pump Waterfall" is semantically wrong).

### Naming conventions (established in codebase)

- `_attr_has_entity_name = True` on all entity classes; display name = **device name + `translation_key` name** from `translations/en.json`.
- `build_unique_id(mac, role, key, ...)`: first instance `{mac}_{key}`, subsequent append role/nodeAddr.
- Equipment device names come from the API (`equip[N][1]`) — normalize to title case ("Circulation Pump", "Return Valve") for gold-quality display.
- Group display names come from the device (`config[0]`: "POOL", "WATERFALL", "AMBIANCE", ...).

### Entities

| Entity | `translation_key` | Display name | Unique ID | Device |
|--------|-------------------|--------------|-----------|--------|
| `select.pump_mode` | `pump_mode` | "Circulation Pump Pump mode" | `{mac}_equip_1_pump_mode` | equipment `{mac}_equip_1` |
| `number.pump_rpm_control` | `pump_rpm_control` | "Circulation Pump Pump RPM" (existing) | `{mac}_equip_1_pump_rpm_control` | equipment `{mac}_equip_1` (already) |
| `switch.group_{key}` | `group` | "PoolSync Waterfall" / "PoolSync Ambiance" / ... | `{mac}_group_{key}` | controller |
| `number.group_{key}_duration` | `group_duration` | "PoolSync Waterfall duration" | `{mac}_group_{key}_duration` | controller |

**Duration number format:** The duration number accepts **minutes** (native unit `min`), with a human-readable input option: users can type values like `1d 10h 22m` (or `90`, `1.5h`, `2h`) which are parsed to minutes. The entity stores/reads minutes; the service accepts seconds (raw API unit) or human-readable strings.
| `sensor.group_info` | `group_info` | "PoolSync Group info" (existing) | `{mac}_group_info` | controller (already) |

**Naming notes:**
- Group switches use `_attr_has_entity_name = True` (fix the current `False` inconsistency). Display reads "PoolSync Waterfall" — the standard HA device+entity pattern, consistent with `sensor.group_info`.
- The duration number reads "PoolSync Waterfall duration" — unambiguous.
- Equipment device names are normalized to title case ("Circulation Pump", "Return Valve") so pump entities read "Circulation Pump Pump mode" instead of "CIRCULATION PUMP Pump mode".
- `translation_key` values are added to `translations/en.json` under `entity.switch.group`, `entity.number.group_duration`, `entity.select.pump_mode`.

### Services

```
poolsync_custom.set_group_state(group, state, duration?)
  group:     group key or display name ("waterfall", "ambiance", ...)
  state:     on | off
  duration:  optional seconds; defaults to the group's configured timeSet

poolsync_custom.set_pump_mode(mode, rpm?)
  mode:  auto | manual | off
  rpm:   required when mode=manual (real RPM, ÷50 internally)
```

---

## Changes by File

### 1. `const.py`
- Add `"switch"` to `PLATFORMS` (**bug fix** — group switches never load today).
- Remove `EQUIP_PUMP_RPM_WRITE_KEY = "rpm"` (**cleanup** — wrong write key).
- Add pump-mode constants: `PUMP_MODE_AUTO`, `PUMP_MODE_MANUAL`, `PUMP_MODE_OFF`.
- Add manual-override sentinel: `PUMP_MANUAL_FLAG = 4294967295` (0xFFFFFFFF, int32 −1).
- Add pump-mode read discriminator: `PUMP_MODE_MANUAL_SENTINEL = 2147483640` (0x7FFFFFF8, seen in `equip[1][5]` when manual).
- Add group config indices: `GROUP_IDX_TIME_SET = 4`, `GROUP_IDX_TIME_LEFT = 5`.

### 2. `runtime.py`
- Add `get_pump_mode(equip_runtime)` → `"auto" | "manual" | "off"`:
  - `manual` if `equip[1][5] == PUMP_MODE_MANUAL_SENTINEL`
  - else `auto` if `equip[1][7] > 0`
  - else `off`
- Add `get_group_duration(equip_runtime, group_key)` → `config[4]` (timeSet).
- Add `get_group_time_left(equip_runtime, group_key)` → `config[5]` (timeLeft).
- Add `get_group_ends_at(equip_runtime, group_key, now)` → UTC timestamp `now + timeLeft`, only when `timeLeft > 0`.
- Register `pump_mode` in `_SELECT_VALUE_GETTERS` (or a new select getter path).
- Register `group_duration` in `_NUMBER_VALUE_GETTERS`.

### 3. `coordinator.py`
- **Fix `async_set_pump_rpm`** → confirmed `equip` format:
  ```python
  {"equip": {slot: [value // PUMP_RPM_FACTOR, PUMP_MANUAL_FLAG]}}
  ```
- **Fix `async_set_group_state`** → confirmed `state` array format:
  ```python
  {"groups": {group_id: {"state": [1 if state else 0, duration]}}}
  ```
  `duration` defaults to the group's `timeSet` when turning on; `0` when off.
- Add `async_set_pump_mode(mode, rpm=None)`:
  - `auto` → `{"equip": {slot: [0, 0]}}`
  - `manual` → `{"equip": {slot: [rpm // PUMP_RPM_FACTOR, PUMP_MANUAL_FLAG]}}`
  - `off` → `{"equip": {slot: [0, PUMP_MANUAL_FLAG]}}`
- Add `async_set_group_duration(group_id, duration, index=0)` → re-sends `state:[1, duration]` (only meaningful while on).

### 4. `__init__.py`
- Register the two services (`set_group_state`, `set_pump_mode`) via `async_register_admin_service` (sensitive — changes device config).
- Add `pump_mode` to `_ROLE_ENTITY_KEYS["equipment"]` (or the equipment whitelist path).
- Add `group_duration` to `_ROLE_ENTITY_KEYS["controller"]` (and `group_{key}` handling for switches).

### 5. `select.py`
- Add `PoolSyncPumpModeSelect` (or extend the existing select class) with `translation_key="pump_mode"`, options `["auto", "manual", "off"]`.
- Attach to the pump's equipment device (`get_equipment_device_info(equip)`), not the heat pump.
- `async_select_option` → `coordinator.async_set_pump_mode(option, rpm=current_rpm)`.
- Read current option via `get_pump_mode()`.

### 6. `switch.py`
- Fix `_attr_has_entity_name` → `True`.
- Attach to the **controller** device (`get_device_info("controller")`), not the heat pump.
- `async_turn_on` → `coordinator.async_set_group_state(key, True)` (uses default duration).
- `async_turn_off` → `coordinator.async_set_group_state(key, False)`.
- Add `duration` and `ends_at` attributes (from `get_group_duration` / `get_group_ends_at`), updating only when shifted >60s.

### 7. `number.py`
- Add `group_duration` number entity per group (`translation_key="group_duration"`, native unit **minutes**).
- Attach to the **controller** device (`get_device_info("controller")`), not the heat pump.
- `async_set_native_value` → `coordinator.async_set_group_duration(key, value)` (converts minutes → seconds).
- Support human-readable duration input (`1d 10h 22m`, `90`, `1.5h`) parsed to minutes via a shared helper.
- Read current value from `config[4]` (timeSet, seconds) converted to minutes.

### 8. `sensor.py`
- `sensor.group_info` `extra_state_attributes`: add decoded `ends_at`/`duration` per active group (currently exposes raw `active_group_attributes`).

### 9. `translations/en.json`
- Add `entity.select.pump_mode.name`, `entity.switch.group.name`, `entity.number.group_duration.name`.

### 10. Tests
- Update `async_set_pump_rpm` / `async_set_group_state` tests to assert the **confirmed** payloads.
- Add tests for `get_pump_mode()` across all 6 diagnostics (auto/manual/off).
- Add tests for `async_set_pump_mode` (auto/manual/off payloads).
- Add tests for group duration + `ends_at` computation (incl.the `timeLeft==0` → no `ends_at` rule).
- Add tests for the two services.
- Add tests for equipment device name normalization ("CIRCULATION PUMP" → "Circulation Pump", "RETURN VALVE" → "Return Valve").

---

## Timing Attributes (anti-noise design)

- `ends_at` = `dt_util.as_utc(now + timedelta(seconds=timeLeft))`, **only when `timeLeft > 0`**.
- Groups with `timeLeft == 0` (e.g. POOL, state=2) run indefinitely → **no `ends_at`**.
- Update the attribute only when the recomputed value differs from the current by **>60s**, so poll jitter never writes to the recorder.
- `duration` = `config[4]` (timeSet), static per activation.

---

## Open Questions

1. **`[1, 0]` (indefinite) behavior** — never sent by design (matches all captures). If the app has a "run forever" option, capture it to confirm.
2. **`timeLeft` decrement** — strongly implied by the 14s-elapsed WATERFALL sample and differing FILTRATION values, but not proven across polls. Two captures ~60s apart would confirm before locking in `ends_at`.
3. **Duration number unit** — **minutes** (native unit `min`), with human-readable input (`1d 10h 22m`) parsed to minutes. Converted to seconds on write. The service accepts seconds (raw API unit) or human-readable strings.
# Implementation Plan: Fault Code Decoding & User-Feedback Mappings

> **Status:** ✅ Implemented (2026-08-20) — all workstreams complete, 228 tests passing, ruff/pylint clean. See "Current Status" below.

## Overview

Four related workstreams, driven by user feedback on Issue #6 (ottoloco-tech, 2026-08-19) and the goal of moving toward Gold-level quality:

1. **Fault code decoding** — surface the raw fault code *and* a human-readable decoded name on the existing fault binary sensors, using the fault tables recovered from the vendor app (v4.73).
2. **Remaining user-feedback mappings** — close the gaps the user reported that are genuinely still missing in 1.0.5 (ChemSync pH min/max + tank threshold, Chlorinator config toggles, controller brightness + connection stats + date/time).
3. **Quality expectations** — codify the existing high-quality patterns (naming, descriptions, diagnostics, units, tests, translations) so every change stays consistent and moves us toward Gold quality scale.
4. **Verification tests** — a concrete test plan (Workstream D) to confirm each item is implemented correctly, following the existing test conventions.

The fault tables are documented in `poolsync-reverse-engineering.md` §0d. Per the agreed guardrail, we treat the vendor app as authoritative and implement against it as-is, adjusting only if a concrete counter-example surfaces.

---

## Current Status (2026-08-20)

All workstreams are **implemented and tested**:

- **Workstream A (fault decoding):** `fault_codes.py` created with `CHLOR_FAULTS` / `CHEM_FAULTS` / `HP_FAULTS` tables and `decode_faults()`. Fault binary sensors expose `fault_code` (raw number) and `active_faults` (decoded names) attributes for **all** device types (ChlorSync, ChemSync, heat pump).
- **Workstream B (user-feedback mappings):** All B1–B7 items implemented as read-only diagnostic sensors (per approved decision). `system_datetime` was already wired. `system_uptime` was removed (unreliable); `display_brightness` reports the raw number (scale unknown).
- **Workstream C (quality patterns):** All new entities follow existing conventions (translation_key, HA constants, DIAGNOSTIC category, disabled-by-default for low-value entities, value getters in runtime.py, `_ROLE_ENTITY_KEYS` updated, diagnostics.py updated).
- **Workstream D (tests):** `test_fault_codes.py` (new), `test_binary_sensor.py`, `test_sensor_setup.py`, `test_diagnostics.py` (extended). Full suite: **228 passing**.
- **Diagnostics:** Added `mapped_binary_sensor_values`, `mapped_number_values`, and `faults_debug` (decoded fault names) sections to the diagnostics download, matching the existing `mapped_sensor_values` pattern.
- **Lint:** ruff clean; pylint clean (no new warnings).

### Decisions applied
1. Heat pump: uses the same `active_faults` decode pattern as ChlorSync/ChemSync (per user correction).
2. All config items read-only (no write until confirmed).
3. pH min/max as separate read-only sensors.
4. Fault labels as plain English in attributes (translations only for entity names).
5. `system_uptime` removed (unreliable — never resets).
6. `display_brightness` reports raw number, no unit (scale unknown).
7. `COMM_CHLOR_FAULTS` removed (dead code — no comm_chlor role).

### Multiple fault codes
- The `faults[]` array is treated as a **bitmask list** — each element is a bitmask, and `decode_faults()` iterates all elements and all set bits.
- **No multi-element fault array has been observed** in any diagnostic sample (all samples show `[0]`, `[4]`, or `[512]` — single-element arrays). The multi-element path is handled defensively but is unverified against real hardware.
- The `fault_code` attribute reports only the **first non-zero** element (matching the existing `hp_fault_code` behavior).

### Review findings (2026-08-20) — resolved

Post-implementation code review identified the following traps/issues, all now resolved:

1. **`system_uptime` removed (✅ resolved).** The existing `runtime.py` has an explicit comment: *"The device-reported upTimeSecs never seemed to reset, even after reboot and full power removal, so we intentionally do not expose it as a sensor."* The `system_uptime` sensor was removed (sensor, getter, translation, test, diagnostics entry) to honor the existing intent.

2. **`display_brightness` unit scale unknown (✅ resolved).** The raw `brightness` value is `4` in both diagnostics, but the scale is unknown. The `PERCENTAGE` unit was removed; the sensor now reports the raw number with no unit until the scale is confirmed.

3. **`COMM_CHLOR_FAULTS` dead code (✅ removed).** The multi-cell comm-unit fault table was defined but not registered in `_FAULT_TABLES` and there is no `comm_chlor` role_key. It was removed as dead code.

4. **`fault_code` vs `active_faults` asymmetry (accepted).** `fault_code` reports only the first non-zero element, while `active_faults` decodes all elements. Consistent for all observed single-element cases; accepted for now.

5. **Heat pump fault decode (✅ enabled).** Per user correction, the heat pump now uses the same pattern as ChlorSync/ChemSync — `active_faults` maps the raw code to names via `HP_FAULTS`. The `heatpump_fault` sensor exposes both `fault_code` and `active_faults`.

---

## Workstream A: Fault Code Decoding

### A1. New module — `fault_codes.py`

A pure data module (no HA dependencies) containing the bit→name tables keyed by device role:

- `CHLOR_FAULTS` — bit 0..13 (cellNotConnected, authFailed, lowTemp, CaBuildup, openCell, overCurrent, sensor, powerFail, underVoltage, highSalt, cleanCell, noFlow, lowSalt, minSalt)
- `CHEM_FAULTS` — bit 0..5 (PCBTemp, pHMin, pHMax, flowSensor, pHProbe, ORPProbe)
- `HP_FAULTS` — heat pump (44 entries)

Each table maps **bit index → internal name → user-facing label** (label derived from the vendor manual display text where it maps cleanly).

### A2. Decode helper

A function `decode_faults(role_key, faults) -> list[str]` that:
- Accepts the raw `faults[]` array from the device payload
- Treats each element as a bitmask (per the app's decode logic)
- Returns the list of user-facing fault labels for every set bit

### A3. Surface on existing fault binary sensors

Extend the existing fault binary sensors (`chlorsync_fault`, `chem_sync_fault`, `heatpump_fault`) to expose an **`active_faults` attribute** — a list of decoded human-readable fault names. Also expose the **raw fault code** as an attribute (e.g. `fault_code`) so users see both the number and the text.

**Why attributes, not new entities:** keeps the entity surface unchanged (no dashboard/automation breakage) while making the fault readable — exactly what the user asked for ("Decoding the fault bitmask into a readable attribute or sensor").

### A3. Translation strings

Add the user-facing fault labels to `translations/en.json` so they render in the user's language.

### A4. Tests

Using the existing diagnostics:
- Beach spa chlor `faults: [512]` → `active_faults` contains "High Salt" (matches its elevated `saltPPM: 5995`)
- Main chem `faults: [4]` → `active_faults` contains "pH Above Max" (matches its `ph: 8.48`)

---

## Workstream B: User-Feedback Mappings

### B1. ChemSync — pH min/max (easy)

- **Gap:** `config.phMin`, `config.phMax` not exposed
- **Source:** `devices[chem_id].config.phMin` / `phMax`
- **Plan:** Add as read-only sensors (or extend the existing `chem_ph_setpoint` number with min/max bounds). Diagnostic, disabled by default.

### B2. ChemSync — acid tank alert threshold (easy)

- **Gap:** `config.acidTankAlertAmount` not exposed
- **Source:** `devices[chem_id].config.acidTankAlertAmount` (640 in main diagnostic)
- **Plan:** Add as a diagnostic sensor (or number entity if writable).

### B3. ChemSync — feed rate (easy to read, hard to unit)

- **Gap:** `config.feedRate` (87662) + `feedRateUnits` (0) not exposed
- **Source:** `devices[chem_id].config.feedRate` / `feedRateUnits`
- **Plan:** Add as a diagnostic sensor showing the raw value. **Unit is unknown** — do not assign a unit until confirmed. (This was previously removed for exactly this reason.)

### B4. Chlorinator — config toggles (easy)

- **Gap:** pool cover control, gallons, polarity change time, ORP input control not exposed
- **Source:** `devices[chlor_id].config.poolCoverCtrl` / `gallons` / `polarityChangeTime` / `orpInputCtrl`
- **Plan:** Add as diagnostic sensors (or switches/numbers if writable). All four are plain values in the existing diagnostic.

### B5. Controller — display brightness (easy)

- **Gap:** `poolSync.config.brightness` not exposed
- **Source:** `poolSync.config.brightness`
- **Plan:** Add as a number entity (per user suggestion).

### B6. Controller — connection stats (easy)

- **Gap:** `poolSync.stats` counters not surfaced
- **Source:** `poolSync.stats.wifiDisconnects` / `awsDisconnects` / `upTimeSecs` / `numPowerups` / `systemRestarts` / `numDeviceOffline`
- **Plan:** Add as diagnostic sensors (TOTAL_INCREASING for counters, MEASUREMENT for uptime).

### B7. Controller — date/time (diagnostic, disabled by default)

- **Gap:** the controller's reported date/time is not surfaced as a timestamp entity
- **Source:** `poolSync.status.dateTime` (string, e.g. `"Sat Aug 20 12:34:56 2026"`)
- **Plan:** Add a `system_datetime` sensor with `device_class=TIMESTAMP`, `entity_category=DIAGNOSTIC`, and **`entity_registry_enabled_default=False`**.
- **Rationale:** A timestamp sensor changes on every poll and would otherwise flood the HA recorder with low-value state changes. Disabling it by default keeps the recorder clean while still making the value available to users who explicitly enable it.
- **Note:** A `system_datetime` sensor already exists in `SENSOR_DESCRIPTIONS_POOLSYNC` (with `_parse_poolsync_datetime` as its value function). Verify it is fully wired through `runtime.py` (`system_datetime` → `poolSync.status.dateTime`) and `__init__.py` before treating this as new work — it may already be complete.

---

## Workstream C: Quality Expectations & Patterns (Gold-Level Direction)

> **Target:** We are not yet at Gold quality scale, but every change should move us toward it. The patterns below are the **existing conventions** in this integration — new code must follow them so the codebase stays consistent, readable, and maintainable.

### C1. Entity naming & identity

- **`_attr_has_entity_name = True`** on every entity class — the entity name is the device name + translation key; never embed the device name in the entity name.
- **`translation_key`** on every `EntityDescription` — never hardcode display strings in code. All user-facing text lives in `translations/en.json`.
- **Stable unique IDs** via the shared `build_unique_id(mac, role, key, device_index, device_node_addr)` helper. First instance of a legacy role keeps its backward-compatible ID; subsequent instances append `nodeAddr`.
- **Device info** via `coordinator.get_device_info(role, index=...)` / `_build_device_info(...)`, with `via_device` pointing at the controller. Never construct `DeviceInfo` inline in entity classes.

### C2. Description-driven entity definitions

- Every platform (`sensor.py`, `binary_sensor.py`, `number.py`, `select.py`, `switch.py`, `button.py`) defines a **`*_DESCRIPTIONS_*` tuple of `(EntityDescription, value_fn)`** pairs.
- The `value_fn` is a pure callable that maps a raw API value → entity value (or `None` to mark unavailable). Keep parsing logic in `runtime.py` value getters; keep the description tuple declarative.
- **`PARALLEL_UPDATES = 0`** at the top of every platform module (coordinator-based updates).

### C3. Diagnostic vs. primary entities

- **Diagnostic entities** (firmware, hardware, serial, board temp, connection stats, date/time) use `entity_category=EntityCategory.DIAGNOSTIC`.
- **Diagnostic entities that change frequently or are low-value** (date/time, counters) additionally use **`entity_registry_enabled_default=False`** so they don't flood the recorder or clutter the UI. Users opt in explicitly.
- **Primary entities** (water temp, pH, ORP, salt, output, fault) use `entity_registry_enabled_default=True`.

### C4. Units, device classes, state classes

- Use HA **constants** (`UnitOfTemperature`, `UnitOfElectricCurrent`, `SensorDeviceClass`, `SensorStateClass`, `EntityCategory`) — never raw strings.
- **`native_unit_of_measurement`** is the device's native unit (e.g. °F for water temp); HA converts to the user's preferred unit automatically. Never report a converted value as native.
- **`state_class`**: `MEASUREMENT` for instantaneous readings, `TOTAL_INCREASING` for monotonic counters (connection stats, fault counts).
- **`suggested_display_precision`** for floats (e.g. `1` for temps, `2` for pH).
- **`device_class`** set where a standard class exists (`TEMPERATURE`, `PH`, `CURRENT`, `VOLTAGE`, `SIGNAL_STRENGTH`, `TIMESTAMP`, `CONNECTIVITY`, `PROBLEM`).

### C5. Value getters & parsing in `runtime.py`

- All raw API access goes through **value getters** in `runtime.py` (e.g. `get_sensor_value`, `get_binary_sensor_value`, `get_number_value`), keyed by entity key and role.
- Parsing helpers (e.g. `_parse_poolsync_datetime`, `_get_first_active_fault_code`) live in `runtime.py` or the platform module, are pure, and return `None` on malformed input (→ entity unavailable).
- The `fault_codes.py` decode helper must follow this pattern: pure function, returns `None`/empty on invalid input, no HA imports.

### C6. Write paths (numbers, selects, switches, buttons)

- Write entities map to coordinator methods via a `_WRITE_METHODS` dict (see `number.py`).
- Coordinator write methods (`async_set_*`) validate input, call the API, and raise `HomeAssistantError` on failure — never silently swallow errors.
- Multi-device writes accept an `index` param and target the correct device via `_get_write_role_device_id`.

### C7. Coordinator & data flow

- Single `PoolSyncDataUpdateCoordinator` per config entry; all entities are `CoordinatorEntity` subclasses.
- `_handle_coordinator_update` calls `ensure_parsed_data(self.coordinator, refresh=True)` then re-reads values.
- `extra_state_attributes` is used sparingly for support-focused data (e.g. `rssi_dbm` on wifi status, `active_faults` on fault sensors) — not for duplicating entity state.

### C8. Tests

- Every new entity/attribute gets a test using the existing `tests/sample_diagnostics/*.json` fixtures.
- Tests assert: entity is created with the right unique ID, correct `device_class`/`unit`/`state_class`, correct value from the fixture, and correct `entity_registry_enabled_default`.
- Use `pytest.mark.parametrize` to merge similar cases; use syrupy snapshots where output is repetitive.
- All test function parameters are type-annotated; prefer concrete types over `Any`.

### C9. Translations & docs

- Every new `translation_key` is added to `translations/en.json` (and `strings.json`), then regenerated via `script.translations develop --integration poolsync_custom`.
- Reverse-engineering findings are documented in `docs/poolsync-reverse-engineering.md`; implementation plans in `docs/implementation-plan-*.md`.

---

## Workstream D: Verification Tests

> **Goal:** Confirm each workstream item is implemented correctly. Tests follow the existing conventions in `tests/components/poolsync_custom/` (see C8): fixtures from `tests/sample_diagnostics/*.json`, `pytest.mark.parametrize` to merge similar cases, syrupy snapshots for repetitive output, and fully type-annotated test functions.

### D1. Fault decode unit tests — `test_fault_codes.py` (new)

Directly test the `fault_codes.py` decode helper against known bitmasks:

| Input | Expected decoded faults |
|-------|------------------------|
| `faults=[512]` (chlor) | `["High Salt"]` |
| `faults=[4]` (chem) | `["pH Above Max"]` |
| `faults=[0]` (any) | `[]` (no active faults) |
| `faults=[]` (any) | `[]` |
| `faults=[1]` (chlor) | `["Cell Not Connected"]` |
| `faults=[2]` (chem) | `["pH Above Max"]` (bit 1 = pHMax) |
| malformed (non-list / non-int) | `[]` (no crash) |

Also test the **raw fault code** extraction (first non-zero element) and that the label mapping covers every bit in each table (no unmapped bit silently dropped).

### D2. Fault attribute tests — `test_binary_sensor.py` (extend)

Verify the fault binary sensors expose the new attributes:

- `chlorsync_fault` with `faults=[512]` → `is_on=True`, `extra_state_attributes["fault_code"] == 512`, `extra_state_attributes["active_faults"] == ["High Salt"]`
- `chem_sync_fault` with `faults=[4]` → `is_on=True`, `active_faults == ["pH Above Max"]`
- `chlorsync_fault` with `faults=[0]` → `is_on=False`, `active_faults == []`
- `heatpump_fault` with `faults=[8, 0]` → `is_on=True`, `fault_code == 8` (first non-zero)

Use the existing `_build_coordinator()` helper and the `_load_runtime_data()` fixture loader already in the file.

### D3. New entity tests — `test_sensor_setup.py` / `test_number_setup.py` (extend)

For each new entity added in Workstream B, assert:

- **Entity is created** with the correct unique ID (via `build_unique_id` pattern)
- **Correct `device_class` / `unit` / `state_class`** (e.g. `system_datetime` → `TIMESTAMP`, diagnostic; connection counters → `TOTAL_INCREASING`)
- **Correct `entity_registry_enabled_default`** (diagnostic/low-value entities → `False`)
- **Correct value** from the fixture (e.g. `system_datetime` parses `"Sat Aug 20 12:34:56 2026"` → timezone-aware `datetime`)

### D4. End-to-end setup tests

For each new entity, add a setup test that runs `async_setup_entry` with a coordinator built from a real diagnostic fixture and asserts the entity appears in `added_entities` with the right attributes. This mirrors the existing `test_async_setup_entry_uses_detected_device_ids` pattern.

### D5. Regression / snapshot tests

- Run the full existing suite (`uv run pytest tests/components/poolsync_custom/`) to confirm no regressions.
- Where a new entity produces repetitive output, add a syrupy `.ambr` snapshot rather than hand-writing expected values.
- Confirm the `system_datetime` sensor (B7) — if already wired, add a test asserting it is `TIMESTAMP` + diagnostic + disabled-by-default; if not wired, the test drives the wiring work.

### D6. Quality-scale checks

- **Ruff / pylint / prek** pass on all changed files (`uv run prek run --all-files`).
- No hardcoded strings in entity code (all via `translation_key`).
- No raw unit strings (all via HA constants).
- Every new entity has a corresponding `translations/en.json` entry and a test.

---

## Out of Scope / Deferred

- **Water temp unit mislabel** — already fixed in 1.0.5 (commit `73fcc8f`); no action needed. The user's report is a repeat of an earlier finding.
- **Packet captures for write-side controls** — user cannot install a MITM cert on the property network; not a viable path.
- **Exhaustive fault-code validation** — not realistic (would require units exhibiting every fault code); we implement against the app tables and adjust on counter-example only.

---

## Open Questions

1. **Multiple simultaneous faults** — can `faults[]` hold more than one code, or is it always length-1? **No multi-element fault array has been observed in any diagnostic sample** (all show `[0]`, `[4]`, or `[512]`). The decode handles a list defensively, but the multi-element path is unverified against real hardware. The `fault_code` attribute reports only the first non-zero element.
2. **Heat pump numeric→name mapping** — the 44-entry `HP_FAULTS` table is now used for `active_faults` decoding (same pattern as ChlorSync/ChemSync). The mapping is inferred from the app's object order and is unverified against real hardware; adjust on counter-example only.
3. **Writability** — for the config items in B2/B4/B5, are they writable via the existing `PATCH ?cmd=devices&device={id}` → `config.{key}` pattern? Per approved decision, these are currently **read-only** diagnostic sensors; write controls can be added once writability is confirmed.
4. **Display brightness scale** — the raw `brightness` value is `4` in both diagnostics, but the scale (0–10 vs 0–100) is unknown. The sensor currently reports the raw number with no unit until the scale is confirmed.
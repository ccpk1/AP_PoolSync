# PoolSync Reverse Engineering

Reference document tracking what we know, what we've built, and what we suspect. Each section cites the specific diagnostic payloads or code paths that back the claim.

---

## 1. Implemented: Device Pairing & System Sensors

All of these are built and tested. Data source for each is noted.

### 1.1 Push-Link Pairing (Discovery → Config Entry)

| Step | Endpoint | Key Data | Reference |
|------|----------|----------|-----------|
| Start push-link | `GET /api/poolsync?cmd=pushLink&start` | `status: "ok"` on success | `api.py:start_pushlink()` |
| Poll for button press | `GET /api/poolsync?cmd=pushLink&status` | `timeRemaining` (seconds), `password` (once pressed) | `config_flow.py:_async_poll_pushlink()` |
| Timeout | — | 120 s max; poll every 5 s | `const.py:PUSHLINK_*` |

Once the user presses the physical button, the API returns the device `password` which is stored in the config entry. The `macAddress` from the full data payload (`GET /api/poolsync?cmd=poolSync&all`) is used as the unique ID.

### 1.2 Controller-Level Sensors (`role="controller"`)

All sourced from `data.poolSync.*` in the all-data response.

| Sensor Key | Source Path | Notes |
|------------|-------------|-------|
| `board_temp` | `poolSync.status.boardTemp` | °C, diagnostic |
| `wifi_rssi` | `poolSync.status.rssi` | dBm |
| `wifi_signal_status` | Derived from `rssi` | "good" ≥ −75, "fair" ≥ −80, else "poor" |
| `system_datetime` | `poolSync.status.dateTime` | Parsed to UTC timestamp |
| `firmware_version` | `poolSync.system.fwVersion` | e.g. 856 |
| `hardware_version` | `poolSync.system.hwVersion` | e.g. "3.0" |

### 1.3 Controller-Level Binary Sensors

| Sensor Key | Source Path | Logic |
|------------|-------------|-------|
| `poolsync_online` | `poolSync.status.online` | Bool |
| `service_mode_active` | `poolSync.config.serviceMode` | Non-zero → true |
| `system_fault` | `poolSync.faults` | Non-zero → true |

### 1.4 ChlorSync Sensors (if device role detected via `deviceType`)

| Sensor Key | Source Path | Unit |
|------------|-------------|------|
| `water_temp` | `devices[chlor_id].status.waterTemp` | °F |
| `salt_ppm` | `devices[chlor_id].status.saltPPM` | PPM |
| `chlor_board_temp` | `devices[chlor_id].status.boardTemp` | °F |
| `flow_rate` | `devices[chlor_id].status.flowRate` | raw |
| `chlor_output_setting` | `devices[chlor_id].config.chlorOutput` | % |
| `boost_remaining` | `devices[chlor_id].status.boostRemaining` | raw |
| `cell_fwd_current` | `devices[chlor_id].status.fwdCurrent` | mA |
| `cell_rev_current` | `devices[chlor_id].status.revCurrent` | mA |
| `cell_output_voltage` | `devices[chlor_id].status.outVoltage` | mV |
| `cell_serial_number` | `devices[chlor_id].system.cellSerialNum` | — |
| `cell_firmware_version` | `devices[chlor_id].system.cellFwVersion` | — |
| `cell_hardware_version` | `devices[chlor_id].system.cellHwVersion` | — |

### 1.5 ChlorSync Controls

| Control | Key | Write Path |
|---------|-----|------------|
| Output % | `chlor_output_control` | `PATCH /api/poolsync?cmd=devices&device={id}` → `config.chlorOutput` |

---

## 2. Implemented: Heat Pump Control

### 2.1 Device Role Detection

`deviceType` map in the all-data response resolves device IDs to roles:
```json
"deviceType": {"0": "heatPump", "1": "chlorSync"}
```
(See `runtime.py:_resolve_device_role_ids()` — T75 and SQ160R samples confirm `"heatPump"` string; 090 samples show mixed-case `"heatPump"`.)

### 2.2 AquaCal Model Decoding (Capability Detection)

Model number format (e.g. `090AHDSBPH`) is parsed with regex:
```
^(?P<brand>[A-Z]{0,2})(?P<unit>\d{3,4})(?P<voltage>[A-Z])(?P<feature>[A-Z])(?P<control>[A-Z]).+$
```

| Code | Slot | Meaning |
|------|------|---------|
| H | Feature | Heat only |
| R | Feature | Heat + Cool (reversible) |
| C | Feature | Cool only |
| D | Control | Digital (pool/spa + separate setpoints) |
| V | Control | Variable speed (pool/spa + separate setpoints) |
| A | Control | Analog (no pool/spa mode) |

**Sample evidence:**
- `090AHDSBPH` → `aquacal_heat_only_digital` (heating, pool/spa, separate setpoints) — **confirmed**, mode=1 is heat, poolSpaMode exists, spaSetpoint exists
- `T75AHDSBPH` → same profile — confirmed via t75-heat-spa.json

When model decode fails, fall back to checking whether `poolSpaMode` and `spaSetpoint` keys exist in the config payload.

### 2.3 Heat Pump Mode Mapping

**Source: `devices[hp_id].config.mode`**

| Raw `mode` | `poolSpaMode` | `mode_context` | HVAC Mode | Notes |
|------------|---------------|----------------|-----------|-------|
| 0 | any | `off` | OFF | |
| 1 | 0 | `heat_pool` | HEAT | |
| 1 | 1 | `heat_spa` | HEAT | SPA preset |
| 2 | 0 | `cool_pool` | COOL | Only if cooling capable |
| 3 | 0 | `auto_pool` | AUTO | Only if heat+cool capable |

### 2.4 Heat Pump Runtime State (from `ctrlFlags` bitmask)

**Source: `devices[hp_id].status.ctrlFlags`**

| Bit | Mask | Meaning | Entity |
|-----|------|---------|--------|
| 2 | 4 | Compressor engaged | `binary_sensor.heatpump_compressor` |
| 3 | 8 | Fan running | `binary_sensor.heatpump_fan` |

`has_flow` = `ctrlFlags != 0` (any non-zero ctrlFlags means the controller sees water flow).

**Sample evidence:**
- t75-heatpump-fault.json: `ctrlFlags=1`, fan bit=0 → fan off (old logic said fan on; bitmask fix confirmed)
- t75-spa-startup: `ctrlFlags=520` → bits 3 (fan) and 9 set → fan on, compressor off ✓
- 090 compressor on: `ctrlFlags=909` → bits 0,2,3,7,9 set → flow + compressor + fan ✓

### 2.5 Heat Pump Sensors

| Sensor Key | Source Path | Notes |
|------------|-------------|-------|
| `hp_water_temp` | `devices[hp_id].status.waterTemp` | °F |
| `hp_water_temp2` | `devices[hp_id].status.waterTemp2` | °F, outlet/secondary water temp; diagnostic, disabled by default; unavailable when sentinel (-40, 0, 127) |
| `hp_air_temp` | `devices[hp_id].status.airTemp` | °F |
| `hp_board_temp` | `devices[hp_id].status.boardTemp` | °F |
| `hp_ds1_temp` | `devices[hp_id].status.ds1Temp` | °F, defrost sensor 1 (suction/vapor line); diagnostic, disabled by default; unavailable when sentinel |
| `hp_ds2_temp` | `devices[hp_id].status.ds2Temp` | °F, defrost sensor 2 (liquid line); diagnostic, disabled by default; unavailable when sentinel |
| `hp_mode` | Derived from `mode` + `poolSpaMode` | e.g. "heat_pool" |
| `hp_setpoint_temp` | Derived active target | Pool or spa setpoint depending on mode |
| `hp_pool_setpoint_temp` | `devices[hp_id].config.setpoint` | °F |
| `hp_spa_setpoint_temp` | `devices[hp_id].config.spaSetpoint` | °F |
| `hp_fault_code` | `devices[hp_id].faults[]` | First non-zero value |
| `hp_top_fault_code` | `devices[hp_id].faultCounts[]` | Index of most frequent fault; diagnostic, disabled by default |
| `hp_top_fault_count` | `devices[hp_id].faultCounts[]` | Count for most frequent fault; diagnostic, disabled by default; TOTAL_INCREASING |

### 2.6 Heat Pump Binary Sensors (beyond those in 2.4)

| Sensor Key | Source Path | Notes |
|------------|-------------|-------|
| `heatpump_online` | `devices[hp_id].nodeAttr.online` | Connectivity |
| `heatpump_fault` | `devices[hp_id].faults[]` | Any non-zero → problem |
| `heatpump_ext_ctrl` | `devices[hp_id].config.extCtrlMode` | Non-zero → remote control active |

### 2.7 Heat Pump Controls (Write Paths)

| Control | Write Key | API Call |
|---------|-----------|----------|
| Mode select | `mode` | `PATCH /api/poolsync?cmd=devices&device={hp_id}` → `config.mode` |
| Pool setpoint | `setpoint` | Same endpoint → `config.setpoint` |
| Spa setpoint | `spaSetpoint` | Same endpoint → `config.spaSetpoint` |
| Active target (number entity) | `setpoint` or `spaSetpoint` | Resolved based on current preset mode |

Climate entity min/max temperature limits are read from `devices[hp_id].config.setpointMin` and `setpointMax`, falling back to 40°F / 104°F when the device reports zero (T75). Previously hardcoded.

### 2.8 Climate Entity

`climate.water_thermostat` wraps the above into a standard HA climate entity:
- **HVAC modes**: off, heat (always), cool (if capable), auto (if heat+cool capable)
- **Preset modes**: pool (default), spa (if pool/spa capable)
- **Current temp**: `waterTemp` from heat pump status
- **Target temp**: active setpoint based on mode+preset
- **HVAC action**: heating/cooling/idle/off derived from mode_context + compressor_running

---

## 3. New Findings from 090 System (Unconfirmed)

These are derived from the three 090 diagnostic samples:
- `090-compressor-off-filtration-group-1750rpm.json`
- `090-compressor-off-priming-filtration-group-3450rpm.json`
- `090-compressor-on-2900rpm-pool-group.json`

All three are from the same system (MAC `C4DEE2532158`) with heat pump model `090AHDSBPH`.

T75 and SQ160R samples have all-null `equip`/`groups`/`schedules` — these structures only appear when additional equipment is connected.

---

### 🔴 HIGH CONFIDENCE — Consistent across all 3 samples

#### F1. Variable Speed Pump (equipment type 0)

**Source:** `devices[0].equip["1"]`

```
[0, "CIRCULATION PUMP", 2, 1, 0, 0, 0, curRPM, minRPM, maxRPM, defMax, startRPM, stopRPM, 0, priming]
```

| Index | Field | 1750 RPM | 3450 RPM (priming) | 2900 RPM | Unit |
|-------|-------|----------|---------------------|----------|------|
| 7 | Current RPM | 35 | 69 | 58 | ×50 = real RPM |
| 8 | Min RPM | 12 | 12 | 12 | 600 real RPM |
| 9 | Max RPM | 69 | 69 | 69 | 3450 real RPM |
| 10 | Default max | 69 | 69 | 69 | 3450 real RPM |
| 11 | Start RPM | 5 | 5 | 5 | 250 real RPM |
| 12 | Stop RPM | 58 | 58 | 58 | 2900 real RPM |
| 14 | Priming flag | 0 | 1 | 0 | bool |

**RPM factor confirmed as ×50:** 35→1750, 58→2900, 69→3450 — all three match the filenames from the user.

**Proposed entities:** `sensor` for current pump RPM, `binary_sensor` for priming, `number` for RPM control.

#### F2. Motorized Return Valve (equipment type 1)

**Source:** `devices[0].equip["3"]`

```
[1, "RETURN VALVE", 1, 0, 1, 300, 0, 0, "FOUNTAIN", 3, "POOL", 0, 0]
```

| Index | Field | Value |
|-------|-------|-------|
| 0 | Type | 1 (valve/actuator) |
| 5 | Move time | 300 ms |
| 8 | Position 1 name | "FOUNTAIN" |
| 9 | Position 1 value | 3 |
| 10 | Position 2 name | "POOL" |
| 11 | Position 2 value | 0 |

**Proposed entities:** `select` for position, `sensor` for current position (derived from active group).

#### F3. Groups as Combined Equipment Scenes

**Source:** `devices[0].groups["0".."5"]`

Group config array: `[name, ?, ?, activeState, durationSec, lastRunTs, scheduleMode, ?]`

| Index | Field | Range |
|-------|-------|-------|
| 0 | Name | "POOL", "WATERFALL", "FILTRATION", "AMBIANCE", "CLEANER" |
| 3 | Active state | 0=off, 1=active (filtration), 2=active with heat |
| 4 | Duration | Seconds (172800=48h, 14400=4h, 5400=90m, 900=15m) |
| 6 | Schedule mode | 0=manual, 1=scheduled |

Group equip sub-object maps equipment IDs to settings for that group:

| Group | equip[1] RPM (×50) | Real RPM | equip[3] Valve | equip[0] Heat Pump |
|-------|--------------------|----------|----------------|---------------------|
| POOL | [35, 0] | 1750 | [0, 0] = POOL | [1, 84] = heat, 84°F |
| WATERFALL | [60, 0] | 3000 | [3, 0] = FOUNTAIN | — |
| FILTRATION | [35, 0] | 1750 | — | — |
| AMBIANCE | [44, 0] | 2200 | [3, 0] = FOUNTAIN | — |
| CLEANER | [69, 0] | 3450 | — | — |

**Mutual exclusion confirmed:** When POOL group is active (index 3 = 2), FILTRATION is inactive (index 3 = 0). When FILTRATION is active (index 3 = 1), POOL is inactive (index 3 = 0).

**Proposed entities:** `select` for active group, `sensor` for active group name.

#### F4. Heat Pump Active-in-Group Flag

**Source:** `devices[0].equip["0"][7]`

| File | Value | Meaning |
|------|-------|---------|
| Compressor off, filtration | 0 | HP not in active group |
| Compressor off, priming | 0 | HP not in active group |
| Compressor on, pool group | 1 | HP enabled by pool group |

**Proposed entity:** `binary_sensor` for "heat pump enabled by active group".

---

### 🟡 MEDIUM-HIGH CONFIDENCE — Strong evidence, single system

#### F5. Equipment Type Taxonomy

| Type | Name | Seen In | Notes |
|------|------|---------|-------|
| 0 | Variable Speed Pump | equip[1] | Internal RPM × 50 = real RPM |
| 1 | Valve/Actuator | equip[3] | Named positions, timed movement |
| 2 | (unknown) | — | All null in 090; possibly single-speed pump, light, or booster |
| 3 | Heat Pump | equip[0] | Already handled by existing integration |
| 4–15 | (unknown) | — | All null in 090; may include lights, solar valves, chemical feeders, additional heat pumps |

#### F6. Group index 3 Active State Semantics

| Value | Meaning | Evidence |
|-------|---------|----------|
| 0 | Inactive | All non-active groups across all 3 samples |
| 1 | Active (filtration/circulation only) | FILTRATION group in files 1 and 2 |
| 2 | Active with heat demand | POOL group in file 3 (mode=1, compressor on) |

The value 2 may indicate "active + heat pump enabled" specifically for the POOL group.

#### F7. Group Schedules Exist Per-Group

**Source:** `devices[0].schedules["0".."5"]`

Each group has up to 4 schedule slots: `[dayMask, startTime, endTime]`

| Group | Day mask values seen | Time values seen |
|-------|---------------------|-------------------|
| POOL | 62, 65, 0 | 0, 8, 11, 17, 11527 |
| WATERFALL | 0 | 8, 14 |
| FILTRATION | 62, 0 | 8, 11, 17, 20, 21, 3848, 7688, 11528 |
| AMBIANCE | 0 | 8, 16 |
| CLEANER | 0 | 8, 18 |

**Day mask:** 7-bit, bit 0 = Sunday. 62 = 0b0111110 = Mon–Fri. 65 = 0b1000001 = Sat+Sun. 0 = disabled.

**Time encoding:** Values ≤ 23 look like hours (0=midnight, 8=8am, 17=5pm). Values like 3848, 7688, 11527, 11528 use an unknown encoding — possibly minutes-past-epoch, seconds, or a special marker.

---

### 🟠 MEDIUM CONFIDENCE — Reasonable inference

#### F8. Group index 1 May Be an Equipment Filter or Category

Values: 0 (POOL), 22 (WATERFALL), 2 (FILTRATION), 8 (AMBIANCE), 3 (CLEANER). Not obviously bitmask-mapped to equipment types. Could be a group category/preset ID.

#### F9. Group index 2 May Be a Flow or Speed Target

Values: 192 (POOL/FILTRATION), 24 (WATERFALL), 32 (AMBIANCE), 48 (CLEANER). Does not match RPM (RPM comes from equip sub-object). Could be GPM target, priority, or display category.

#### F10. Group Duration Is Auto-Shutoff Timer

Each group has a duration (48h for POOL, 4h for WATERFALL, 90m for AMBIANCE, 15m for CLEANER). Index 5 (`lastRunTs`) is non-zero when the group has been running — possibly a countdown remaining or a start timestamp.

---

### 🟢 LOWER CONFIDENCE — Needs more data

#### F11. Schedule Time Encoding (Non-Hour Values)

Values like 7688, 11527, 11528 appear with dayMask=0 (disabled). May be:
- Historical last-run timestamps
- A different time unit (seconds since midnight? epoch offsets?)
- Special "until manual stop" markers

#### F12. What Lives in Unused Equipment Slots

Slots 2, 4–15 are null in the 090 system. Other PoolSync installations may have:
- Booster/cleaner pumps
- Pool/spa lights (RGB or single-color)
- Solar heating valves
- Intake valve actuators
- Chemical feeders / pH controllers
- Additional heat pumps (multi-unit — note `multiUnitMode=0` in config)

#### F13. Pump Subtype (index 2 = 2)

The circulation pump has index 2 = 2. Could mean "variable speed" as opposed to 1=single-speed or 0=two-speed. Only one pump type observed.

#### F14. Equipment Write API Format

The write endpoint `PATCH /api/poolsync?cmd=devices&device={id}` currently sends `config.{key}`. Equipment and group writes may use a different command (`cmd=deviceConfig` or similar) with the equipment slot as a sub-path. Actual API traffic capture needed.

#### F15. Multi-Unit Heat Pump

`multiUnitMode` and `multiUnitAddr` exist in heat pump config. The 16 equipment slots suggest multiple heat pumps could populate different slots in a multi-unit setup. The 090 system has only one.

---

## 4. Confirmation Process

---

## 5. Unimplemented Heat Pump Values & Controls

Fields present in the heat pump device payload (`devices[hp_id].status`, `.config`, `.system`, `.nodeAttr`, `.stats`, `.faultCounts`) that are **not yet exposed** as sensors, binary sensors, or controls.

Data compared across 9 diagnostic files spanning 3 models:
- **T75** (`075AHDSBLH`): heat-pool, heat-spa, fault, in-celsius, off-no-flow, off-with-flow, remote-disabled, spa-startup
- **SQ160R** (`160ARDSBPA`): off, idle, heating
- **090** (`090AHDSBPH`): compressor-off-filtration, compressor-off-priming, compressor-on-pool

When a field is `0`, `-40`, or `127` and never varies on a given model, it is treated as "sensor not present" for that model.

---

### 🔴 HIGH CONFIDENCE — Values change meaningfully with operating state

#### H1. `waterTemp2` — Secondary water temperature ✅

**Status:** Confirmed & built (`sensor.hp_water_temp2` — see section 2.5).

| Model | Off/Idle | Heating | Comp On | Present? |
|-------|----------|---------|---------|----------|
| T75 | 0 | 0 | — | ❌ |
| SQ160R | 71.27 / 84.03 | 81.08 | — | ✅ |
| 090 | 83.71 / 83.54 | — | 83.54 | ✅ |

Always within ~0.5°F of `waterTemp`. Likely the outlet-side water temperature sensor (after heat exchanger). ΔT between `waterTemp` and `waterTemp2` when compressor is running would indicate heat transfer rate.

---

#### H2. `ds1Temp` / `ds2Temp` — Defrost/refrigerant temperatures ✅

**Status:** Confirmed & built (`sensor.hp_ds1_temp`, `sensor.hp_ds2_temp` — see section 2.5).

| Model | Off/Idle | Heating | Comp On | Notes |
|-------|----------|---------|---------|-------|
| T75 | 0 | 0 | — | ❌ not present |
| SQ160R | 71/70 (off), 79/78 (idle) | 70/58 | — | ds2 drops ~12°F during heating |
| 090 | 67/67, 64/62 (filtration) | — | 62/57 | ds2 drops ~5°F with compressor on |

In air-source heat pumps, ds1 is typically suction line temperature and ds2 is liquid line temperature. The temperature spread between them changes with compressor load — useful for detecting defrost cycles or low refrigerant.

---

#### H3. `flowPeriod` — Flow switch pulse period

| Model | Value | Notes |
|-------|-------|-------|
| T75 | 0 | ❌ not present |
| SQ160R | 599 | Constant across all states |
| 090 | 1437 | Constant across all states |

Non-zero when a flow sensor is present. May be the period of a paddle-wheel or hall-effect flow sensor in milliseconds. Shorter period = higher flow. Could be converted to GPM if we can determine the K-factor.

**Proposed:** `sensor` (diagnostic, disabled by default), raw ms value. Flow rate derivation needs calibration data.

---

#### H4. `stateFlags` raw — Diagnostic bitmask sensor

| Model | Off | Idle | Heating | Fault | Comp On |
|-------|-----|------|---------|-------|---------|
| T75 | — | — | 2 (heat pool) | 192 | — |
| SQ160R | 8450 | 8452 | 8456 | — | — |
| 090 | 257 (filtration) | — | — | — | 264 |

The raw `stateFlags` value encodes the heat pump's internal state machine. Currently only used internally for capability detection. Exposing the raw value as a diagnostic sensor lets users and developers correlate behavior with future bitmask discoveries.

**Proposed:** `sensor` (diagnostic, disabled by default), raw integer.

---

#### H5. `compRPM` — Compressor RPM

Always `0` in all current samples, even when `ctrlFlags` shows compressor engaged. This suggests the T75, SQ160R, and 090 units all use single-speed or two-speed compressors that don't report RPM. On a variable-speed/inverter model this field would be non-zero.

**Proposed:** `sensor` (diagnostic, disabled by default). Will report `0` until we encounter a variable-speed unit.

---

### 🟡 MEDIUM-HIGH CONFIDENCE — Consistent patterns, limited sample diversity

#### H6. `efficiencyMode` — Efficiency/silent mode

| Model | Value | Notes |
|-------|-------|-------|
| T75 | 0 | Older firmware, may not support |
| SQ160R | 1 | Enabled |
| 090 | 1 | Enabled |

When enabled, the heat pump may run at reduced compressor speed or fan speed for quieter operation. Write control likely uses the same PATCH endpoint with key `efficiencyMode`.

**Proposed:** `switch` entity (or `binary_sensor` if read-only). Write needs API traffic confirmation.

---

#### H7. `schedMode` — Heat pump schedule enable

| Model | Value |
|-------|-------|
| T75 | 0 (no schedule) |
| SQ160R | 1 (schedule active) |
| 090 | 1 (schedule active) |

Distinct from the group-level schedule mode. This is the heat pump's own internal schedule.

**Proposed:** `binary_sensor` or `switch`.

---

#### H8. `extCtrlMode` — External/remote control mode ✅

**Status:** Confirmed & built (`binary_sensor.heatpump_ext_ctrl` — see section 2.6).

| Model | Value |
|-------|-------|
| T75 | 0 |
| SQ160R | **5** |
| 090 | **5** |

Always 5 on the two systems running firmware 856 (appFwVersion 61-81). Always 0 on the T75 (appFwVersion 270, older PoolSync hardware — PID 9984 vs 9986). The consistent value of 5 suggests this is the "PoolSync is in control" mode — enabling remote write operations.

**Proposed:** `binary_sensor` — "remote control enabled" (true when non-zero).

---

#### H9. `faultCounts[]` — Fault occurrence histogram ✅

**Status:** Confirmed & built (`sensor.hp_top_fault_code`, `sensor.hp_top_fault_count` — see section 2.5).

| Model | Index 1 | Index 3 | Index 12 | Others |
|-------|---------|---------|----------|--------|
| T75 | 314–319 | 4–5 | 3 | 0 |
| SQ160R | 0 | 0 | 0 | 0 |
| 090 | 0 | 0 | 0 | 0 |

The T75 has accumulated hundreds of fault-code-1 events (likely HP5 or similar). The array length varies: T75 has 14 entries, SQ160R has 44, 090 has 37. This is a running histogram of how many times each fault code has been triggered — complementary to `faults[]` which shows currently active faults.

**Proposed:** `sensor` for the most frequently triggered fault code and its count (diagnostic). Useful for maintenance planning.

---

#### H10. `turboBoost` — Turbo/boost mode

Always `0` in all samples. When enabled, may force maximum compressor and fan speed regardless of efficiency settings.

**Proposed:** `switch` entity. Write needs API traffic confirmation.

---

### 🟠 MEDIUM CONFIDENCE — Plausible but needs verification

#### H11. `solarTemp` — Solar panel temperature

| Model | Value | Meaning |
|-------|-------|---------|
| T75 | 0 | No sensor |
| SQ160R | 127 | Possible sentinel for "no sensor" |
| 090 | -40 | Sentinel for "no sensor" |

-40 is the common "not connected" sentinel in the 090 system (also used for `outletTemp`). 127 may serve the same purpose in the SQ160R. If a user had solar thermal panels, this would carry a real temperature.

**Proposed:** `sensor` (diagnostic, disabled by default). Show `unavailable` when value is -40, 0, or 127.

---

#### H12. `outletTemp` — Outlet water temperature

Same sentinel pattern as `solarTemp`. No system in our samples has this sensor. Would measure water temperature exiting the heat pump.

**Proposed:** `sensor` (diagnostic, disabled by default). Show `unavailable` when sentinel.

---

#### H13. `geoInlet` / `geoOutlet` — Geothermal loop temperatures

On the 090 system, these exactly mirror `ds1Temp`/`ds2Temp`. The naming suggests they serve as geothermal ground-loop temperature sensors when the unit is configured for geothermal operation (vs air-source where ds1/ds2 are the primary labels).

**Proposed:** `sensor` (diagnostic, disabled by default). May be redundant with ds1/ds2 on air-source units.

---

#### H14. `setpointMin` / `setpointMax` — Device-reported setpoint limits ✅

**Status:** Confirmed & built (climate entity now reads these dynamically — see section 2.7).

| Model | Min | Max |
|-------|-----|-----|
| T75 | 0 | 0 |
| SQ160R | 40 | 104 |
| 090 | 40 | 104 |

Our climate entity currently hardcodes `_attr_min_temp = 40` and `_attr_max_temp = 104`. When the device reports non-zero values, we should use those instead for dynamic range clamping.

**Proposed:** Use these values to populate `min_temp`/`max_temp` on the climate entity when non-zero, falling back to 40/104.

---

#### H15. `serviceMode` (heat pump level)

Always `0` in all samples. This is separate from the controller-level `poolSync.config.serviceMode`. When 1, the heat pump may be in technician/maintenance mode, potentially disabling remote control.

**Proposed:** `binary_sensor` — "heat pump service mode" (diagnostic).

---

### 🟢 LOWER CONFIDENCE — Speculative or single-model

#### H16. `system.serialNum` — Heat pump serial number

Present on T75 and SQ160R (redacted in diagnostics, but present in raw data). Could be a diagnostic sensor for warranty/support.

#### H17. `system.appFwVersion` — Application firmware version

| Model | Version |
|-------|---------|
| T75 | 270 |
| SQ160R | 81 |
| 090 | 61 |

Useful for troubleshooting. Already redacted from diagnostics on T75/SQ160R but available in raw data.

**Proposed:** `sensor` (diagnostic, disabled by default).

#### H18. `system.blFwVersion` — Bootloader firmware

T75: 262, SQ160R: 0, 090: 0. Only the T75 reports bootloader version.

#### H19. `system.dispFwVersion` — Display firmware

T75: 65, SQ160R: 3, 090: 3. All report a value.

#### H20. `system.compModelNum` — Compressor model

"ZPV038CE-2E9" on both SQ160R and 090 (same Copeland compressor). Empty on T75.

**Proposed:** `sensor` (diagnostic, disabled by default).

#### H21. `nodeAttr.pid` — Product ID

| Model | PID |
|-------|-----|
| T75 | 9984 |
| SQ160R | 9986 |
| 090 | 9986 |

9984 appears to be an older PoolSync hardware generation. 9986 is the current generation.

#### H22. `nodeAttr.flags` — Node attribute flags

| Model | Value |
|-------|-------|
| T75 | 2 |
| SQ160R | 2 |
| 090 | 0 |

Consistently 2 on the older generation and 0 on the newer 090 system. May encode device capabilities or connection state.

#### H23. `stats[]` — Runtime statistics array

Varying lengths (T75: 10 entries, SQ160R: 19, 090: 18) with accumulating counters. Without documentation, individual indices can't be labeled. Some entries clearly increment over time (runtime hours, compressor cycles, etc.).

**Proposed:** No entities until we can label individual indices. Continue exposing in diagnostics for future analysis.

#### H24. `gasBoost` / `backupHeat*` / `solarMode` / `solarSetpoint` — Auxiliary heat features

All zero in all current samples. These configure auxiliary/backup heating (gas boiler, solar thermal). May be non-zero on systems with hybrid heating.

**Proposed:** Defer until we encounter a system using these features.

#### H25. `multiUnitMode` / `multiUnitAddr` — Multi-unit configuration

Always zero. For installations with multiple heat pumps in parallel.

#### H26. `nodeAttr.bootMode` — Boot mode

Always 2 across all samples. Unknown meaning.

#### H27. `nodeAttr.fwUpdProg` / `fwUpdResult` — Firmware update status

Always 0. Would be non-zero during/after firmware updates.

---

## 6. Confirmation Process

Each finding in sections 3 and 5 needs to be confirmed before building. The process:

1. **Request targeted diagnostic captures** from users with relevant equipment
   - For section 3 (groups/equipment): captures per group active state, before/after group changes via app
   - For section 5 (heat pump values): captures across all operating modes (off/idle/heating/cooling/fault)

2. **Capture API traffic** (mitmproxy or similar) between the PoolSync app and device during:
   - Group activation / deactivation
   - Pump RPM changes
   - Valve position changes
   - Heat pump config writes (efficiencyMode, turboBoost, schedMode)

3. **After confirmation, move finding to section 1 or 2** and build the entity/platform implementation.

| Status | Marker |
|--------|--------|
| Confirmed & built | ✅ |
| Confirmed, not yet built | 🔵 |
| Probable, awaiting confirmation | 🟡 |
| Speculative | 🟢 |

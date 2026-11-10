# PoolSync Reverse Engineering

Reference document tracking what we know, what we've built, and what we suspect. Each section cites the specific diagnostic payloads or code paths that back the claim.

---

## 0a. Sources

Three independent sources back the claims in this document:

1. **Live local API traffic.** Requests issued against real hardware (initially a T75 heat pump on fw 860, later a 090 system with a heat pump, variable-speed pump and return valve), with the responses stored as diagnostic fixtures under `tests/sample_diagnostics/`. The live-tested tables in §0b, and most of §4 and §5, come from here.
2. **User packet captures.** The write payloads in F1, F7a and F10a were confirmed by capturing what the vendor app sent to the device.
3. **Observed app behaviour.** Endpoint paths, header sets, pairing prompts, button-hold durations and UI labels were cross-checked against the vendor Android app (v4.73, package `com.poolconnect.sync`) as it behaves on screen and on the wire.

Everything here is a behavioural description written in our own words. This document reproduces no vendor source code and carries no disassembly listings or offsets. Where a claim rests only on the app's user-facing behaviour and has not been reproduced against hardware, the section says so and marks it accordingly.

---

## 0b. Live API Probing & App Endpoint Map (Preliminary)

A live T75 heat pump (fw 860, hw 2.0) was probed via the local HTTP API. Cross-checking against the vendor app supplied the remaining endpoint set and their HTTP methods. **These findings are preliminary** — only one firmware version has been live-tested at the time of writing, and behaviour may vary across models and firmware revisions.

### Live-tested (fw 860, T75 heat pump only — no additional devices)

#### GET requests

| Method | Endpoint | Result |
|--------|----------|--------|
| `GET` | `/api/poolsync?cmd=poolSync` | ✅ Returns controller status, `deviceType` map. Auth via `Authorization: {password}` works |
| `GET` | `/api/poolsync?cmd=poolSync&all` | ✅ Same response; `&all` has no observable difference on this firmware |
| `GET` | `/api/poolsync?cmd=devices&device=0` | ❌ 401 Unauthorized |
| `GET` | `/api/poolsync?cmd=devices&device=9984` | ❌ 401 Unauthorized |
| `GET` | `/api/dongle/*` | ❌ "This URI does not exist" |

#### PATCH write tests (confirmed working)

The `User` header is **required** for PATCH requests alongside `Authorization`. All payload formats below returned HTTP 200 on fw 860. Note: the T75 has no groups or ChemSync/ChlorSync hardware, so these tests only confirm the device accepts the JSON format at the HTTP layer — they do not confirm the writes have a functional effect. The ESP32 acts as a pass-through gateway, accepting any well-formed JSON body.

| Payload | HTTP Result | Purpose |
|---------|-------------|---------|
| `{"config": {"mode": 1}}` | ✅ 200 | Device config write (proven in production) |
| `{"config": {"chlorOutput": 50}}` | ✅ 200 | Chlorinator output write |
| `{"groups": {"0": {"config": ["POOL",0,192,1,172800,0,1,1]}}}` | ✅ 200 | Full group config array replacement |
| `{"groups": {"0": {"config": {"3": 1}}}}` | ✅ 200 | Sparse group state toggle (format later superseded — see F10a) |
| `{"groups": {"2": {"config": [...], "equip": {"1": [35,0]}}}}` | ✅ 200 | Group config + equipment mapping |
| `{"primePump": 1}` | ✅ 200 | Action command |
| `{"equip": {"1": {"7": 58}}}` | ✅ 200 | Equipment array index write |

> **⚠️ Note on the "✅ 200" rows above:** These were validated on a T75 (fw 860) which has no groups/ChemSync/ChlorSync hardware. The device accepted the JSON at the HTTP layer but the writes had no observable effect on that hardware. **The user's packet capture (2026-09-01) on real 090 hardware confirmed the actual group and pump write formats** — see F1 (pump `equip` array) and F10a (group `state` array). Those confirmed formats supersede any guessed payloads in the table above.

**Required PATCH headers:**
```
Authorization: {password}
User: {userSub or static UUID}
Content-Type: application/json
```

### App function-to-method map (observed in the app, not live-tested)

Requests the app issues, with their methods:

| Function | Method | Endpoint | Notes |
|----------|--------|----------|-------|
| `getSync` | `GET` | `?cmd=poolSync` or `?cmd=poolSync&all` | Read all controller+device data |
| `getDevice` | `GET` | `?cmd=devices&device={id}` | Read single device (401 on fw 860) |
| `checkChangeStatus` | `GET` | `?cmd=changeStatus` | May check device status |
| `checkPushLinking` | `GET` | `?cmd=pushLink&status` | Poll push-link state |
| `updateSync` | `PATCH` | `?cmd=poolSync` | Controller-level write |
| `updateDevice` | `PATCH` | `?cmd=devices&device={id}` | Device-level config write |
| `putDevice` | `PUT` | `/api/dongle/devices/{id}` | Full device state replace (dongle API) |
| `putDongleState` | `PUT` | `/api/dongle/state` | Dongle state update |
| `startPushLinking` | `PUT` (local) / `POST` (dongle) | `?cmd=pushLink&start` / `/api/dongle/link` | Initiate push-link pairing. The dongle variant sends body `{"pushLink": true}` |
| `endPushLinking` | `PATCH` | `?cmd=pushLink&end` | End push-link session |
| `restartDevice` | `PUT` | `/api/dongle/software_restart` | Software restart |
| `factoryReset` | `DELETE`/`PUT` | `?cmd=factoryReset` / `/api/dongle/factory_reset` | Factory reset |
| `discoverDevices` | `GET`/`PUT` | `/api/dongle/discover_devices` | Scan for attached devices |
| `sendWiFiCredentials` | `PUT` | `/api/dongle/wifi/setup` | Provision WiFi |
| `getWiFiDevices` | `GET` | `/api/dongle/wifi/list` | List WiFi networks |
| `resetHash` | `DELETE`/`POST` | *(unknown)* | Auth hash reset |

All requests use the same header pattern:
```
Authorization: {psToken}
User: {userSub or static UUID}
Content-Type: application/json  (only on requests with a body)
```

The `User` header is **mandatory** for PATCH requests — the device returns 401 without it. GET requests appear to work with `Authorization` alone. The integration uses a static UUID (`b167ecc8-87ce-47da-9b7d-cab632a2eeba`) for the `User` header, which matches the app's `userSub` parameter for local-only requests.

**Key observation:** On fw 860, `devices` in the response is an integer count (`devices: 1`) rather than a device dict. Whether this is firmware-specific or requires a different request pattern is unknown.

**Key note on `updateDevice` vs `putDevice`:** The app has *two* write paths — `updateDevice` (PATCH → `?cmd=devices&device={id}`) for partial updates, and `putDevice` (PUT → `/api/dongle/devices/{id}` or cloud `thingsAPI.updateShadow`) for full state replacement. Our current `setDeviceConfigValue` write method uses the PATCH path, matching `updateDevice`. The PUT/dongle path is likely for initial provisioning, not runtime control.

### 0c. Complete Field Name Mappings

The app resolves every readable sensor and writable config field through a single mapping from internal constant names to API data paths. The mapping uses dot-separated paths into the per-device data object:

- `status.{field}` → readable sensor values
- `config.{field}` → writable configuration values
- `system.{field}` → device metadata (model, serial, firmware)
- `stats[{index}]` → runtime counter arrays
- `nodeAttr.{field}` → connection/identity fields

**Note on the write path:** The `updateDevice` function sends `JSON.stringify(payload)` as the body where payload is an object whose keys correspond to the API paths below. For config writes tested so far, the payload shape `{"config": {field: value}}` works. The app's internal write pipeline may construct the payload differently (using the full DEVICES mapping object and `merge` to batch changes), but the PATCH endpoint accepts partial `{"config": {key: value}}` bodies.

#### Controller-level paths (`poolSync.*`)

| Constant | API Path | Type | Notes |
|----------|----------|------|-------|
| `SYNC_NAME` | `poolSync.config.name` | Read | Device name from config |
| `SYNC_ONLINE` | `poolSync.status.online` | Read | Bool |
| `SYNC_BOARD_TEMP` | `poolSync.status.boardTemp` | Read | °C |
| `SYNC_FW_VERSION` | `poolSync.system.fwVersion` | Read | Firmware number |
| `SYNC_HW_VERSION` | `poolSync.system.hwVersion` | Read | Hardware version |
| `SYNC_BSSID` | `poolSync.system.bssid` | Read | WiFi BSSID |
| `SYNC_FLAGS` | `poolSync.status.flags` | Read | Status flags |
| `SYNC_FAULTS` | `poolSync.faults` | Read | Fault code |
| `SYNC_OPT_INS` | `poolSync.config.optIns` | Read | Option flags |
| `SYNC_SETUP_MODE` | `poolSync.config.setupMode` | Read | Setup mode flag |
| `SYNC_SERVICE_MODE` | `poolSync.config.serviceMode` | Read | Service mode flag |
| `SYNC_BRIGHTNESS` | `poolSync.config.brightness` | Read | Display brightness |
| `SYNC_LATITUDE` | `poolSync.config.latitude` | Read | GPS latitude |
| `SYNC_LONGITUDE` | `poolSync.config.longitude` | Read | GPS longitude |
| `SYNC_UI_PID` | `poolSync.status.remoteUiPid` | Read | Remote UI process ID |
| `SYNC_UI_VERSION` | `poolSync.status.remoteUiVersion` | Read | Remote UI version |
| `AUTHORIZED` | `poolSync.config.authorized` | Read/Write? | Authorization status |
| `IS_WATCHING` | `poolSync.config.isWatching` | Read | Watchdog flag |
| `TIME_ZONE` | `poolSync.config.timeZone` | Read | IANA timezone |
| `TIME` | `poolSync.status.dateTime` | Read | Device date/time string |

#### Heat Pump paths (`devices[{id}].*`)

| Constant | API Path | Type | Notes |
|----------|----------|------|-------|
| `DEVICE_PID` | `nodeAttr.pid` | Read | Product ID |
| `DEVICE_NAME` | `nodeAttr.name` | Read | Display name |
| `DEVICE_NODE_ADDR` | `nodeAttr.nodeAddr` | Read | RS-485 node address |
| `DEVICE_IDMP_ADDR` | `nodeAttr.idmpAddr` | Read | IDMP address |
| `DEVICE_ONLINE` | `nodeAttr.online` | Read | Bool |
| `DEVICE_FLAGS` | `nodeAttr.flags` | Read | Status flags |
| `DEVICE_BOOT_MODE` | `nodeAttr.bootMode` | Read | Boot mode |
| `DEVICE_FW_PROGRESS` | `nodeAttr.fwUpdProg` | Read | FW update progress |
| `DEVICE_FW_RESULT` | `nodeAttr.fwUpdResult` | Read | FW update result |
| `DEVICE_FAULTS` | `faults` | Read | Fault code |
| `DEVICE_FAULT_COUNTS` | `faultCounts` | Read | Fault counter array |
| `DEVICE_STATS` | `stats` | Read | Stats array |
| `DEVICE_BOARD_TEMP` | `status.boardTemp` | Read | °C |
| `HP_WATER_TEMP` | `status.waterTemp` | Read | °F |
| `HP_WATER_TEMP_TWO` | `status.waterTemp2` | Read | °F |
| `HP_WATER_TEMP_THREE` | `status.waterTemp3` | Read | °F |
| `HP_AIR_TEMP` | `status.airTemp` | Read | °F |
| `HP_AMBIENT_AIR_TEMP` | `status.ambientAirTemp` | Read | °F |
| `HP_SOLAR_TEMP` | `status.solarTemp` | Read | °F |
| `HP_DS1_TEMP` | `status.ds1Temp` | Read | Defrost sensor 1 |
| `HP_DS2_TEMP` | `status.ds2Temp` | Read | Defrost sensor 2 |
| `HP_DS3_TEMP` | `status.ds3Temp` | Read | Defrost sensor 3 |
| `HP_COMP_RPM` | `status.compRPM` | Read | Compressor RPM |
| `HP_FLOW_PERIOD` | `status.flowPeriod` | Read | Flow sensor period |
| `HP_OUTLET_TEMP` | `status.outletTemp` | Read | °F |
| `HP_GEO_INLET` | `status.geoInlet` | Read | Geothermal inlet |
| `HP_GEO_OUTLET` | `status.geoOutlet` | Read | Geothermal outlet |
| `HP_PRESSURE_ONE` | `status.pressure1` | Read | Pressure sensor 1 |
| `HP_PRESSURE_TWO` | `status.pressure2` | Read | Pressure sensor 2 |
| `HP_WATER_SENSOR_ONE` | `status.ws1Temp` | Read | Water sensor 1 |
| `HP_WATER_SENSOR_TWO` | `status.ws2Temp` | Read | Water sensor 2 |
| `HP_STATE_FLAGS` | `status.stateFlags` | Read | State flags |
| `HP_CTRL_FLAGS` | `status.ctrlFlags` | Read | Control flags |
| `HP_BOARD_TEMP` | `status.boardTemp` | Read | °C |
| `HP_MODE` | `config.mode` | Read/Write | Operating mode |
| `HP_SPA_MODE` | `config.poolSpaMode` | Read/Write | Pool/Spa selection |
| `HP_POOL_SETPOINT` | `config.setpoint` | Read/Write | Target temp |
| `HP_SPA_SETPOINT` | `config.spaSetpoint` | Read/Write | Spa target temp |
| `HP_EFFICIENCY_MODE` | `config.efficiencyMode` | Read/Write | Efficiency mode |
| `HP_TURBO_BOOST` | `config.turboBoost` | Read/Write | Turbo boost flag |
| `HP_SERVICE_MODE` | `config.serviceMode` | Read/Write | Service mode |
| `HP_SCHED_MODE` | `config.schedMode` | Read/Write | Schedule mode |
| `HP_SCHED_AWAY_END` | `config.schedAwayEnd` | Read/Write | Away end time |
| `HP_MULTI_UNIT_MODE` | `config.multiUnitMode` | Read/Write | Multi-unit mode |
| `HP_MULTI_UNIT_ADDRESS` | `config.multiUnitAddr` | Read/Write | Multi-unit address |
| `HP_GAS_BOOST` | `config.gasBoost` | Read/Write | Gas boost flag |
| `HP_BACKUP_HEAT_MODE` | `config.backupHeatMode` | Read/Write | Backup heat mode |
| `HP_BACKUP_HEAT_START_TIME` | `config.backupHeatStartTime` | Read/Write | Backup heat start |
| `HP_BACKUP_HEAT_STOP_TIME` | `config.backupHeatStopTime` | Read/Write | Backup heat stop |
| `HP_SOLAR_MODE` | `config.solarMode` | Read/Write | Solar mode |
| `HP_SOLAR_SETPOINT` | `config.solarSetpoint` | Read/Write | Solar target |
| `HP_SETPOINT_MIN` | `config.setpointMin` | Read | Min setpoint |
| `HP_SETPOINT_MAX` | `config.setpointMax` | Read | Max setpoint |
| `HP_SERIAL_NUM` | `system.serialNum` | Read | Serial number |
| `HP_MODEL_NUM` | `system.modelNum` | Read | Model number |
| `HP_HW_VERSION` | `system.hwVersion` | Read | Hardware version |
| `HP_FW_VERSION` | `system.appFwVersion` | Read | App firmware |
| `HP_BL_VERSION` | `system.blFwVersion` | Read | Bootloader firmware |
| `HP_DISP_FW_VERSION` | `system.dispFwVersion` | Read | Display firmware |
| `HP_COMP_MODEL_NUM` | `system.compModelNum` | Read | Compressor model |
| `HP_EQUIPMENT` | `equip` | Read | Equipment sub-object |
| `HP_GROUPS` | `groups` | Read | Groups sub-object |
| `HP_SCHEDULES` | `schedules` | Read | Schedules sub-object |
| `HP_FAULTS` | `faults` | Read | Fault array |
| `HP_FAULT_COUNTS` | `faultCounts` | Read | Fault count array |
| `HP_EXTERNAL_CONTROL` | `config.extCtrlMode` | Read/Write | External control mode |

#### ChlorSync paths (`devices[{id}].*`)

| Constant | API Path | Type | Notes |
|----------|----------|------|-------|
| `CHLOR_WATER_TEMP` | `status.waterTemp` | Read | °F |
| `CHLOR_SALT_PPM` | `status.saltPPM` | Read | Salt level |
| `CHLOR_OUTPUT` | `config.chlorOutput` | Read/Write | Output % |
| `CHLOR_FWD_CURRENT` | `status.fwdCurrent` | Read | Forward current |
| `CHLOR_REV_CURRENT` | `status.revCurrent` | Read | Reverse current |
| `CHLOR_AMPS` | `status.amps` | Read | Amperage |
| `CHLOR_CELL_LIFE` | `status.cellLife` | Read | Cell life remaining |
| `CHLOR_FLAGS` | `status.flags` | Read | Status flags |
| `CHLOR_STATE_FLAGS` | `status.stateFlags` | Read | State flags |
| `CHLOR_CTRL_FLAGS` | `status.ctrlFlags` | Read | Control flags |
| `CHLOR_BOARD_TEMP` | `status.boardTemp` | Read | °C |
| `CHLOR_OUT_VOLTAGE` | `status.outVoltage` | Read | Output voltage |
| `CHLOR_CELL_RAIL_VOLTAGE` | `status.cellRailVoltage` | Read | Cell rail voltage |
| `CHLOR_CELL_RAW_SALT_ADC` | `status.cellRawSaltADC` | Read | Raw salt ADC |
| `CHLOR_FLOW_RATE` | `status.flowRate` | Read | Flow rate |
| `CHLOR_TEMP_COMP_OUTPUT` | `status.tempCompOutput` | Read | Temp comp output % |
| `CHLOR_BOOST_REMAINING` | `status.boostRemaining` | Read | Boost time remaining |
| `CHLOR_REVERSE_REMAINING` | `status.reverseRemaining` | Read | Reverse time remaining |
| `CHLOR_BOOST_ENABLE` | `config.boostEnable` | Read/Write | Boost on/off |
| `CHLOR_POLARITY_CHANGE_TIME` | `config.polarityChangeTime` | Read/Write | Polarity interval |
| `CHLOR_TEMP_COMP_ENABLE` | `config.tempCompEnable` | Read/Write | Temp comp on/off |
| `CHLOR_TEMP_UNITS` | `config.tempUnits` | Read/Write | °F/°C |
| `CHLOR_USER_SALT_CALIB` | `config.userSaltCalib` | Read/Write | Salt calibration |
| `CHLOR_USER_TEMP_CALIB` | `config.userTempCalib` | Read/Write | Temp calibration |
| `CHLOR_GALLONS` | `config.gallons` | Read/Write | Pool size |
| `CHLOR_PROX_SENSOR_ENABLE` | `config.proxSensorEnable` | Read/Write | Proximity sensor |
| `CHLOR_POOL_COVER_CTRL` | `config.poolCoverCtrl` | Read/Write | Cover control |
| `CHLOR_ORP_INPUT_CTRL` | `config.orpInputCtrl` | Read/Write | ORP input control |
| `CHLOR_AUX_INPUT_ENABLE` | `config.auxInputEnable` | Read/Write | Aux input |
| `CHLOR_DEMO_MODE` | `config.demoMode` | Read/Write | Demo mode |
| `CHLOR_SERVICE_MODE` | `config.serviceMode` | Read/Write | Service mode |
| `CHLOR_WEIGHT_VOLUME_UNITS` | `config.weightVolumeUnits` | Read/Write | Units |
| `CHLOR_DATE_FORMAT` | `config.dateFormat` | Read/Write | Date format |
| `CHLOR_TIME_FORMAT` | `config.timeFormat` | Read/Write | Time format |
| `CHLOR_USER_LOCK_CODE` | `config.userLockCode` | Read/Write | Lock code |
| `CHLOR_USER_LOCK_CODE_ENABLE` | `config.userLockCodeEnable` | Read/Write | Lock enable |
| `CHLOR_NUM_BLADES` | `system.numBlades` | Read | Cell blade count |
| `CHLOR_CELL_SERIAL_NUM` | `system.cellSerialNum` | Read | Cell serial |
| `CHLOR_CELL_FW_VERSION` | `system.cellFwVersion` | Read | Cell firmware |
| `CHLOR_CELL_HW_VERSION` | `system.cellHwVersion` | Read | Cell hardware |
| `CHLOR_CELL_CALIB` | `system.cellCalib` | Read | Cell calibration |
| `CHLOR_DRV_FW_VERSION` | `system.drvFwVersion` | Read | Driver firmware |
| `CHLOR_DRV_BL_FW_VERSION` | `system.drvBlFwVersion` | Read | Driver bootloader |
| `CHLOR_DRV_HW_VERSION` | `system.drvHwVersion` | Read | Driver hardware |
| `CHLOR_DRV_MODEL_NUM` | `system.drvModelNum` | Read | Driver model |
| `CHLOR_DRV_SERIAL_NUM` | `system.drvSerialNum` | Read | Driver serial |
| `CHLOR_MAX_CURRENT` | `system.maxCurrent` | Read | Max current rating |
| `CHLOR_MODEL_NUM` | `system.modelNum` | Read | Model number |
| `CHLOR_SERIAL_NUM` | `system.serialNum` | Read | Serial number |
| `CHLOR_FW_VERSION` | `system.fwVersion` | Read | Firmware version |
| `CHLOR_HW_VERSION` | `system.hwVersion` | Read | Hardware version |
| `CHLOR_CELL_CYCLE_TIME` | `stats[0]` | Read | Cycle time counter |
| `CHLOR_CELL_COUNTER` | `stats[1]` | Read | Cell counter |
| `CHLOR_CELL_DIR` | `stats[2]` | Read | Polarity direction |
| `CHLOR_CELL_DIR_COUNTER` | `stats[3]` | Read | Direction counter |
| `CHLOR_DRIVER_ON_TIME` | `stats[4]` | Read | Driver on time |
| `CHLOR_DRIVER_DRIVE_TIME` | `stats[5]` | Read | Driver drive time |
| `CHLOR_CELL_ON_TIME` | `stats[6]` | Read | Cell on time |
| `CHLOR_CELL_DRIVE_TIME` | `stats[7]` | Read | Cell drive time |
| `CHLOR_CELL_OVER_SALT_TIME` | `stats[8]` | Read | Over-salt time |
| `CHLOR_CELL_UNDER_SALT_TIME` | `stats[9]` | Read | Under-salt time |
| `CHLOR_SYSTEM_RESETS` | `stats[10]` | Read | Reset count |
| `CHLOR_SYSTEM_UPTIME` | `stats[11]` | Read | Uptime counter |
| `CHLOR_DEBUG_FLAGS` | `stats[12]` | Read | Debug flags |
| `CHLOR_FAULT_COUNT_0_3` | `stats[13]` | Read | Faults 0-3 |
| `CHLOR_FAULT_COUNT_4_7` | `stats[14]` | Read | Faults 4-7 |
| `CHLOR_FAULT_COUNT_8_11` | `stats[15]` | Read | Faults 8-11 |
| `CHLOR_FAULT_COUNT_12_15` | `stats[16]` | Read | Faults 12-15 |
| `CHLOR_FAULT_COUNT_16_19` | `stats[17]` | Read | Faults 16-19 |
| `CHLOR_FAULT_COUNT_20_23` | `stats[18]` | Read | Faults 20-23 |
| `CHLOR_CFG_CP_BOARDS` | `config.cfgCpBoards` | Read/Write | CP board config |
| `CHLOR_MEASURE_SALT` | `measureSalt` | Action | Trigger salt measure |
| `CHLOR_CLEAR_CELL_LIFE` | `clearCellLife` | Action | Reset cell life |

#### ChemSync paths (`devices[{id}].*`)

| Constant | API Path | Type | Notes |
|----------|----------|------|-------|
| `CHEM_PH` | `status.ph` | Read | pH reading |
| `CHEM_ORP` | `status.orp` | Read | ORP reading (mV) |
| `CHEM_ACID_CONSUMED` | `status.acidConsumed` | Read | Acid consumption |
| `CHEM_BOARD_TEMP` | `status.boardTemp` | Read | °C |
| `CHEM_BOOST_REMAINING` | `status.boostRemaining` | Read | Boost time left |
| `CHEM_FLAGS` | `status.flags` | Read | Status flags |
| `CHEM_PH_SETPOINT` | `config.phSetpoint` | Read/Write | pH target |
| `CHEM_PH_MIN` | `config.phMin` | Read/Write | pH min limit |
| `CHEM_PH_MAX` | `config.phMax` | Read/Write | pH max limit |
| `CHEM_PH_ENABLED` | `config.phEnabled` | Read/Write | pH control on/off |
| `CHEM_PH_OFFSET` | `config.phOffset` | Read/Write | pH probe offset |
| `CHEM_ORP_SETPOINT` | `config.orpSetpoint` | Read/Write | ORP target (mV) |
| `CHEM_ORP_ENABLED` | `config.orpEnabled` | Read/Write | ORP control on/off |
| `CHEM_FEED_RATE` | `config.feedRate` | Read/Write | Feed pump rate (unit unknown — intentionally not exposed as an entity) |
| `CHEM_FEED_AMOUNT` | `config.feedAmount` | Read/Write | Feed amount |
| `CHEM_FEED_RATE_UNITS` | `config.feedRateUnits` | Read/Write | Feed rate units |
| `CHEM_MAX_DAILY_FEED` | `config.maxDailyFeed` | Read/Write | Max daily feed |
| `CHEM_FLOW_SENSOR_ENABLE` | `config.flowSensorEnable` | Read/Write | Flow sensor on/off |
| `CHEM_FLOW_POLARITY` | `config.flowPolarity` | Read/Write | Flow polarity |
| `CHEM_SYS_MODE` | `config.sysMode` | Read/Write | System mode |
| `CHEM_MANUAL_MODE` | `config.manualMode` | Read/Write | Manual mode |
| `CHEM_IDMP_ADDRESSES` | `config.idmpAddrs` | Read/Write | IDMP addresses |
| `CHEM_ACID_TANK_ALERT_AMOUNT` | `config.acidTankAlertAmount` | Read/Write | Tank alert threshold |
| `CHEM_FW_VERSION` | `system.fwVersion` | Read | Firmware version |
| `CHEM_HW_VERSION` | `system.hwVersion` | Read | Hardware version |
| `CHEM_SERIAL_NUM` | `system.serialNum` | Read | Serial number |
| `CHEM_MODEL_NUM` | `system.modelNum` | Read | Model number |
| `CHEM_SYSTEM_RESETS` | `stats[0]` | Read | Reset count |
| `CHEM_SYSTEM_UPTIME` | `stats[1]` | Read | Uptime counter |
| `CHEM_FLOW_RUNTIME` | `stats[2]` | Read | Flow runtime |
| `CHEM_FEED_PUMP_RUNTIME` | `stats[3]` | Read | Feed pump runtime |
| `CHEM_TOTAL_ACID_DELIVERY` | `stats[4]` | Read | Total acid delivered |
| `CHEM_TOTAL_CHLORINE_DEMAND_TIME` | `stats[5]` | Read | Total Cl demand time |
| `CHEM_FAULT_COUNT_0_3` | `stats[6]` | Read | Faults 0-3 |
| `CHEM_FAULT_COUNT_4_7` | `stats[7]` | Read | Faults 4-7 |
| `CHEM_FAULT_COUNT_8_11` | `stats[8]` | Read | Faults 8-11 |
| `CHEM_TANK_FEED_RUNTIME` | `stats[9]` | Read | Tank feed runtime |
| `CHEM_STATS_FUTURE_1` through `5` | `stats[10-14]` | Read | Unknown/unused |
| `CHEM_BOOST` | `boost` | Action | Trigger boost cycle |
| `CHEM_PRIME_PUMP` | `primePump` | Action | Prime feed pump |
| `CHEM_REFILL_TANK` | `refillTank` | Action | Refill acid tank |

> **⚠️ Action payload note:** Action fields (`boost`, `primePump`, `refillTank`, `clearCellLife`, `measureSalt`) use the same `PATCH ?cmd=devices&device={id}` endpoint as config writes. Live testing on fw 860 confirmed `{"primePump": 1}` returns HTTP 200, so the plain `{"actionName": value}` format is accepted. Whether the action actually executes depends on the target device supporting it.

#### Equipment (positional array indices)

> **⚠️ Source note:** The `VIRTUAL_EQUIPMENT_*` index mapping below is **derived from the app's display behaviour (v4.73) and is NOT yet verified against live device writes.** The index *positions* are confirmed by real diagnostics (see F1/F2), but the *semantic meaning* of each named constant is inferred from how the app renders the values and has not been confirmed to match the device's write API.

Equipment entries are positional arrays (not named objects). The `VIRTUAL_EQUIPMENT_*` constants map array indices:

| Constant | Array Index | Meaning |
|----------|-------------|---------|
| `VIRTUAL_EQUIPMENT_TYPE` | `[0]` | Equipment type code |
| `VIRTUAL_EQUIPMENT_NAME` | `[1]` | Display name string |
| `VIRTUAL_EQUIPMENT_NAME_ID` | `[2]` | Name ID |
| `VIRTUAL_EQUIPMENT_SUB_TYPE` | `[3]` | Sub-type code |
| `VIRTUAL_EQUIPMENT_PORT` | `[4]` | Port number |
| `VIRTUAL_EQUIPMENT_TIME_START` | `[5]` | Timer start |
| `VIRTUAL_EQUIPMENT_TIME_LEFT` | `[6]` | Timer remaining |
| `VIRTUAL_EQUIPMENT_STATE` | `[7]` | On/off state |
| `VIRTUAL_EQUIPMENT_PARAM_8` | `[8]` | Type-specific parameter 8 |
| `VIRTUAL_EQUIPMENT_PARAM_9` | `[9]` | Type-specific parameter 9 |
| `VIRTUAL_EQUIPMENT_PARAM_10` | `[10]` | Type-specific parameter 10 |
| `VIRTUAL_EQUIPMENT_PARAM_11` | `[11]` | Type-specific parameter 11 |
| `VIRTUAL_EQUIPMENT_PARAM_12` | `[12]` | Type-specific parameter 12 |
| `VIRTUAL_EQUIPMENT_PARAM_13` | `[13]` | Type-specific parameter 13 |
| `VIRTUAL_EQUIPMENT_PARAM_14` | `[14]` | Type-specific parameter 14 |

**From app behaviour (2026-08-17, unverified):** The app renders each equipment type differently based on `VIRTUAL_EQUIPMENT_TYPE` (`[0]`). For the pump (type 0) it reads `GROUP_EQUIPMENT_PARAM0` (the speed value) and multiplies by 50 to show RPM, or shows "Priming" when the priming flag is set. This is consistent with the verified ×50 RPM factor and priming flag location from diagnostics, but the display behaviour itself is unverified against live writes.

#### Group config array (field mapping from app behaviour)

> **⚠️ Source note:** The `GROUP_*` field mapping below is **derived from the app's display behaviour (v4.73) and is NOT yet verified against live device writes.** The `config[3]` active-state position is verified by real diagnostics (see F6), but the other field meanings are inferred from the app's constant names and have not been confirmed against the device's write API.

The app's field mapping defines the group config array structure:

| Constant | Array Index | Meaning |
|----------|-------------|---------|
| `GROUP_NAME` | `config[0]` | Group display name |
| `GROUP_NAME_ID` | `config[1]` | Name ID |
| `GROUP_MAX_ACTIVE` | `config[2]` | Max active count |
| `GROUP_STATE` | `config[3]` | Active state (0=off, >0=on) |
| `GROUP_TIME_SET` | `config[4]` | Duration set (seconds) |
| `GROUP_TIME_LEFT` | `config[5]` | Time remaining |
| `GROUP_FREEZE_PROTECTING` | `config[6]` | Freeze protection flag |
| `GROUP_SCHEDULE_MODE` | `config[7]` | Schedule mode |
| `GROUP_EQUIPMENT` | `equip` | Equipment settings dict |

**Confirmed (2026-08-17):** `GROUP_STATE` = `config[3]` matches our `GROUP_IDX_STATE = 3`. The app checks `config[3] > 0` to determine if a group is active. `GROUP_EQUIPMENT` = `equip` confirms the group's equipment settings sub-object.

#### Default display names

The app defines these default names for device types:

| Constant | Value | Device Type |
|----------|-------|-------------|
| `SYNC_DEFAULT_NAME` | `PoolSync®` | Controller |
| `HP_DEFAULT_NAME` | `Heat Pump` | Heat pump |
| `CHLOR_DEFAULT_NAME` | `Chlorinator` | ChlorSync |
| `CHEM_DEFAULT_NAME` | `Chem Controller` | ChemSync |

### 0d. Fault Code Mapping

> **Source:** The fault tables below were derived from how the **vendor's own app (v4.73)** labels and displays faults, and they are treated as **authoritative** for how faults are surfaced to users. The vendor manual's display strings (e.g. "Lo SaLt", "CLn CELL", "NO FLO") are the user-facing subset of the same faults, just with display labels instead of internal identifiers.
>
> **Adjustment policy:** We implement against these tables as-is. If a concrete counter-example ever surfaces (a device reporting a fault code that decodes to an implausible name), we adjust that single entry. We do **not** wait on packet captures or exhaustive fault-code testing — those can never cover every code, so they are not a realistic validation path.

The app decodes a device's `faults[]` array as a **bitmask**. It picks the fault table by device PID, then treats bit *n* of the word (least significant bit first) as the *n*th entry in that table, marking every entry whose bit is set as active.

**PID dispatch:**
- PID `9729` / `9730` (ChlorSync / Chlor Cell) → `CHLOR_FAULTS`
- PID `9731` → `COMM_CHLOR_FAULTS` (multi-cell / comm units)
- PID `10752` (ChemSync) → `CHEM_FAULTS`
- PID `9984` / `9986` (heat pumps, hpc/2700 + hpc/2702) → `HP_FAULTS`
- PID `9985` (heat pump, hpc/2701 — "HP10") → `HP10_FAULTS` (see §0e, **not** `HP_FAULTS`)

**`CHLOR_FAULTS`** (ChlorSync / Chlor Cell):

| Bit | Fault Name |
|-----|-----------|
| 0 | `cellNotConnectedError` |
| 1 | `authFailedError` |
| 2 | `lowTemp` |
| 3 | `CaBuildupError` |
| 4 | `openCellError` |
| 5 | `overCurrentError` |
| 6 | `sensorError` |
| 7 | `powerFailError` |
| 8 | `underVoltageError` |
| 9 | `highSaltWarning` |
| 10 | `cleanCellWarning` |
| 11 | `noFlow` |
| 12 | `lowSaltWarning` |
| 13 | `minSaltError` |

**`CHEM_FAULTS`** (ChemSync):

| Bit | Fault Name |
|-----|-----------|
| 0 | `PCBTemp` |
| 1 | `pHMin` |
| 2 | `pHMax` |
| 3 | `flowSensor` |
| 4 | `pHProbe` |
| 5 | `ORPProbe` |

**`COMM_CHLOR_FAULTS`** (multi-cell / comm units, PID 9731): `lowSalt`, `addSalt`, `highSalt`, `tempSensor`, `noFlow`, then `cpOne…cpNine` × (`CommLoss` / `HighAmps` / `LowAmps` / `CleanCell`), and `noCellsDetected`. *Not currently implemented in the integration — there is no `comm_chlor` device role yet. Documented for reference if multi-cell units are ever detected.*

**`HP_FAULTS`** (heat pump): `lowPressure`, `highPressure`, `lp5Lockout`, `hp5Lockout`, `ds1Open`, `ds1Short`, `ds2Open`, `ds2Short`, `airTempOpen`, `airTempShort`, `highWaterTemp`, `overTempAlarm`, `smartComms`, `multiUnitComms`, `poolSpaInletWaterTempOpen`, `poolSpaInletWaterTempShort`, `solarRoofTempOpen`, `solarRoofTempShort`, `lowClockBattery`, `highHpcPcbTemp`, `highDisplayTemp`, `variableDrive`, `sourceFlow`, `poolSpaOutletTempOpen`, `poolSpaOutletTempShort`, `sourceInletTempOpen`, `sourceInletTempShort`, `sourceOutletTempOpen`, `sourceOutletTempShort`, `sourceInletHighWaterTemp`, `sourceInletLowWaterTemp`, `internalExpansionModule`, `dualTempSensor`, `pump1Comms`, `pump2Comms`, `pump3Comms`, `pump4Comms`, `solarPoolSpaInletTempOpen`, `solarPoolSpaInletTempShort`, `freezeProtectSensorShort`, `freezeProtectSensorOpen`, `multiplePrimaryDetected`, `compressorProtect`, `compressorProtectLockout`.

**Example decode (fault code 512):** 512 = 2⁹ → bit 9 → **`highSaltWarning`** (High Salt Warning). This matches the Beach Spa diagnostic, where the chlorinator reported `saltPPM: 5995` (elevated) with `faults: [512]`.

**Fault-count histogram structure:** The `faultCounts` histogram groups faults into `stats[]` buckets — ChlorSync uses `stats[13–18]` (4 faults per bucket), ChemSync uses `stats[6–8]`. The `CHLOR_FAULTS` field maps to the raw `faults` array in the API payload (confirmed via the `CHLOR_FAULTS: 'faults'` key mapping).

**Multi-word fault arrays:** template indices are *linear*, mapping to `word = floor(i / 32)` and `bit = i % 32`, i.e. `faults[0]` bits 0–31 then `faults[1]` bits 0–11. Any implementation that decodes each array element independently from bit 0 (as the integration did before 2.1.0) mis-decodes `faults[1]` and beyond. HP10 only ever uses `faults[0]`.

---

### 0e. Heat Pump Firmware Families — `HP` (9984/9986) vs `HP10` (9985)

> **Evidence base:** the issue #30 diagnostic capture stored as `tests/sample_diagnostics/hp10-issue30-pump-off.json`, the `t75-*` and `sq160r-*` fixtures, and the app's own UI for the same unit. Every claim below is reproducible from those fixtures.
>
> This section exists because the 2026-11-02 diagnostics in issue #30 proved the integration was decoding a PID **9985** unit with the 9984/9986 layout: integration reported flow=on / compressor=on while the app showed Flow OFF / Compressor OFF / "No Flow" from the *same* payload (`stateFlags: 8`, `ctrlFlags: 4`).

#### 0e.1 PID → firmware family

| PID | Firmware path (`pcfw/…`) | App version table | Model class |
|-----|--------------------------|-------------------|-------------|
| 9984 | `hpc/2700` | version 573, min 568 | `HeatPump` |
| **9985** | `hpc/2701` | **version 275, min 274** | **`Hp10`** |
| 9986 | `hpc/2702` | version 46, min 46 | `HeatPump` |

The hex directory name *is* the PID (`0x2700` = 9984, `0x2701` = 9985, `0x2702` = 9986; likewise `0x1000` = 4096 dongle, `0x2601`–`0x2603` = 9729–9731 ChlorSync, `0x2A00` = 10752 ChemSync). The app selects the parser family from the PID: 9984 and 9986 use the `HeatPump` decoders, 9985 uses the `Hp10` decoders.

The issue #30 unit reports `appFwVersion: 275`, `hwVersion: "E"` — an exact match for the 9985 (2701) entry, independent of `nodeAttr.pid`.

#### 0e.2 How the bit layout was verified (method)

Every flag word (`stateFlags`, `ctrlFlags`, `nodeAttr.flags`, `status.flags`) decodes the same way: the value is read as a binary number and the template's *n*th key is the bit at position *n*, counting from the least significant bit. Bit order is therefore tied to key order in the table, LSB first.

That convention is cross-checked against the 9984/9986 fixtures already in the repo (`t75-heat-pool` `ctrlFlags=13` → flow(0)+compressor(2)+fan(3); `t75-off-*` `stateFlags=1` → `isOff`; `t75-heatpump-fault` `stateFlags=192` → `isFaulted`(6)+`isLockedOut`(7); `t75-spa-startup` `stateFlags=520` → `isHeating`(3)+`isMakeDelay`(9)).

Independent corroboration comes from the HP10 capture in issue #30: `ctrlFlags: 4` and `stateFlags: 8` decode under the HP10 tables to `highPressureLowPressure` and `isWaitFlow`, which is what the app displayed for that unit, while the HP tables read the same two values as "compressor on" and no state at all.

#### 0e.3 `status.stateFlags`

| Bit | `HP` (9984/9986) — `HP_STATE_FLAGS` | `HP10` (9985) — `HP10_STATE_FLAGS` |
|-----|-------------------------------------|------------------------------------|
| 0 | `isOff` | `isOff` |
| 1 | `isWaitFlow` | `isHeating` |
| 2 | `isHolding` | `isHolding` |
| 3 | `isHeating` | `isWaitFlow` |
| 4 | `isCooling` | `isDefrosting` |
| 5 | `isDefrosting` | `isFaulted` |
| 6 | `isFaulted` | `isMakeDelay` |
| 7 | `isLockedOut` | `isLockedOut` |
| 8 | `isRemoteControlled` | `isLocalUIControl` |
| 9 | `isMakeDelay` | — |
| 10 | `isGasHeatingCoolDown` | — |
| 11 | `isWaitSourceFlow` | — |
| 12 | `isFreezeProtecting` | — |

Note the **bit order differs**, not just the names: `isHeating` is bit 3 on `HP` and bit 1 on `HP10`; `isWaitFlow` is bit 1 on `HP` and bit 3 on `HP10`. HP10 also has no cooling, source-flow, gas-cool-down or freeze-protect states, and replaces `isRemoteControlled` with `isLocalUIControl` (local panel takeover).

#### 0e.4 `status.ctrlFlags`

| Bit | `HP` (9984/9986) — `HP_CONTROL_FLAGS` | `HP10` (9985) — `HP10_CONTROL_FLAGS` |
|-----|---------------------------------------|--------------------------------------|
| 0 | `flowSensorOneState` | **`compressorRelayState`** |
| 1 | `flowSensorTwoState` | `fanRelayState` |
| 2 | `compressorRelayState` | **`highPressureLowPressure`** |
| 3 | `fanRelayState` | **`flowSensorOneState`** |
| 4 | `fanSpeedState` | `twoWireEnabled` |
| 5 | `reverseValveState` | `twoWireHeatModeOn` |
| 6 | `flexRelayState` | — |
| 7 | `gasRelayState` | — |
| 8 | `geothermalPSR` | — |
| 9 | `expansionModuleInstalled` | — |
| 10 | `poweredOff` (app label: **"HP10 Panel Off"**) | — |

HP10 is a **6-bit** word. The compressor/fan/flow positions are all different from `HP`, which is exactly why `ctrlFlags: 4` reads as "compressor ON" under the `HP` layout and as "HP/LP pressure input" under `HP10`.

App-side consumers of these bits (for reference): `Flow` row ← `flowSensorOneState`, `Fan` ← `fanRelayState`, `Compressor` ← `compressorRelayState` (+ `compRPM` when `isVS`), Water Temperature row renders **"No Flow"** when `flowSensorOneState` is false. `buildUiStatus` renders the same bits as text rows.

#### 0e.5 `faults[]`

`HP` (9984/9986) → `HP_FAULTS` (44 entries, §0d) spanning `faults[0]` bits 0–31 and `faults[1]` bits 0–11.

`HP10` (9985) → `HP10_FAULTS`, **8 entries, `faults[0]` only**:

| Bit | Key | App card title |
|-----|-----|----------------|
| 0 | `waterSensorOne` | Water Sensor 1 |
| 1 | `waterSensorTwo` | Water Sensor 2 |
| 2 | `ds1Sensor` | Defrost Sensor 1 |
| 3 | `ds2Sensor` | Defrost Sensor 2 |
| 4 | `compressor` | Compressor Fault |
| 5 | `highWaterTemp` | High Water Temperature |
| 6 | `lowPressureHighPressure` | High/Low Pressure |
| 7 | `lp5hp5Lockout` | HP5/LP5 |

Consequence: the integration's HP table maps HP10 bit 0 (`Water Sensor 1`) to "Low Pressure", bit 2 (`Defrost Sensor 1`) to "LP5 Lockout", bit 4 (`Compressor Fault`) to "Defrost Sensor 1 Open", etc.

#### 0e.6 Payload field availability

Diffed against `t75-*` (9984) and `sq160r-*` (9986) fixtures and the issue #30 capture (9985):

| Section | Present on HP10 only | Absent on HP10 (present on HP) |
|---------|----------------------|--------------------------------|
| `status` | `ws1Temp`, `ws2Temp` | `airTemp`, `boardTemp`, `compRPM`, `flowPeriod`, `outletTemp`, `solarTemp`, `geoInlet`, `geoOutlet`, `waterTemp2` |
| `config` | — | `backupHeatMode`, `backupHeatStartTime`, `backupHeatStopTime`, `efficiencyMode`, `extCtrlMode`, `gasBoost`, `multiUnitAddr`, `multiUnitMode`, `poolSpaMode`, `schedAwayEnd`, `schedMode`, `serviceMode`, `solarMode`, `solarSetpoint`, `spaSetpoint`, `turboBoost` |
| `system` | — | `compModelNum`, `dispFwVersion` |

On HP10 `waterTemp` duplicates `ws1Temp` (both 87.3 in the capture) with `ws2Temp` ~0.3 °F lower; `ds1Temp`/`ds2Temp` are still present (89.06 / 86.64).

#### 0e.7 Model-class differences (`HP` vs `HP10`)

| Property | `HP` | `HP10` |
|----------|------|--------|
| `isHeatPump` / `isHeatPump10` | true / false | false / true |
| `availableHeatModes` | from model number via `getHeatModesFromModel()` — `…H…` → `['OFF','HEAT','COOL','AUTO']`, `…C…` → `['OFF','COOL']`, else `['OFF','HEAT']` | hardcoded `['OFF','HEAT']` |
| `isVS` | model chars `-5..-4` ∈ {`V`,`Y`} | **always false** |
| `isSubUnit` | `multiUnitMode === 2` | **always false** |
| `isPhase2` | `pid === 9986 \|\| appFwVersion` in 512…767 | **always true** |
| `logicIdSupport` | `pid === 9986 \|\| appFwVersion >= 518` | **always true** |
| `remoteControl` | `getHpRemoteControlStatus(extCtrlMode, mode)` | always false |
| `compRPM`, `flowPeriod`, `efficiencyMode`, `gasBoostMode`, `multiUnitAddr/Mode`, `poolSpaMode`, `displayVersion`, `compressorModel` | parsed | zero/undefined |
| `maxTemp` / `minTemp` fallback | 110 / 60 | 110 / 60 (payload supplies 104 / 60) |

`getHpRemoteControlStatus(extCtrlMode, mode)` compares `extCtrlMode` against `2` and `{2,4}` and `mode` against `{1,3}`; it is only ever non-zero for `HP` (HP10 hardcodes `remoteControl = false`). The exact truth table has not been pinned down — treat it as “remote/external control active”.

#### 0e.8 App UI differences driven by `isHeatPump10` / `isPhase2`

- **Status banner priority** (heat-pump screen): powered off → locked out → faulted → two-wire → sub-unit, where
  - "System is Powered Off" = `isHeatPump10 && isOff` (HP10) — the exact string users see when the panel/unit reports off,
  - "System Locked Out" = `isHeatPump10 && !isOff && isLockedOut`,
  - "two-wire" = `isHeatPump10 && !isOff && !isLockedOut && twoWireEnabled`,
  - HP10 does **not** use `ctrlFlags` bit 10 for this; HP's `poweredOff` bit has no HP10 equivalent.
- **Faulted banner** uses `faults.waterSensorOne || faults.waterSensorTwo` on HP10 (i.e. water-sensor faults only), not `isFaulted`.
- **Controls disabled** when `(isHeatPump10 && isOff) || (isHeatPump10 && isLockedOut) || isFaulted`.
- **Setpoint writes**: `isPhase2` ⇒ always write `config.setpoint`; otherwise write `spaSetpoint` when `poolSpaMode !== 0`. Writes are refused when `!isOnline` or `isFreezeProtecting`.
- **Slider label**: `isPhase2` → "Setpoint"; else "Pool Setpoint"/"Spa Setpoint". Because T75 fw 563 also satisfies `isPhase2`, the T75 shows a single "Setpoint" too.
- **Settings rows** (heat-pump settings screen): `Compressor` (RPM), `Flow Hours`, `Efficiency Mode`, `Compressor Model` require `isVS && !isSubUnit`; `Schedule Mode` requires `!isPhase2 && !isSubUnit`; `Logical ID` requires `logicIdSupport`; `Gas Boost` requires `!isPhase2 && !isSubUnit` (shown on phase-2 units even though HP10 has no `gasBoost` field).
- **HP10 status detail list** is a distinct 20-row set: Off, Heating, Holding Setpoint Temp, Waiting for Flow, Defrosting, Faulted, Make Delay, Locked Out, Local UI Control, Compressor Relay State, Fan Relay State, HP/LP, Flow Sensor 1 State, Two-Wire Enabled, Two-Wire Heat Mode, Water Temp, Water Sensor 1/2 Temp, Defrost Sensor 1/2 Temp.
- HP10 shows **no** `Compressor Speed`, `Flow Period (3-day avg)`, `Outlet Water Temp`, `Ambient Air Temp`, `Solar Temp`, `Board Temperature` rows (those belong to the `HP` list).

#### 0e.9 What the 2026-11-02 payload decodes to

Capture: `pid 9985`, `stateFlags: 8`, `ctrlFlags: 4`, `faults: [0]`, `waterTemp: 87.3`, `ws1Temp: 87.3`, `ws2Temp: 86.98`.
This capture is stored as `tests/sample_diagnostics/hp10-issue30-pump-off.json`.

| Signal | `HP` layout (integration 2.0.1 and earlier) | `HP10` layout (app, and integration after the PID-aware fix) |
|--------|--------------------------------|---------------------|
| flow | on (`ctrlFlags != 0`) | **off** (bit 3 clear) |
| compressor | on (bit 2) | **off** (bit 0 clear) |
| fan | off (bit 3) | off (bit 1 clear) |
| state | — | `isWaitFlow` (bit 3) |
| ctrl bit 2 | compressor | `HP/LP` pressure input |
| water temp | 87.3 shown | "No Flow" |

---

## 0. Architecture: Device Type Registry & Multi-Device Model

### 0.1 Device Type Registry

Device role resolution is driven by a `DEVICE_TYPE_REGISTRY` dict in `runtime.py` — a single source of truth mapping API `deviceType` strings to internal metadata:

```python
DEVICE_TYPE_REGISTRY = {
    "chlorSync": DeviceTypeInfo(role_key="chlorinator", ...),
    "heatPump":  DeviceTypeInfo(role_key="heat_pump", ...),
    "chemSync":  DeviceTypeInfo(role_key="chem_sync", ...),
}
```

A reverse `ROLE_KEY_REGISTRY` provides O(1) lookup from `role_key` → `DeviceTypeInfo`. Adding a new device type is a single block addition. Unrecognized `deviceType` values are logged at DEBUG and gracefully skipped.

### 0.2 Parsed Data Model

`PoolSyncParsedData` stores devices in a dict keyed by `role_key`:

```python
@dataclass
class PoolSyncParsedData:
    system: PoolSyncSystemData
    devices: dict[str, list[PoolSyncDeviceRoleData]]
```

Each `PoolSyncDeviceRoleData` includes `node_addr` (from `nodeAttr.nodeAddr`) and `index` (ordinal position within the role) for stable disambiguation.

### 0.3 Device Identification

Device registry identifiers and entity unique IDs follow this pattern:

| Instance | Device Identifier | Entity Unique ID |
|----------|------------------|-----------------|
| First chlorinator | `{mac}_chlorinator` | `{mac}_water_temp` |
| Second chlorinator | `{mac}_chlorinator_19` | `{mac}_chlorinator_19_water_temp` |
| First heat pump | `{mac}_heat_pump` | `{mac}_hp_water_temp` |
| ChemSync | `{mac}_chem_sync_21` | `{mac}_chem_sync_21_chem_ph` |

The first instance of legacy roles (`chlorinator`, `heat_pump`) keeps its existing identifier format for backward compatibility. Subsequent instances append `nodeAddr`. Newer types (e.g., `chem_sync`) always use the disambiguated format.

### 0.4 Value Getter Factory

Device-scoped value getters are created via the `_dv()` factory:

```python
"water_temp": _dv("chlorinator", "status", "waterTemp"),
"chem_ph":    _dv("chem_sync", "status", "ph"),
```

The factory accepts a closure-time `index` parameter and runtime kwargs override (`role_key`, `index`) from the public `get_sensor_value()` / `get_binary_sensor_value()` / `get_number_value()` functions.

---

## 1. Implemented: Device Pairing & System Sensors

All of these are built and tested. Data source for each is noted.

### 1.1 Push-Link Pairing (Discovery → Config Entry)

| Step | Endpoint | Key Data | Reference |
|------|----------|----------|-----------|
| Start push-link | `PUT /api/poolsync?cmd=pushLink&start` | `status: "ok"` on success | `api.py:start_pushlink()` |
| Poll for button press | `GET /api/poolsync?cmd=pushLink&status` | `timeRemaining` (seconds), `password` (once pressed) | `config_flow.py:_async_poll_pushlink()` |
| Timeout | — | 120 s max; poll every 5 s | `const.py:PUSHLINK_*` |

Once the user presses the physical button, the API returns the device `password` which is stored in the config entry. The `macAddress` from the full data payload (`GET /api/poolsync?cmd=poolSync&all`) is used as the unique ID.

> **Method correction (verified 2026-10-11 against app v4.73 and `api.py`):** `pushLink&start` is a **PUT**, not a GET as previously recorded. This table, `const.py:API_PATH_PUSHLINK_START`, and the app's own push-link start call all agree. The header set for `&start` is `User` only — `Authorization` is not sent, since the password does not exist yet.
>
> The app also closes the session with `PATCH /api/poolsync?cmd=pushLink&end`. The integration does not currently call `&end`; on a timeout the link session is left open on the device, which is a plausible cause of a subsequent `&start` returning HTTP 400 with an empty body.
>
> Related device-side state resets (not currently used by the integration): `DELETE /api/poolsync?cmd=pushLink` (app `legacy_resetHashAPI`, clears the local auth hash) and `POST /api/dongle/link` with body `{"reset": true}` (app `resetHash`).

#### 1.1a Pairing instructions are selected by UI host, not by model

The authorization button differs per hardware variant, and the app has **two** screens that encode this: the legacy
"Device Linking" screen, keyed on `status.remoteUiPid`, and the setup wizard, keyed on the wizard's own device type.
The text below is quoted as it appears on screen; which branch shows it is our description of the app's behaviour.

**Legacy linking screen — selected by `status.remoteUiPid`:**

| `remoteUiPid` | Instruction shown |
|---------------|-------------------|
| `4096` | "Press and hold the Service Button (middle button) on your <defaultName> for 3 seconds before the timer runs out to authorize this device. You will need to authorize all mobile devices you wish to access this <defaultName>." |
| `9986` | "Press AUTH on the heat pump display:" + "Tip: If the POOLSYNC AUTHORIZE screen does not appear then navigate to the POOLSYNC WIFI menu screen or the MAIN status screen of the heat pump." |
| `9731` | "Press Yes on the chlorinator display to authorize this device:" + "Tip: If the POOLSYNC AUTHORIZE screen does not appear then press the MENU button and navigate to the Network setting, press Select, navigate to the Authorize setting and press Select." |
| anything else | progress bar only, no instruction text |

**Setup wizard — selected by the wizard's device type.** The two screens agree, which cross-validates the mapping:

| Wizard type | `remoteUiPid` | UI host | Instruction | Illustration asset |
|-------------|---------------|---------|-------------|--------------------|
| `wall` | `4096` | PoolSync controller (standalone wall unit, or built into the heat pump) | hold **Service (middle)** button ~3 s | `images.pushLink1` / `pushLink2`, `instructionImage(_new)` |
| `embedded` | `9986` | Heat pump display | press **AUTH** on the heat pump display | `images.embeddedAuth` |
| `commChlor` | `9731` | Chlorinator display | press **Yes** on the chlorinator display | `images.commChlorAuth` |
| anything else | — | — | **no instruction text at all** (progress bar only) | — |

Corrections to earlier notes in this document: `embeddedAuth` and `commChlorAuth` are *image asset names*, not
setup types; `hwVersion === '3.0'` does **not** select text — inside the 4096 branch it only picks between two
illustration variants (`pushLink1`/`pushLink2` and `instructionImage`/`instructionImage_new`).

**There is no 10-second hold in app v4.73.** The only durations in any instruction are:

| Duration | Operation | Verbatim |
|----------|-----------|----------|
| 3 s | authorize (both pairing screens) | "…for 3 seconds before the timer runs out to authorize this device…" |
| 15 s | enter **Wi-Fi setup mode** (device-selection step, asset `tropicSetupLights`) | "are flashing. If not, hold the button for 15 seconds or until they flash." — preceded by "Press the Setup button on the physical device to begin. The third light will turn on once in setup mode." and "Do not press the setup button." (when already on Wi-Fi) |
| 30 s | software restart | "Do you want to restart your device? This may take up to 30 seconds before you can use it again." |

Button names used by the app (`SYNC_FLAGS` labels + `stats` counters): **Connect**, **Service**,
**Service Access**, **Setup**. The pairing text refers to the Service button as the "middle" button.

**Field observations vs the app text:**

| Unit | `remoteUiPid` | `hwVersion` | What actually worked |
|------|---------------|-------------|----------------------|
| T75 / 075AHDSBLH (standalone controller, project owner) | 4096 | 2.0 | single AUTH press |
| 090 system | 4096 | 3.0 | not reported |
| SQ160R (heat pump hosts the UI) | 9986 | 3.0 | not reported |
| Issue #30 AquaCal 055AHDSBLH (integrated) | 4096 | 3.0 | AUTH alone did nothing; **Service, then AUTH** worked (2026-11-02) |

The app's text for `4096`/`wall` (hold Service ~3 s) matches the issue #30 unit. The standalone T75 accepts a
single AUTH press, so on at least some controller hardware either action authorizes. The integration therefore
cannot name one universal button and states the app's per-host instruction plus that fallback.

#### 1.1b Authorized clients (why a re-pair can break an existing client)

- Each successful `pushLink` authorizes **one client** and hands back the password. The app's copy: *"You will need to authorize all mobile devices you wish to access this `<device>`"*, and the setup wizard has a step *"Clear all previously authorized users who can remotely access the device."*
- That step is `DELETE /api/poolsync?cmd=pushLink` (the app's "clear authorized users" / auth-hash reset call), sent **with** `Authorization` + `User` headers. Full device wipe is `DELETE /api/poolsync?cmd=factoryReset`.
- Practically: if a device is re-paired from the app or the user runs the "clear authorized users" step, the password stored in the Home Assistant config entry may be invalidated. Symptom would be HTTP 401 / `ConfigEntryAuthFailed`, **not** frozen values or connection refused.
- The dongle also exposes `poolSync.config.authorized` (mapped by `AUTHORIZED`) in newer firmware; absent in the 864-firmware payload from issue #30.

#### 1.1c Local API surface used by the app v4.73

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/api/poolsync?cmd=poolSync&all` | GET | full snapshot; same path the integration uses (`API_PATH_ALL_DATA`) |
| `/api/poolsync?cmd=poolSync` | PATCH | controller-level config writes |
| `/api/poolsync?cmd=changeStatus` | GET | lightweight change check (not used by the integration) |
| `/api/poolsync?cmd=devices&device={id}` | GET / PATCH | per-device read/write; PATCH sends `Content-Type: application/json` + `Authorization` + `User` |
| `/api/poolsync?cmd=discover` | GET | ask the dongle to re-scan attached equipment |
| `/api/poolsync?cmd=restart` | GET | software restart ("may take up to 30 seconds") |
| `/api/dongle`, `/api/dongle/state`, `/api/dongle/devices/{id}` | GET/PUT | newer API; the app falls back to it on HTTP 404 from the legacy path |
| `/api/dongle/software_restart`, `/api/dongle/factory_reset` | POST/DELETE | newer equivalents |

When the app writes a device setting it also syncs the cloud shadow; only the local PATCH changes the device itself.

#### 1.1d Dongle-side state worth reading during pairing / comms troubleshooting

`poolSync.status.flags` (`SYNC_FLAGS`) is a 5-bit word the integration currently ignores:

| Bit | Key | Meaning |
|-----|-----|---------|
| 0 | `isUpdating` | device/shadow update in progress |
| 1 | `connectButtonPressed` | Connect button currently held |
| 2 | `serviceButtonPressed` | Service button currently held |
| 3 | `serviceAccessButtonPressed` | Service-Access button currently held |
| 4 | `setupButtonPressed` | Setup button currently held |

Polling this while the user presses a button would conclusively show whether the press reached the dongle ("I pressed AUTH and nothing happened" vs "the dongle never saw it"). Cumulative press counters already exist in `poolSync.stats`: `numConnectButtonPresses`, `numServiceButtonPresses`, `numServiceAccessButtonPresses`, `numSetupButtonPresses` (issue #30 unit: 4 / 2 / 5 / 0).

Other per-device comms counters: `stats.numDeviceMsgNoResp`, `stats.numDeviceOffline`, `stats.lastOfflineDevPid`, `stats.lastOfflineDevAddr`, `stats.device0CommErrors` … `device7CommErrors`, plus `numDeviceCmdErrResp`. The app labels these "Num Device MSG No Resp", "Num of Times Devices Offline", "Last Offline Dev PID/Addr".

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

### 1.4 ChlorSync Sensors (one set per detected device)

When one or more `"chlorSync"` entries are found in the `deviceType` map, sensors are created for each device. The first chlorinator keeps backward-compatible entity IDs; subsequent ones append `nodeAddr` to their unique IDs. Example unique IDs:

| Instance | Sensor Example |
|----------|---------------|
| First chlorinator | `sensor.poolsync_water_temperature` (unique ID: `{mac}_water_temp`) |
| Second chlorinator (nodeAddr 19) | `sensor.poolsync_chlorinator_19_water_temperature` (unique ID: `{mac}_chlorinator_19_water_temp`) |

Device names are de-duplicated: two "ChlorSync" units become "ChlorSync" and "ChlorSync 2".



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

| Control | Key | Write Path | Multi-Device |
|---------|-----|------------|-------------|
| Output % | `chlor_output_control` | `PATCH /api/poolsync?cmd=devices&device={id}` → `config.chlorOutput` | Supports `index` param; each chlorinator number entity targets its own device |

When multiple chlorinators are present, each gets its own number entity. The `index` parameter (0-based, matching the device's position in `parsed_data.devices["chlorinator"]`) is passed through the coordinator write methods to target the correct API device ID.

---

## 2. Implemented: Heat Pump Control

### 2.1 Device Role Detection

Device roles are resolved from the `deviceType` map via `_resolve_device_types()` in `runtime.py`. All `deviceType` entries are iterated in sorted numeric order and looked up in `DEVICE_TYPE_REGISTRY`. Example payload:

```json
"deviceType": {"0": "heatPump", "1": "chlorSync"}
```

Multiple devices of the same type are supported (e.g., two heat pumps). Each gets its own climate entity, mode select, and temperature entities. All heat-pump runtime functions accept an `index` parameter to read from the correct device.

**Reference:** `runtime.py:_resolve_device_types()`, `runtime.py:DEVICE_TYPE_REGISTRY`
**Previously:** `_resolve_device_role_ids()` returned only the first match per type — any second chlorSync was silently dropped. This was replaced by `_resolve_device_types()` which maps `{role_key: [device_id, ...]}`.

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

The bit order is selected by `nodeAttr.pid` (see §0e). `runtime.get_heat_pump_flag_layout()`
returns `hp` for 9984/9986 (and for a missing PID) and `hp10` for 9985.

| Bit (`hp`) | Mask | Meaning | Entity |
|------------|------|---------|--------|
| 0 | 1 | `flowSensorOneState` → `has_flow` | `binary_sensor.heatpump_flow` |
| 2 | 4 | Compressor engaged | `binary_sensor.heatpump_compressor` |
| 3 | 8 | Fan running | `binary_sensor.heatpump_fan` |

| Bit (`hp10`) | Mask | Meaning | Entity |
|--------------|------|---------|--------|
| 0 | 1 | Compressor engaged | `binary_sensor.heatpump_compressor` |
| 1 | 2 | Fan running | `binary_sensor.heatpump_fan` |
| 2 | 4 | `highPressureLowPressure` (HP/LP input) | `binary_sensor.*_high_low_pressure` (diagnostic) |
| 3 | 8 | `flowSensorOneState` → `has_flow` | `binary_sensor.heatpump_flow` |

`has_flow` is the dedicated flow-sensor bit — never `ctrlFlags != 0`. Other control
bits (expansion module, gas/geothermal relays, fan speed, HP/LP) do not imply flow.

Bit 2 on HP10 is the **live** pressure-switch input (the app's own "HP/LP" status
row), which is a different thing from the **latched** fault at `faults[0]` bit 6
(`lowPressureHighPressure`). It is exposed as a diagnostic binary sensor so
captures can settle what it means; see §7.3 Q2. It reports `None` on HP, where no
such bit exists.

**Sample evidence:**
- t75-heatpump-fault.json: `ctrlFlags=1` → bit 0 only → flow on, compressor and fan off
- t75-spa-startup: `ctrlFlags=9` → bits 0 and 3 → flow + fan, compressor off (`stateFlags=520` is a separate word)
- 090 compressor on: `ctrlFlags=909` → bits 0,2,3,7,8,9 → flow + compressor + fan (bits 7-9 are gas/geothermal/expansion relays)
- **090 all off: `ctrlFlags=512` → bit 9 only → no flow** — regression case for the previous `ctrlFlags != 0` rule, which reported flow on a switched-off unit
- hp10-issue30-pump-off.json: `ctrlFlags=4` → bit 2 only → HP/LP input; flow, compressor and fan all off

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

## 3. ChemSync (pH/ORP) Support

Added in Phase 2 of the device refactor. Detected when `deviceType` contains a `"chemSync"` entry. The chemSync is exposed through the standard `DEVICE_TYPE_REGISTRY` with `role_key="chem_sync"`, and entities are created by the same per-device iteration pattern used for chlorinators and heat pumps.

### 3.1 Raw Payload Structure

```json
{
  "nodeAttr": { "name": "Chemistry", "nodeAddr": 21, "online": true },
  "status": { "ph": 8.16, "orp": 709, "boardTemp": 114.41, "acidConsumed": 1941 },
  "system": { "modelNum": "ChemSync", "fwVersion": 533, "hwVersion": "F" },
  "config": { "phSetpoint": 7.2, "orpSetpoint": 650, "flowSensorEnable": true },
  "faults": [4]
}
```

**Reference:** Issue #6 payload, `runtime.py:DEVICE_TYPE_REGISTRY`

### 3.2 ChemSync Sensors

| Sensor Key | Source Path | Unit | Device Class |
|------------|-------------|------|-------------|
| `chem_ph` | `status.ph` | — (logarithmic) | `PH` |
| `chem_orp` | `status.orp` | mV | — |
| `chem_board_temp` | `status.boardTemp` | °F | `temperature` (diagnostic) |
| `chem_acid_consumed` | `status.acidConsumed` | fl. oz. | — (MEASUREMENT) |

### 3.3 ChemSync Binary Sensors

| Sensor Key | Source Path | Device Class | Logic |
|------------|-------------|-------------|-------|
| `chem_sync_online` | `nodeAttr.online` | CONNECTIVITY | Bool |
| `chem_sync_fault` | `data.faults[]` | PROBLEM | Any non-zero |
| `chem_sync_flow` | `config.flowSensorEnable` | — | Bool |

### 3.4 Write Controls (Not Yet Implemented)

The config payload includes `phSetpoint` and `orpSetpoint` fields that may be writable via the same `PATCH /api/poolsync?cmd=devices&device={id}` → `config.{key}` pattern. These have not been tested. Number entities can be added once confirmed.

---

## 4. New Findings from 090 System (Unconfirmed)

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

Raw array (actual values from 1750 RPM sample):
```
[0, "CIRCULATION PUMP", 2, 1, 0, 0, 0, 35, 12, 69, 69, 5, 58, 0, 0]
```

⚠️ **All field names below are inferred from observed behavior, not from any documentation or API schema.** The data is a positional array with no named keys.

| Index | Inferred purpose | 1750 RPM | 3450 RPM (priming) | 2900 RPM | Basis for inference |
|-------|-----------------|----------|---------------------|----------|---------------------|
| 0 | Equipment type | 0 | 0 | 0 | Constant: always 0 |
| 1 | Display name | "CIRCULATION PUMP" | "CIRCULATION PUMP" | "CIRCULATION PUMP" | String, matches device labeling |
| 2 | Unknown | 2 | 2 | 2 | Constant; possibly pump class (2=VS) |
| 3 | Unknown | 1 | 1 | 1 | Constant |
| 4–6 | Unknown | 0,0,0 | 0,0,0 | 0,0,0 | Always zero in these samples |
| 7 | **Current speed** | 35 | 69 | 58 | **Changes across samples; ×50 matches filename RPM values** |
| 8 | Minimum speed | 12 | 12 | 12 | Constant; lowest value seen (12×50=600 RPM) |
| 9 | Maximum speed | 69 | 69 | 69 | Constant; highest value seen (69×50=3450 RPM) |
| 10 | Unknown | 69 | 69 | 69 | Same as index 9; possibly default max |
| 11 | Unknown | 5 | 5 | 5 | Constant; very low (5×50=250 RPM) — possible soft-start |
| 12 | Unknown | 58 | 58 | 58 | Constant; mid-range (58×50=2900 RPM) |
| 13 | Unknown | 0 | 0 | 0 | Always zero |
| 14 | **Flag** | 0 | 1 | 0 | **Correlates with priming state in filename** |

**Only indices 7 and 14 are confirmed to change with operating state.** Indices 8–12 are constant across all three samples — they're likely static capability values (min/max RPM, etc.) but this is unconfirmed. Indices 2–6, 10, and 13 have unknown purpose.

**RPM factor confirmed as ×50:** 35→1750, 58→2900, 69→3450 — all three match the filenames from the user. **Also confirmed from the app (2026-08-17):** the pump display reads the speed value and multiplies by 50 to render RPM, and shows "Priming" when the priming flag is set.

**Manual override (2026-08-15, VERIFIED):** A diagnostic with a manual pump override to 2000 RPM shows `raw[7]=40` (40×50=2000) while only the POOL group is active (which would normally run at 1750). This confirms manual override is reflected in `raw[7]`. Notably, in the manual-override sample `raw[5]=2147483640` (≈0x7FFFFFF8, near INT32_MAX) and `raw[6]=4294896` — large/garbage values that appear to flag manual-override mode, distinct from the group-driven case where `raw[5]=300` (the group's RPM setting) and `raw[6]=0`. This flag is not yet decoded.

**✅ Manual RPM write path (CONFIRMED from user packet capture, 2026-09-01):** The user captured the exact PATCH payloads the app sends to `?cmd=devices&device=0`:

```json
// Manual override to 1800 RPM
{"equip": {"1": [36, 4294967295]}}

// Back to auto
{"equip": {"1": [0, 0]}}

// Turn pump off
{"equip": {"1": [0, 4294967295]}}
```

**Key findings (all confirmed):**
- The write targets the **`equip` array**, keyed by the pump's equipment slot (`"1"`)
- The first element is the **speed ÷ 50** (36×50=1800 RPM)
- The second element is a **flag**: `4294967295` (0xFFFFFFFF, int32 −1) = manual override/on, `0` = auto
- This **supersedes** the earlier guess that the write key was `config.rpm` — the actual format is `equip.{slot} = [rpm/50, flag]`

**Proposed entities:** `sensor` for current pump RPM (index 7 × 50), `binary_sensor` for priming flag (index 14), `number` for RPM control (now has confirmed write format).

#### F2. Motorized Return Valve (equipment type 1)

**Source:** `devices[0].equip["3"]`

Raw array:
```
[1, "RETURN VALVE", 1, 0, 1, 300, 0, 0, "FOUNTAIN", 3, "POOL", 0, 0]
```

⚠️ **All field names below are inferred.** Positional array, no named keys.

| Index | Inferred purpose | Value | Basis |
|-------|-----------------|-------|-------|
| 0 | Equipment type | 1 | Constant: valve/actuator |
| 1 | Display name | "RETURN VALVE" | String |
| 2–4 | Unknown | 1, 0, 1 | Constant |
| 5 | Movement time | 300 | Likely milliseconds for actuator travel |
| 6 | Unknown | 0 | Constant |
| 7 | **Current position index** | 0 or 1 | **1-based index into named positions; 0 = default (last). Confirmed 2026-08-15: FOUNTAIN active → 1, POOL → 0** |
| 8 | Position A name | "FOUNTAIN" | Named position in active groups |
| 9 | Position A value | 3 | Matches valve setting in WATERFALL/AMBIANCE groups |
| 10 | Position B name | "POOL" | Named position in active groups |
| 11 | Position B value | 0 | Matches valve setting in POOL group |
| 12 | Unknown | 0 | Constant |

**⚠️ Write key gap:** Same issue as F1. Additionally, user feedback (2026-07-15) indicates **valve position is not independently controllable** — it's a side effect of group membership. Changing the valve requires changing which groups are active. An independent write control would not work.

**✅ Current position is reported directly (2026-08-15):** The valve equipment entry reports its current position via `raw[7]` — a 1-based index into the named positions list, where `0` means the default (last) position. This is **authoritative and independent of active groups**, so it is correct even when multiple groups with conflicting valve settings are active simultaneously. This supersedes the earlier approach of deriving the position from the active group's `equip["3"][0]` setting, which returned the wrong value (POOL) when POOL + WATERFALL were both active and the valve was actually at FOUNTAIN.

**Proposed entities:** `sensor` for current position (from `raw[7]`, mapped through named positions). No select control.

#### F3. Groups as Combined Equipment Scenes

**Source:** `devices[0].groups["0".."5"]`

Group config array: `[name, nameId, maxActive, state, timeSet, timeLeft, freezeProtecting, scheduleMode]`

The field names are **confirmed** from the app's `GROUP_*` field mapping (see "Group config array" section above).

| Index | Field | Range |
|-------|-------|-------|
| 0 | Name | "POOL", "WATERFALL", "FILTRATION", "AMBIANCE", "CLEANER" |
| 1 | Name ID | 0, 22, 2, 8, 3 |
| 2 | Max active | 192, 24, 32, 48 |
| 3 | State | 0=off, 1=active (filtration), 2=active with heat |
| 4 | Time set | Seconds (172800=48h, 14400=4h, 5400=90m, 900=15m) |
| 5 | Time left | Seconds remaining |
| 6 | Freeze protecting | 0/1 |
| 7 | Schedule mode | 0=manual, 1=scheduled |

Group equip sub-object maps equipment IDs to settings for that group:

| Group | equip[1] RPM (×50) | Real RPM | equip[3] Valve | equip[0] Heat Pump |
|-------|--------------------|----------|----------------|---------------------|
| POOL | [35, 0] | 1750 | [0, 0] = POOL | [1, 84] = heat, 84°F |
| WATERFALL | [60, 0] | 3000 | [3, 0] = FOUNTAIN | — |
| FILTRATION | [35, 0] | 1750 | — | — |
| AMBIANCE | [44, 0] | 2200 | [3, 0] = FOUNTAIN | — |
| CLEANER | [69, 0] | 3450 | — | — |

**⚠️ User feedback (2026-07-15): Groups are additive, not mutually exclusive.** Multiple groups can be active simultaneously. The device merges settings from all active groups (highest temperature, fastest pump RPM, and an unknown merge strategy for valve positions). Our initial "mutual exclusion" conclusion was based on three snapshots that happened to only have one group active at a time.

**Proposed entities:** `sensor` for active group names (comma-separated). `select` for group activation (deferred — requires API key discovery).

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

**From app behaviour (2026-08-17, unverified):** The app renders `VIRTUAL_EQUIPMENT_TYPE` (`[0]`) with distinct branches for types 0, 1, 2, and 3. Types 0 (pump) and 1 (valve) are **verified** by real diagnostics; types 2 and 3 are inferred from what the app displays for them.

| Type | Name | Seen In | Notes |
|------|------|---------|-------|
| 0 | Variable Speed Pump | equip[1] | **Verified** — Internal RPM × 50 = real RPM; priming flag at param1 |
| 1 | Valve/Actuator | equip[3] | **Verified** — Named positions, timed movement |
| 2 | (unknown) | — | All null in 090; possibly single-speed pump, light, or booster |
| 3 | Heat Pump | equip[0] | Already handled by existing integration |
| 4–15 | (unknown) | — | All null in 090; may include lights, solar valves, chemical feeders, additional heat pumps |

#### F6. Group index 3 Active State Semantics

**Verified (2026-08-17):** `GROUP_STATE` = `config[3]`. The app checks `config[3] > 0` to determine if a group is active (confirmed by both diagnostics and the app's constant name). Any positive value is active. What distinct values 1, 2, etc. mean is unclear — they may encode priority, activation source (manual vs schedule), or a sub-state. User testing confirmed groups are additive, so state values do not imply mutual exclusion.

| Value | Meaning | Evidence |
|-------|---------|----------|
| 0 | Inactive | All non-active groups across all 3 samples |
| 1 | Active | FILTRATION group in files 1 and 2 |
| 2 | Active (different priority/source) | POOL group in file 3 (mode=1, compressor on) |

**⚠️ Update (2026-09-02):** The state value does **not** encode schedule-vs-manual. Both a scheduled run (FILTRATION, state=1, pump in auto) and a manual run (POOL, state=2, pump in manual) have `schedMode=1`. The reliable indicator of manual operation is the **pump's manual-override sentinel** (`equip[1][5] = 0x7FFFFFF8`, see F1) — when the pump is in manual mode, the active group was started manually, not by the schedule. The distinct state values 1 vs 2 remain unexplained (possibly priority or activation sub-state).

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

**Time encoding (RESOLVED by packet capture, 2026-09-02):** Each time value packs the minute and hour into a single integer:

```
value = minute * 256 + hour
```

Verified against the user's captured schedule edits (see F7a):
- `22` = 0·256 + 22 → **10:00pm**
- `3862` = 15·256 + 22 → **10:15pm**
- `21` = 0·256 + 21 → **9:00pm**
- `3861` = 15·256 + 21 → **9:15pm**
- `7698` = 30·256 + 18 → **6:30pm**
- `7699` = 30·256 + 19 → **7:30pm**

This retroactively explains the diagnostic values that previously looked like garbage:
- `3848` = 15·256 + 8 → **8:15am** (FILTRATION)
- `7688` = 30·256 + 8 → **8:30am**
- `11528` = 45·256 + 8 → **8:45am**
- `11527` = 45·256 + 7 → **7:45am** (POOL)

#### F7a. Schedule Write Path (CONFIRMED from user packet capture, 2026-09-02)

**✅ CONFIRMED:** The user captured the exact PATCH payloads the app sends to `?cmd=devices&device=0` for schedule control. The CLEANER group (key `"5"`) runs 4 daily schedules at 4–4:15am, 10–10:15am, 4–4:15pm, and 10–10:15pm.

**Schedule on/off (per group):** toggles the group's `schedMode` (`config[7]`):

```json
// Turn OFF CLEANER group schedule
{"groups": {"5": {"schedMode": 0}}}

// Turn ON CLEANER group schedule
{"groups": {"5": {"schedMode": 1}}}
```

**Schedule slot edit (per group, per slot):** replaces a slot's `[dayMask, startTime, endTime]` array:

```json
// Remove Monday from 4th schedule block of CLEANER
{"schedules": {"5": {"3": [125, 22, 3862]}}}

// Remove Monday from 3rd schedule block of CLEANER
{"schedules": {"5": {"2": [125, 16, 3856]}}}

// Add Monday back to 3rd schedule block of CLEANER
{"schedules": {"5": {"2": [127, 16, 3856]}}}

// Add Monday back to 4th schedule block of CLEANER
{"schedules": {"5": {"3": [127, 22, 3862]}}}

// Clear 4th schedule block line of CLEANER (dayMask=0 disables it)
{"schedules": {"5": {"3": [0, 22, 3862]}}}

// Change 4th schedule block to all days, 9:00 to 9:15pm
{"schedules": {"5": {"3": [127, 21, 3861]}}}

// Change 4th schedule block to all days, 6:30 to 7:30pm
{"schedules": {"5": {"3": [127, 7698, 7699]}}}
```

**Key findings (all confirmed):**
- The schedule write uses a **`schedules` key** with the shape `schedules.{groupKey}.{slotIndex} = [dayMask, startTime, endTime]`
- The schedule on/off uses a **`groups` key** with `groups.{groupKey}.schedMode = 0|1` — this is the group's `config[7]` schedule-mode field
- Day masks confirmed: `62`=Mon–Fri, `65`=Sat+Sun, `125`=all-but-Mon, `127`=all days, `0`=disabled
- The endpoint is `?cmd=devices&device=0` (the heat pump device), same as group state (F10a)
- This **resolves** the earlier open question about the schedule write format (F11)

---

### 🟠 MEDIUM CONFIDENCE — Reasonable inference

#### F8. Group index 1 Is the Name ID

**From app behaviour (2026-08-17, unverified):** `GROUP_NAME_ID` = `config[1]`. Values: 0 (POOL), 22 (WATERFALL), 2 (FILTRATION), 8 (AMBIANCE), 3 (CLEANER). Not obviously bitmask-mapped to equipment types. Could be a group category/preset ID. The index position is verified by diagnostics; the semantic meaning is inferred from the app's constant name.

#### F9. Group index 2 Is Max Active

**From app behaviour (2026-08-17, unverified):** `GROUP_MAX_ACTIVE` = `config[2]`. Values: 192 (POOL/FILTRATION), 24 (WATERFALL), 32 (AMBIANCE), 48 (CLEANER). Does not match RPM (RPM comes from equip sub-object). Could be GPM target, priority, or display category. The index position is verified by diagnostics; the semantic meaning is inferred from the app's constant name.

#### F10. Group Duration Is Auto-Shutoff Timer

**From app behaviour (2026-08-17, unverified):** `GROUP_TIME_SET` = `config[4]` and `GROUP_TIME_LEFT` = `config[5]`. Each group has a duration (48h for POOL, 4h for WATERFALL, 90m for AMBIANCE, 15m for CLEANER). `config[5]` is non-zero when the group has been running — a countdown remaining or a start timestamp. The index positions are verified by diagnostics; the semantic meanings are inferred from the app's constant names.

**✅ Confirmed (2026-09-03, user packet captures + three sequential diagnostics):**
- **`timeSet` (config[4]) is the static set duration and does NOT decrement.** It stays at 5400 (90 min) across three snapshots of the WATERFALL group: on, 5 minutes later (running), and off. The integration's duration number entity reads this value, so it is stable (no recorder churn).
- **`timeLeft` (config[5]) is the decrementing countdown.** It dropped from 5383s to 5000s over ~6 min of runtime (≈ real-time), and reads 0 when off.
- **`ends_at` is computed as `now + timeLeft` and is rounded down to the minute** by the integration to avoid sub-second drift between polls. It is a fixed timestamp that does not move while the group runs.
- **Turning a group off does NOT revert `timeSet` to the group's max.** The off-write (`{state: [0, 0]}`) sets `state=0` and `timeLeft=0`, but leaves the last-set duration intact (WATERFALL stayed at 5400, not 21600).
- **The device clamps out-of-range durations to the group's max.** If a set duration exceeds the group's configured maximum, the device reverts it to the max on the next read (e.g. a 10h request on a 6h-max group reverts to 6h). This is device enforcement, not something the integration needs to handle.

**User-facing model — duration is a *preference* (2026-09-04):** The group duration number entities do not mirror `timeSet`. They hold the user's **preferred duration**, persisted across restarts:
- A blank number is seeded once from the controller's `timeSet`; after that the device never overwrites it.
- Changing the number while the group is **off** stores the preference only (no device write — writing `state:[1,duration]` while off would turn the group on).
- Turning a group on (switch or `set_group_state` service) uses that preference unless the service passes an explicit `duration`.
- Changing the number while the group is **on** applies the new duration immediately.
- The controller's actual configured duration is exposed as a read-only `controller_duration` attribute (formatted `0d hh:mm`) on both the number and group switch entities, so the device's real value stays visible without fighting the preference.

#### F10a. Group Write Path (CONFIRMED from user packet capture, 2026-09-01)

**✅ CONFIRMED:** The user captured the exact PATCH payloads the app sends to `?cmd=devices&device=0` for group control:

```json
// Activate Waterfall group (default 6 hours)
{"groups": {"1": {"state": [1, 21600]}}}

// Change Waterfall to 58 minutes
{"groups": {"1": {"state": [1, 3480]}}}

// Turn Waterfall off
{"groups": {"1": {"state": [0, 0]}}}

// Activate Ambiance for 8 hours (default max)
{"groups": {"3": {"state": [1, 28800]}}}

// Turn Ambiance off
{"groups": {"3": {"state": [0, 0]}}}
```

**Key findings (all confirmed):**
- The group write uses a **`state` key** with a **2-element array** `[state, duration]`
- `state`: `1` = on, `0` = off
- `duration`: time in **seconds** (21600=6h, 3480=58min, 28800=8h)
- The endpoint is `?cmd=devices&device=0` (the heat pump device)
- This **supersedes** the earlier guess that the write used `{"config": {"3": 1}}` — the actual format is `groups.{key}.state = [on/off, duration]`

**Note:** The duration is only meaningful when turning a group on. Turning off uses `[0, 0]`. When turning on without a duration, the app uses the group's configured default max (e.g. 21600 for Waterfall).

The earlier app-behaviour hypothesis (`updateDevice` → `{devices: {...}}` → `config[3]`) was reasonable but the **confirmed capture shows the real payload is flat** (`groups.{key}.state`), not wrapped in `devices.{id}`.

#### F10b. Integration Services (UI mode)

The integration exposes two admin services that wrap the confirmed write paths above. Both are defined in `services.yaml` and translated in `translations/en.json`, so they appear in the Home Assistant Services UI picker.

| Service | Fields | Write path |
|---------|--------|------------|
| `set_group_state` | `group` (name or key), `state` (on/off/true/false/1/0), `duration?` (minutes or human-readable) | `groups.{key}.state = [on/off, duration]` |
| `set_pump_mode` | `mode` (auto/manual/off), `rpm?` (required for manual) | `equip.{slot} = [rpm/50, flag]` |

Notes:
- `state` is validated with `cv.boolean`, so it accepts `on`/`off`, `true`/`false`, or `1`/`0`.
- `duration` accepts minutes (e.g. `90`) or a human-readable value (e.g. `1d 10h 22m`); when omitted, the group's stored default (`config[4]`) is used.
- `set_pump_mode` with `mode: manual` requires `rpm`; the RPM is divided by the ×50 factor before writing.

#### F10c. Optimistic updates (write entities)

**Implemented (2026-09-03):** All write entities (switches, selects, numbers, climate) reflect a control change **immediately** after a successful write, rather than waiting for the next poll. The coordinator keeps a monotonic `refresh_seq` counter, bumped on each successful fetch. Each write entity holds an optimistic flag (`PoolSyncOptimisticMixin`) that:

- Is set only **after** the write succeeds, so a failed write never leaves a stale optimistic value.
- Keeps the user-requested value in `_update_attrs()` while pending, so a pre-write read-back does not immediately revert it.
- Is cleared once a fetch that started **after** the write completes (`refresh_seq > optimistic_seq`), after which the fresh read-back is trusted.

For climate, `current_temperature` is a live sensor reading and is always updated even while an optimistic write is pending; only the control values (`hvac_mode`, `preset_mode`, `target_temperature`) are guarded.

### 🟢 LOWER CONFIDENCE — Needs more data

#### F11. Schedule Time Encoding (RESOLVED by packet capture, 2026-09-02)

**✅ RESOLVED:** The schedule time encoding is `value = minute * 256 + hour` (see F7). The values `7688`, `11527`, `11528` that previously appeared to be "unknown encoding" are now decoded as 8:30am, 7:45am, and 8:45am respectively. This section is retained for historical reference only.

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

#### F14. Equipment Write API Format (RESOLVED by packet capture, 2026-09-01)

The write endpoint `PATCH /api/poolsync?cmd=devices&device={id}` sends JSON directly to the device. For **named config keys** (`config.setpoint`, `config.mode`, etc.) the payload is `{"config": {key: value}}` and the read/write keys match.

For **equipment arrays** (positional `equip["1"] = [0, "CIRCULATION PUMP", ...]`), the confirmed capture (2026-09-01) shows the write replaces the equipment slot with a **partial array**:

```json
{"equip": {"1": [36, 4294967295]}}   // pump: [rpm/50, manual-flag]
```

So the format is `equip.{slot} = [values...]` — a partial positional array where each element maps to the same index as the full read array. This **resolves** the earlier open question: we now know the pump RPM and flag write format (see F1).

The **valve write key remains unknown** — the user confirmed (2026-07-15) the valve position is a side effect of group membership and not independently controllable, so a direct valve write is not needed.

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

---

## 7. HP10 (PID 9985): Gaps, Communications Evidence & Open Questions

Reference layout: §0e. This section tracks the work items and the questions we cannot answer from a single capture.

### 7.1 Integration gaps (code state at 2.0.1)

| # | Gap | Location | Status |
|---|-----|----------|--------|
| G1 | No PID awareness — every heat pump is decoded with the `HP` layout | `runtime.py` flag helpers | ✅ **fixed** — `get_heat_pump_flag_layout()` selects `hp`/`hp10` from `nodeAttr.pid` |
| G2 | `has_flow = ctrlFlags != 0` | `runtime.py` `_heat_pump_has_flow()` | ✅ **fixed** — flow is the dedicated flow-sensor bit; `090-all-off` (`ctrlFlags=512`) no longer reports flow |
| G3 | HP10 fault table missing — 9985 faults decoded with `HP_FAULTS` | `fault_codes.py` | ✅ **fixed** — `HP10_FAULTS` (8 bits) selected by PID 9985 in `get_fault_table()` |
| G4 | Multi-word fault arrays decoded per element from bit 0 | `fault_codes.py:decode_faults()` | ✅ **fixed** — linear index `word * 32 + bit` |
| G13 | Zero PID 9985 test coverage | `tests/sample_diagnostics/` | ✅ **fixed** — `hp10-issue30-pump-off.json` + `test_heat_pump_ctrl_flags_use_pid_layout` |
| G5 | `stateFlags` parsed but unused | `runtime.py` | ✅ **fixed** — all flags decoded per layout (`isOff`, `isWaitFlow`, `isHolding`, `isHeating`, `isCooling`, `isDefrosting`, `isFaulted`, `isLockedOut`, `isMakeDelay`, `isRemoteControlled`, `isLocalUIControl`); climate action follows `isOff`/`isHeating`/`isCooling`, bounded by capability |
| G6 | HP10 `twoWireEnabled` / `twoWireHeatModeOn` never exposed | `runtime.py` | 🔵 open — cannot tell whether the unit is under external dry-contact control |
| G6a | HP10 `ctrlFlags` bit 2 (`highPressureLowPressure`) never exposed | `runtime.py` | ✅ **exposed** as `binary_sensor.*_high_low_pressure` (diagnostic), `None` on HP. **Semantics still unconfirmed (Q2)** — it was set with the compressor off and no `faults[]` entry |
| G7 | HP10 sensor set not mapped: `ws1Temp`, `ws2Temp` | `runtime.py` sensor getters | 🔵 open — `hp_water_temp2` maps `waterTemp2`, which HP10 never sends (`null` while `ws2Temp` = 86.98) |
| G8 | Water temperature not gated on flow | `runtime.py` sensor getters | ✅ **fixed** — `hp_water_temp` and climate current temperature report unknown without flow, with `unavailable_reason: no_flow` |
| G9 | `_TEMP_SENTINELS` / `_get_temp_value` are dead code | `runtime.py` | ✅ **fixed** — sentinel filtering now applies to the heat pump water temperature |
| G10 | `hp_fault_code` reports the first non-zero **word** as a "code" | `runtime.py` | ✅ **fixed** — renamed to *Active faults*; state is the decoded names, attributes carry `faults` / `raw` / `pid` |
| G11 | `poolSync.status.flags` (`SYNC_FLAGS`) unused | diagnostics | ✅ **fixed** — `get_sync_flags()` decoded into the diagnostics dump |
| G12 | Write guards differ from app: no `isOnline` / freeze-protect refusal | `coordinator.py` write paths | 🟢 deferred — HA can write while the app would refuse (low impact) |

Fixes for G1–G5 and G8–G13 have landed. Behaviour changes on existing hardware: a non-zero
`ctrlFlags` without the flow bit no longer reports flow; water temperature is unknown without
flow; `hp_fault_code` now shows decoded names instead of a raw bitmask word; climate action
follows the device's own state flags.
Diagnostics now include `heat_pump_debug.pid` and `heat_pump_debug.flag_layout` so future
reports are self-identifying.

### 7.2 What pairing/communications evidence suggests about issue #30

Two separate events are involved; they should not be conflated.

**(a) 2026-11-02 — flow/compressor shown ON while the pump was OFF (app showed OFF).**

- Not polling/staleness: the diagnostics show `last_update_success: true`, `last_failure_class: null`, `update_interval_seconds: 120`, and the dongle clock (`status.dateTime`) at 12:41:09, ~6 min after the 12:35 observation. A fresh poll was decoded with the wrong layout (§0e.9).
- Not communication loss: the payload is internally consistent for an HP10 unit — `stateFlags: 8` = `isWaitFlow`, `ctrlFlags: 4` = `HP/LP` input, compressor/fan/flow bits all clear, and the app's "No Flow" + "Flow OFF" come from those same bits.
- Pairing is unrelated to this one: it is a decode defect (G1/G2).

**(b) 2026-11-05 — PoolSync froze repeatedly and the app said "System is Powered Off".**

- `poolSync.status.flags` = 0 and `stats.cfgRamConflicts` / `cfgNvramConflicts` = 0, so no config-conflict restart storm at snapshot time.
- `stats`: `numPowerups: 19`, `systemRestarts: 16`, `lastEsp32ResetReason: 3` (ESP-IDF `ESP_RST_SW` = software restart), `restartHistory: "08070908"`, `wifiDisconnects: 21`, `awsDisconnects: 10`, `mqttKeepAliveTimeouts: 524342`, `upTimeSecs: 1009806` (~11.7 days), `numConsoleIncorrectPassword: 20`.
- `stats.numDeviceMsgNoResp: 2` and `stats.device0CommErrors: 2` — the dongle↔heat-pump link had logged only two non-responses at snapshot time, so a persistent bus failure is not proven.
- "System is Powered Off" is `isHeatPump10 && isOff` (state flag bit 0) — the *heat pump* told the dongle it was off. Combined with the compressor stopping, that is the heat pump's own behaviour, not HA's.
- Later in the same log HA got `Connect call failed ('192.168.1.153', 80)` — the dongle's HTTP listener went away, consistent with the software-restart counters. The integration then serves the last snapshot for up to 3 consecutive failures (`_MAX_STALE_TRANSPORT_FAILURES`), so ~6 min of frozen-but-plausible values before entities go unavailable.
- Nothing HP10-specific was found in the pairing or transport layer: the app uses the same endpoints, the same `&all` snapshot, and tolerates far more polling than HA's 120 s (the app polls on a 2500 ms cycle — **tentative**, observed from timing rather than a confirmed constant).

**Plausible-but-unproven for (b):** `ctrlFlags` bit 2 (`highPressureLowPressure`) was *set* in the 11-02 capture while the compressor was off and `faults: [0]` reported nothing. If HP10 latches a pressure-switch condition that never appears in `faults[]`, it could explain both "no fault code" and the repeated stops. One capture cannot settle this (§7.3 Q2).

**Not implicated for either event:**

- Multi-client authorization (§1.1b) would present as 401 auth failure, not frozen values.
- Two-wire control (`twoWireEnabled`) and panel takeover (`isLocalUIControl`) were both clear in the 11-02 capture (`ctrlFlags` bit 4 = 0, `stateFlags` bit 8 = 0).
- Wi-Fi signal: `rssi: -40`, `minRssi: -62` — strong.

### 7.3 Open questions (HP10)

| # | Question | Why it matters | What would answer it |
|---|----------|----------------|----------------------|
| Q1 | Do real 9985 captures match the HP10 bit maps in §0e.3/§0e.4 across pump-on, heating, idle-with-flow and defrost states? | Only one 9985 payload exists today | 4 captures from any 9985 unit (all modes) |
| Q2 | Is HP10 `ctrlFlags` bit 2 (`highPressureLowPressure`) a latched condition or a live switch input? Should it suppress heating / be surfaced as a fault? | Candidate cause of the 11-05 stops with no `faults[]` entry. Now **exposed** as a diagnostic binary sensor, so captures from affected users will show whether it tracks the switch or latches | capture with bit 2 set + service-manual cross-check |
| Q3 | What exactly does `isLocalUIControl` (state bit 8) mean, and should HA disable writes while it is set? | Panel takeover would silently ignore HA writes | capture with the panel being operated |
| Q4 | With `twoWireEnabled` set, are `mode`/`setpoint` writes still honoured, or does the dry contact override them? | Could make heat control a no-op | capture from a two-wire installation |
| Q5 | Is HP10 `waterTemp` a computed value or a mirror of `ws1Temp`? Should `hp_water_temp2` map to `ws2Temp` on 9985? | Sensor accuracy / duplicate entities | 2 captures with different ws1/ws2 spread |
| Q6 | ~~Should water temperature be reported unavailable when `flowSensorOneState` is false?~~ | **Resolved** — gated on flow (unknown + `unavailable_reason: no_flow`) | — |
| Q7 | Is `faults[]` on HP10 always a single word, and are bits 8+ used? | Unknown bits currently decode to nothing | capture with an induced fault (e.g. unplug a water sensor) |
| Q8 | Why does the app's per-PID fault **card** table for 9985 contain only `pressure` / `pressureLockout`, while the `HP10_FAULTS` bit template uses `lowPressureHighPressure` / `lp5hp5Lockout`? | Either a vendor naming mismatch (cards never render) or a table we misread | induced pressure fault + watch the app's alert card |
| Q9 | Does HP10 support cooling or auto? App hardcodes `['OFF','HEAT']` and `supports_cooling = false` | Configuration surface | model-number list from AquaCal / a cooling unit capture |
| Q10 | `setpointMax` 104 vs app fallback 110 — which wins when the payload omits it? | Range clamping | capture from a unit without limits |
| Q11 | Can `remoteUiPid` be 9984/9985 (heat pump as UI host)? If so the pairing screen shows no button text at all | Affects the pairing UX we document | unit where the heat pump drives the UI |
| Q12 | Does `isOff` (state bit 0) mean the panel switch is off, or standby? And why is HP's `poweredOff` control bit labelled "HP10 Panel Off"? | Interpretation of the app's "System is Powered Off" banner | panel on/off capture pair |
| Q13 | What are `ds1Temp`/`ds2Temp` on HP10 (defrost/suction vs water sensors)? In the capture 89.06 / 86.64 bracket `waterTemp` 87.3 | Whether they are safe to expose | service manual + heating capture |
| Q14 | Does `logicIdSupport` (`true` for HP10) imply multi-unit / logical-ID addressing that HA should use for writes? | Multi-unit installs | multi-unit capture |

### 7.4 Suggested next captures

1. PID 9985, pump **on**, unit **heating** (expect compressor bit 0 + fan bit 1 set, `isHeating` bit 1 set, no `isWaitFlow`).
2. PID 9985, pump **on**, unit **idle at setpoint** (expect flow bit 3 set, compressor/fan clear, `isHolding`).
3. PID 9985 with an **induced water-sensor fault** (expected bit 0/1 in `faults[0]`, `isFaulted` bit 5).
4. PID 9985 **panel switched off** (expected `isOff` bit 0; confirms Q12 and the banner mapping).
5. Same unit **with a pressure condition** if one can be triggered safely (Q2/Q8).

Store captures in `tests/sample_diagnostics/` with `hp10-*` names so `test_runtime.py` can pin the new layout.


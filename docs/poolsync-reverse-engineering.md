# PoolSync Reverse Engineering

Reference document tracking what we know, what we've built, and what we suspect. Each section cites the specific diagnostic payloads or code paths that back the claim.

---

## 0a. Source: Android App (APK) Analysis

The official PoolSync Android app (v4.73, package `com.poolconnect.sync`) was obtained from APKPure and analysed to extract API protocol details.

**Method:**
1. Downloaded the XAPK bundle and decompiled the base APK with `JADX`
2. The main application bundle (`assets/index.android.bundle`) was identified as **Hermes bytecode** (React Native 0.85.3, Hermes v98)
3. Disassembled to Hermes assembly with [`hermes-dec`](https://github.com/P1sec/hermes-dec) (v0.1.5): `hbctool disasm index.android.bundle output.hasm`
4. The Hermes assembly (68 MB, ~1M lines) preserves string constants, function names, and instruction patterns — enough to reconstruct API endpoints and request formats without recovering full JavaScript logic

**Status:** Early-stage exploration. The disassembly reveals API endpoint strings, HTTP header patterns, and function names. Full decompilation to readable JS is limited by Hermes bytecode version (98) and the absence of a sourcemap. Deeper analysis may yield additional protocol details as techniques improve.

---

## 0b. Live API Probing & Decompiled Endpoint Map (Preliminary)

A live T75 heat pump (fw 860, hw 2.0) was probed via the local HTTP API. Additionally, the Hermes-disassembled Android app bundle revealed the complete set of API functions and their HTTP methods. **These findings are preliminary** — only one firmware version has been live-tested, and behaviour may vary across models and firmware revisions.

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
| `{"groups": {"0": {"config": {"3": 1}}}}` | ✅ 200 | Sparse group state toggle |
| `{"groups": {"2": {"config": [...], "equip": {"1": [35,0]}}}}` | ✅ 200 | Group config + equipment mapping |
| `{"primePump": 1}` | ✅ 200 | Action command |
| `{"equip": {"1": {"7": 58}}}` | ✅ 200 | Equipment array index write |

**Required PATCH headers:**
```
Authorization: {password}
User: {userSub or static UUID}
Content-Type: application/json
```

### Decompiled function-to-method map (from APK, not live-tested)

Functions that build HTTP requests, with their methods, inferred from Hermes assembly:

| Function | Method | Endpoint | Notes |
|----------|--------|----------|-------|
| `getSync` | `GET` | `?cmd=poolSync` or `?cmd=poolSync&all` | Read all controller+device data |
| `getDevice` | `GET` | `?cmd=devices&device={id}` | Read single device (401 on fw 860) |
| `checkChangeStatus` | `GET` | `?cmd=changeStatus` | May check device status |
| `checkPushLinking` | `GET` | `?cmd=pushLink&...` | Poll push-link state |
| `updateSync` | `PATCH` | `?cmd=poolSync` | Controller-level write |
| `updateDevice` | `PATCH` | `?cmd=devices&device={id}` | Device-level config write |
| `putDevice` | `PUT` | `/api/dongle/devices/{id}` | Full device state replace (dongle API) |
| `putDongleState` | `PUT` | `/api/dongle/state` | Dongle state update |
| `startPushLinking` | `POST`/`PUT` | `/api/dongle/link` | Initiate push-link pairing |
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

### 0c. Complete Field Name Mappings (from APK Decompilation)

The decompiled app contains a master mapping object (`DEVICES`) that translates between internal constant names and API data paths. Every readable sensor and writable config field is defined here. The mapping uses dot-separated paths into the per-device data object:

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
| `CHEM_FEED_RATE` | `config.feedRate` | Read/Write | Feed pump rate |
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

#### Default display names

The app defines these default names for device types:

| Constant | Value | Device Type |
|----------|-------|-------------|
| `SYNC_DEFAULT_NAME` | `PoolSync®` | Controller |
| `HP_DEFAULT_NAME` | `Heat Pump` | Heat pump |
| `CHLOR_DEFAULT_NAME` | `Chlorinator` | ChlorSync |
| `CHEM_DEFAULT_NAME` | `Chem Controller` | ChemSync |

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

**RPM factor confirmed as ×50:** 35→1750, 58→2900, 69→3450 — all three match the filenames from the user.

**⚠️ Write key gap:** Equipment data is a positional array, not a named object like `config.{key}`. The read-side has no named keys to observe, so the write API key for setting pump speed is unknown. Candidates (`rpm`, `speed`, `pumpSpeed`) are guesses until API traffic is captured or trial-and-error confirms one. The existing write pattern (`PATCH … → config.{key}`) is proven for device-level config keys, but equipment-level writes may use a different path entirely.

**Proposed entities:** `sensor` for current pump RPM (index 7 × 50), `binary_sensor` for priming flag (index 14), `number` for RPM control (requires write key discovery).

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
| 6–7 | Unknown | 0, 0 | Constant |
| 8 | Position A name | "FOUNTAIN" | Named position in active groups |
| 9 | Position A value | 3 | Matches valve setting in WATERFALL/AMBIANCE groups |
| 10 | Position B name | "POOL" | Named position in active groups |
| 11 | Position B value | 0 | Matches valve setting in POOL group |
| 12 | Unknown | 0 | Constant |

**⚠️ Write key gap:** Same issue as F1. Additionally, user feedback (2026-07-15) indicates **valve position is not independently controllable** — it's a side effect of group membership. Changing the valve requires changing which groups are active. An independent write control would not work.

**Proposed entities:** `sensor` for current position (from active group's `equip["3"][0]`, mapped through names). No select control.

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

| Type | Name | Seen In | Notes |
|------|------|---------|-------|
| 0 | Variable Speed Pump | equip[1] | Internal RPM × 50 = real RPM |
| 1 | Valve/Actuator | equip[3] | Named positions, timed movement |
| 2 | (unknown) | — | All null in 090; possibly single-speed pump, light, or booster |
| 3 | Heat Pump | equip[0] | Already handled by existing integration |
| 4–15 | (unknown) | — | All null in 090; may include lights, solar valves, chemical feeders, additional heat pumps |

#### F6. Group index 3 Active State Semantics

Any positive value is considered active (the app checks `config[3] > 0`). What distinct values 1, 2, etc. mean is unclear — they may encode priority, activation source (manual vs schedule), or a sub-state. User testing confirmed groups are additive, so state values do not imply mutual exclusion.

| Value | Meaning | Evidence |
|-------|---------|----------|
| 0 | Inactive | All non-active groups across all 3 samples |
| 1 | Active | FILTRATION group in files 1 and 2 |
| 2 | Active (different priority/source) | POOL group in file 3 (mode=1, compressor on) |

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

The write endpoint `PATCH /api/poolsync?cmd=devices&device={id}` currently sends `config.{key}`. This pattern is proven for device-level config keys where the read payload has named objects (`config.setpoint`, `config.mode`, etc.) — the read key and write key match exactly.

Equipment data, however, is stored as **positional arrays** in the read payload (`equip["1"] = [0, "CIRCULATION PUMP", ...]`). There are no named keys to observe and match against. This means:

- We **cannot** determine equipment write keys from diagnostic data alone
- The key name for setting pump speed or valve position is unknown
- Candidates (`rpm`, `speed`, `pumpSpeed`, `position`, `valve`) are guesses

**Resolution requires:** API traffic capture between the PoolSync app and device during equipment control operations, or trial-and-error with a willing beta user.

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

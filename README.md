# AutoPilot PoolSync Custom Integration for Home Assistant

[![Quality Scale: Gold Ready](https://img.shields.io/badge/Quality%20Scale-Gold%20Ready-FFD700)](https://github.com/ccpk1/AP_PoolSync/blob/main/quality_scale.yaml)
[![Quality Gates](https://img.shields.io/github/actions/workflow/status/ccpk1/AP_PoolSync/lint-validation.yaml?branch=main&label=Quality%20Gates)](https://github.com/ccpk1/AP_PoolSync/actions/workflows/lint-validation.yaml)
[![License](https://img.shields.io/static/v1?label=License&message=GPL-3.0&color=1E88E5&labelColor=555)](https://github.com/ccpk1/AP_PoolSync/blob/main/LICENSE)
[![HACS Custom](https://img.shields.io/static/v1?label=HACS&message=custom&color=1E88E5&labelColor=555)](https://github.com/custom-components/hacs) <br>
[![Version](https://img.shields.io/github/v/release/ccpk1/AP_PoolSync?label=Version&color=1E88E5)](https://github.com/ccpk1/AP_PoolSync/releases)
[![Stars](https://img.shields.io/github/stars/ccpk1/AP_PoolSync)](https://github.com/ccpk1/AP_PoolSync/stargazers)

### Full local monitoring and control of your AutoPilot PoolSync ecosystem — zero cloud dependencies.

Bring your complete AutoPilot PoolSync infrastructure into Home Assistant. Whether operating a standalone PoolSync controller or one integrated directly into an AquaCal heat pump, this integration local-polls and controls your full equipment stack: chlorination, water chemistry, heating, circulation pumps, motorized valves, and group scenes.

---

## Key Features

- **100% Local Control:** Direct IP communication via local push-button authorization. No cloud outages, no external dependencies.
- **Multiple PoolSync Controllers:** Add more than one PoolSync controller as separate config entries — ideal for homes with separate pool/spa installs.
- **Comprehensive Equipment Coverage:** Controls ChlorSync, ChemSync (pH/ORP), heat pumps, variable-speed pumps, valves, and group scenes.
- **Multi-Device Architecture:** Full native support for setups with multiple units of the same equipment type (e.g., dual ChlorSync chlorinators, multiple heat pumps, or stacked ChemSync controllers).
- **Human-Readable Diagnostics:** Decodes raw board fault codes, firmware data, temperatures, and Wi-Fi link quality.

<img width="1024" height="1004" alt="image" src="https://github.com/user-attachments/assets/455ab6f5-1a87-4cc1-b15f-db50a4b9fae1" />



---

## Compatibility & Prerequisites

| Requirement | Details |
| :--- | :--- |
| **Home Assistant** | Core `2025.1.0` or newer |
| **Network** | Local network access to the PoolSync IP address |
| **Hardware Support** | Standalone PoolSync Controller **OR** PoolSync integrated into Heat Pump |
| **Ecosystem Units** | ChlorSync, ChemSync, Heat Pumps, Variable-Speed Pumps, Valves, Group Scenes |

---

## Installation

### One-Click HACS Install
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ccpk1&repository=AP_PoolSync&category=integration)

### Manual HACS Setup
1. Open **HACS** in Home Assistant → **Integrations**.
2. Click the top-right menu icon → **Custom repositories**.
3. Add `https://github.com/ccpk1/AP_PoolSync` as an **Integration**.
4. Search for **PoolSync Custom**, click **Install**, and restart Home Assistant.

---

## Initial Setup & Local Linking

1. In Home Assistant, go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **PoolSync Custom** and enter the local IP address of your PoolSync device.
3. When prompted, press the physical **Auth** or **Service** button on your PoolSync controller.

<table>
  <tr>
    <td align="center" valign="top">
      <strong>HA Setup Prompt</strong><br />
      <img width="460" alt="link device" src="https://github.com/user-attachments/assets/86c394cd-9d7c-4675-9bcc-9500b157da5f" />
    </td>
    <td align="center" valign="top">
      <strong>Physical Hardware Auth Button</strong><br />
      <img width="487" alt="press auth" src="https://github.com/user-attachments/assets/b957b170-7b41-475a-a700-7836676b4801" />
    </td>
  </tr>
</table>

4. Wait for Home Assistant to complete pairing and generate config entries for all detected hardware.

If linking fails, the flow offers a retry path. If repeated attempts fail, restart the PoolSync device and try again.
<table>
  <tr>
    <td align="center" valign="top">
      <strong>Retry</strong><br />
      <img width="456" height="270" alt="image" src="https://github.com/user-attachments/assets/7abc8ce0-0421-45ce-8d95-deaff0efaf06" />
    </td>
  </tr>
</table>

---

## Equipment & Entity Breakdown

The integration dynamically generates discrete devices and entities based on what your PoolSync installation reports. When multiple devices of the same type are present (e.g. two ChlorSync units or two heat pumps), each gets its own device and a full set of entities.

### 🎮 Controller & System
- **Sensors:** Wi-Fi RSSI & Signal Status, Board Temperature, System Date/Time, Firmware/Hardware Revisions, Display Brightness.
- **Diagnostic Counters:** Wi-Fi disconnects, AWS disconnects, power-ups, system restarts, and offline-device counts.
- **Group On/Off Switches:** Individual switches (`switch.group_*`) for `POOL`, `WATERFALL`, `FILTRATION`, `AMBIANCE`, and `CLEANER` — turn a group on or off directly. Each exposes `duration` (your preference), `controller_duration` (the device's configured value), and `ends_at` (when the group stops).
- **Group Schedule Switches:** Separate schedule toggles (`switch.group_*_schedule`) that enable or disable each group's programmed schedule (its `schedMode`), exposing a decoded `schedules` attribute with up to 4 slots (days and times).
- **Group Duration:** Custom duration sliders (`number.group_*_duration`) to set persistent run-time defaults or apply immediate extensions. Exposes `controller_duration` so you can always see the device's actual value.
- **Group Info Sensor:** `sensor.group_info` shows which groups are active, with per-group config, equipment, and timing (duration and end time) attributes.

### 🧂 ChlorSync (Chlorinator)
- **Control:** Output percentage slider (`number`).
- **Sensors:** Water Temperature, Salt Level (PPM), Cell Flow Rate, Boost Time Remaining, Output Setting.
- **Diagnostics:** Cell forward/reverse current, cell output & rail voltage, cell serial number, firmware/hardware versions, temperature compensation output, driver model/firmware/hardware, pool cover control, pool gallons, polarity change time, ORP input control.
- **Fault Sensor:** The fault binary sensor exposes both the raw `fault_code` and decoded `active_faults` (human-readable names like "High Salt", "Clean Cell").
- **Actions:** One-click button to clear cell life warnings.

> ⚠️ **The clear-cell-life action is not yet confirmed.** It is implemented from the reverse-engineered API, but whether it actually executes depends on the target device supporting it. If you use it and it isn't working properly, please [open a GitHub issue](https://github.com/ccpk1/AP_PoolSync/issues) — and if you're willing to work with me to finalize it (including capturing the correct command syntax), that would be a huge help.

### 🧪 ChemSync (Chemical Controller)
- **Control:** System Mode selector, pH Setpoint, ORP Setpoint, Max Daily Feed adjustments.
- **Sensors:** Live pH, Live ORP, Acid Consumption, Tank Level Alert, Board Temperature.
- **Diagnostics:** Firmware, hardware, and model details.
- **Fault Sensor:** The fault binary sensor exposes both the raw `fault_code` and decoded `active_faults` (e.g. "pH Below Min", "Flow Sensor").
- **Actions:** Prime Pump and Chemical Boost action buttons.

> ⚠️ **ChemSync write controls are not yet confirmed.** The pH/ORP setpoint and max daily feed writes are implemented from the reverse-engineered API but have not been validated against a live ChemSync device. If you have a ChemSync and these controls aren't working properly, please [open a GitHub issue](https://github.com/ccpk1/AP_PoolSync/issues) — and if you're willing to work with me to finalize them (including capturing the correct command syntax), that would be a huge help.

### 🌡️ Heat Pumps & Climate
- **Control:** Full Home Assistant `climate` entity for target water temperature, HVAC modes, and preset selection. Exposes current temperature, target temperature, HVAC action, and min/max temperature.
- **Sensors:** Water Temperature, Air Temperature, Pool/Spa Setpoint tracking, Active Target Temperature, Fault Code.
- **Diagnostics:** Board Temperature, Outlet Water Temperature, Defrost Sensor 1 & 2, Top Fault Code & Count.
- **Binary Sensors:** Compressor state, Fan state, Water Flow status, Online/Fault flags, Remote Control.
- **Fault Sensor:** The fault binary sensor exposes both the raw `fault_code` and decoded `active_faults` (e.g. "Low Pressure", "High Pressure").

### 🔄 Pumps & Motorized Valves
- **Mode Select:** `Auto` (follows active group), `Manual` (user RPM), `Off`.
- **Speed Control:** Live RPM sensor and manual RPM adjustment slider.
- **Valves & Status:** Live valve position reporting (e.g., POOL vs. FOUNTAIN) and pump priming binary sensor.

---

## Native Services

Available via **Developer Tools** → **Actions / Services**:

### `poolsync_custom.set_group_state`
Triggers a group scene with an optional custom duration string.
```yaml
action: poolsync_custom.set_group_state
data:
  group: "WATERFALL"
  state: "on"
  duration: "1h 30m"
```

### `poolsync_custom.set_pump_mode`
Directly controls variable-speed pump modes and target RPM.
```yaml
action: poolsync_custom.set_pump_mode
data:
  mode: "manual"
  rpm: 2200
```

---

## Common Use Cases

### Set a group's default run time
Change how long a group runs by default when you turn it on. Set the group's duration number (`number.group_*_duration`) to your preferred minutes. The value is persisted across restarts and used the next time you turn the group on.

### Run the pump at a fixed speed
Set the pump to manual at a specific RPM, then return it to automatic (following the active group):
```yaml
action: poolsync_custom.set_pump_mode
data:
  mode: "manual"
  rpm: 2000
```
```yaml
action: poolsync_custom.set_pump_mode
data:
  mode: "auto"
```

### Enable a group's schedule
Turn on the group's schedule switch (`switch.group_*_schedule`) to let the group follow its programmed schedule. This does **not** turn the group on immediately — it only enables the schedule.

### Automate the heat pump
The heat-pump climate entity supports normal Home Assistant climate automations (turn on/off, set target temperature, set preset mode). For example, heat the pool to 84°F when the outdoor temperature drops:
```yaml
automation:
  - alias: "Heat pool when cool"
    trigger:
      - platform: numeric_state
        entity_id: sensor.outdoor_temperature
        below: 60
    action:
      - action: climate.set_temperature
        target:
          entity_id: climate.poolsync_water_thermostat
        data:
          temperature: 84
```

Some diagnostic entities are disabled by default to keep the default dashboard cleaner.

---

## See It In Action

### Controller:
<img width="300" alt="image" src="https://github.com/user-attachments/assets/3f9a3478-c32f-4470-ba26-3adfe248d2e1" />

### Heat Pump:
<img width="300" alt="image" src="https://github.com/user-attachments/assets/ab334d7e-9469-456a-9590-32f5a1bc07b4" /> <img width="300" alt="image" src="https://github.com/user-attachments/assets/d9bc554c-72c0-4366-ab19-202a62dfa9a6" /> <img width="300" alt="image" src="https://github.com/user-attachments/assets/816fecf9-7485-47b6-bc4c-cf104013f52d" />

### Circulation Pump:
<img width="318" height="355" alt="image" src="https://github.com/user-attachments/assets/cecb1b0c-24e4-4b58-993a-3ab706529610" />

### ChlorSync
<img width="300" alt="image" src="https://github.com/user-attachments/assets/58c212b1-8e6c-4b84-a23c-4d7f043c95ae" />

### ChemSync
<img width="300" alt="image" src="https://github.com/user-attachments/assets/a22ddd62-647e-421d-bc51-c2bca0103461" />

---

## Options

After setup, you can adjust the polling interval:

1. Go to **Settings** → **Devices & Services**.
2. Open the PoolSync integration card.
3. Select **Configure**.
4. Set **Update interval** in seconds and submit.

The minimum supported interval is 10 seconds.

---

## Removal

To remove the integration:

1. Go to **Settings** → **Devices & Services**.
2. Open the PoolSync integration.
3. Select the menu for the config entry.
4. Choose **Delete**.

This removes the Home Assistant config entry and its entities. It does not change configuration on the physical PoolSync device.

---

## Troubleshooting & Diagnostics

- **Linking Issues:** If pairing times out, reboot the physical PoolSync controller and retry the HA configuration flow immediately after startup.
- **Intermittent Unavailability:** Check Wi-Fi RSSI on the controller device page. Outdoor pool equipment often suffers from marginal Wi-Fi signals; weak links cause TCP connection resets.
- **Debugging:** Export Diagnostic JSON directly from the PoolSync Device page in HA when filing GitHub issues. I've made efforts to redact private information (such as hardware serial numbers, tokens, and passwords) in the exported diagnostic file, but you should always review it and double-check before submitting if you have any concerns. If you spot anything that should be redacted, please [open an issue](https://github.com/ccpk1/AP_PoolSync/issues) and I'll make sure it's covered in a future update.

---

## ❤️ Support the Project

⭐ **Star the Repo:** If this integration powers your pool, clicking the Star button on GitHub is the best free way to support development and help others discover the project.

☕ **Sponsor Development:** Maintaining local API reverse-engineering and complex hardware state machines takes significant time and hardware investment. If this integration saves you time and money, consider sponsoring:

[![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-pink?style=for-the-badge&logo=github)](https://github.com/sponsors/ccpk1)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/ccpk1)

---

## Get Help or Report Issues

- Community thread: [PoolSync Pool / Heat Pump Integration](https://community.home-assistant.io/t/poolsync-pool-heat-pump-integration/682888)
- GitHub issues: [ccpk1/AP_PoolSync/issues](https://github.com/ccpk1/AP_PoolSync/issues)
- GitHub discussions: [ccpk1/AP_PoolSync/discussions](https://github.com/ccpk1/AP_PoolSync/discussions)

When reporting a problem, include diagnostics, relevant logs, the PoolSync firmware or hardware details if known, and what equipment is attached.

---

## Acknowledgments & Credits

Special thanks to [@socbrian](https://github.com/socbrian) for the initial reverse-engineering work on the PoolSync local linking protocol.

---

## Disclaimers & Development Model

🤖 **AI-Assisted Engineering:** In today's landscape, leveraging AI tooling is one of the only ways a solo maintainer can build, test, and support a complex multi-device integration at this scale. However, this code is not "vibe coded." Human oversight dictates the architecture, every commit is manually audited, and code is validated against Home Assistant Gold standards with continuous integration test coverage.

This integration is an independent open-source project and is not affiliated with or endorsed by AutoPilot Pool Systems or AquaCal.

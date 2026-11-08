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
| **Hardware Support** | Standalone PoolSync Controller or PoolSync integrated into a heat pump (chlorinator-hosted PoolSync is app-documented but untested) |
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

Home Assistant then opens a **120-second** window and waits for your PoolSync to hand back an access password.
What you press during that window depends on your hardware, because PoolSync is sold in a few different shapes.

> **The walkthrough and screenshots below are from a standalone PoolSync controller** — the hardware this
> project was built on. If your PoolSync does **not** have its own screen and you operate it from your heat
> pump or chlorinator display, use the matching section instead.

---

### If your PoolSync has its own panel

This covers the standalone controller, and any PoolSync unit that shows its own screen.

**Next:** press the **AUTH** button once.

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

**If nothing happens,** hold the **Service** (middle) button for about **3 seconds** instead.

> **Why both?** The PoolSync phone app's own instruction for this hardware is to *"Press and hold the Service
> Button (middle button) on your `<device>` for 3 seconds before the timer runs out to authorize this device."*
> On the standalone controller this project was built on, a single AUTH press is enough — you can see the AUTH
> LED light. So start with AUTH; fall back to the Service hold.
>
> If the AUTH LED never lights and every attempt times out, try pressing **Service** first (its LED lights) and
> **then AUTH** while Home Assistant is still counting down. That two-button sequence is what resolved
> [issue #30](https://github.com/ccpk1/AP_PoolSync/issues/30) on an integrated AquaCal unit.

**Then:** wait for Home Assistant to complete pairing and generate config entries for all detected hardware.

If linking fails, the flow offers a retry path. If repeated attempts fail, restart the PoolSync device and
try again.
<table>
  <tr>
    <td align="center" valign="top">
      <strong>Retry</strong><br />
      <img width="456" height="270" alt="image" src="https://github.com/user-attachments/assets/7abc8ce0-0421-45ce-8d95-deaff0efaf06" />
    </td>
  </tr>
</table>

---

### If you operate PoolSync from your heat pump's display

On these units the PoolSync screens appear on the heat pump's display rather than on a PoolSync panel. The
PoolSync phone app's instruction for that hardware is:

> **"Press AUTH on the heat pump display:"**
> *"Tip: If the POOLSYNC AUTHORIZE screen does not appear then navigate to the POOLSYNC WIFI menu screen or
> the MAIN status screen of the heat pump."*

So:

- Press **AUTH** on the heat pump display.
- If no **POOLSYNC AUTHORIZE** prompt appears, go to the **POOLSYNC WIFI** menu screen or the **MAIN** status
  screen and press **AUTH** there.
- If AUTH alone does nothing, the **Service then AUTH** fallback described in the section above is worth trying.

No user running this configuration has reported its pairing behaviour yet, so the steps above are transcribed
from the app.

---

### If you operate PoolSync from your chlorinator's display

> 🟡 **Not yet reported by a user.** The PoolSync phone app has a dedicated instruction for this hardware, but
> nobody running it has contacted this project, so the steps below are transcribed from the app and untested.

The PoolSync phone app's instruction is:

> **"Press Yes on the chlorinator display to authorize this device:"**
> *"Tip: If the POOLSYNC AUTHORIZE screen does not appear then press the MENU button and navigate to the
> Network setting, press Select, navigate to the Authorize setting and press Select."*

So:

- Press **Yes** on the chlorinator display.
- If no **POOLSYNC AUTHORIZE** prompt appears, press **MENU** → **Network** → **Select** → **Authorize** →
  **Select**, then press **Yes**.

---

### Authorization summary

| Where you see the PoolSync screen | What to press |
| :--- | :--- |
| On the PoolSync's own panel | **AUTH** once; if nothing happens, hold **Service** ~3 s |
| On your heat pump's display | **AUTH** on the heat pump display |
| On your chlorinator's display *(untested here)* | **Yes** on the chlorinator display |

Applies to all hardware types:

- You must press within the **120-second** window; the pairing countdown is the deadline.
- **Do not confuse this with the 15-second hold.** The app's *"hold the button for 15 seconds or until they
  flash"* puts the unit into **Wi-Fi setup mode** (orange Option light + green Wi-Fi light flashing). It is not
  how you authorize Home Assistant.
- Close the PoolSync app on your phone before pairing. The app's own failure text is *"In order to authorize,
  you must be on the same Wi-Fi network as the device."*
- Relinking authorizes the Home Assistant client. If the device's authorized clients are cleared (app: *"Clear
  all previously authorized users"*), Home Assistant raises a reauth prompt rather than silently going stale.
- **Reporting a pairing problem?** Download diagnostics from **Settings → Devices & Services → PoolSync** and
  include `poolSync.status.remoteUiPid` and `poolSync.system.hwVersion` — together with the button that finally
  worked, that is what lets this guide be corrected for your hardware.

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
- **Control:** Full Home Assistant `climate` entity for target water temperature, HVAC modes, and preset selection. Exposes current temperature, target temperature, HVAC action, and min/max temperature. HVAC action follows the heat pump's own state machine (off / heating / cooling / idle).
- **Sensors:** Water Temperature, Air Temperature, Pool/Spa Setpoint tracking, Active Target Temperature, Active Faults.
- **Diagnostics:** Board Temperature, Outlet Water Temperature, Defrost Sensor 1 & 2, Top Fault Code & Count.
- **Binary Sensors:** Compressor state, Fan state, Water Flow status, Online/Fault flags, Remote Control, High/low pressure (HP10 units).
- **Fault reporting:** Faults are a bitmask, not a single code, so the *Active Faults* sensor shows the decoded names (e.g. "Compressor Fault") with the raw words and the device product ID as attributes. The fault binary sensor exposes the same `active_faults` list. The decode table is chosen by the heat pump's product ID, so `Water Sensor 1` and `Low Pressure` are never confused.
- **Water temperature needs flow:** with no water flow the probe is sitting in a stagnant pipe, so water temperature reports as unavailable with an `unavailable_reason: no_flow` attribute instead of a misleading number. This matches the PoolSync app, which shows "No Flow" in the same situation.

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

- **Linking Issues:** Press the button for your hardware type — see [Initial Setup & Local Linking](#initial-setup--local-linking). If auth times out, try the **Service** hold (~3 s) then **AUTH**, and stay inside the 120-second window with the PoolSync app closed. If it still fails, reboot the physical PoolSync controller and retry the Home Assistant configuration flow immediately after startup.
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

## Development

### Running the tests

`pytest-homeassistant-custom-component` pins the exact Home Assistant release it
was built for, so the suite needs a virtual environment where that pin is
satisfied. Do not run it from a Home Assistant *core* development environment —
an editable core checkout is on a `.dev` build and the plugin cannot import
against it.

```bash
./utils/setup_test_env.sh    # creates .venv and installs .[dev] (no version pins)
./utils/run_tests.sh         # full suite in .venv
./utils/run_tests.sh -k heat_pump
```

Nothing is version-pinned on purpose: the test plugin is what selects the Home
Assistant release, so refreshing dependencies (`./utils/setup_test_env.sh
--fresh`) always produces a matching pair and no manual version bumps are
needed. A scheduled CI job runs the suite against the newest upstream releases
to surface breakage before it reaches a release.

If you run `pytest` directly in an incompatible interpreter, collection is
limited to the parsing-only modules (`test_runtime`, `test_fault_codes`,
`test_equipment`) instead of failing outright.

### Releasing

HACS installs from the **release asset**, not from GitHub's source snapshot
(`hacs.json` sets `zip_release` and `filename`). Asset downloads are the ones
GitHub counts, so a release without the zip is both uncounted and installed from
a source archive instead.

HACS extracts the asset straight into `config/custom_components/poolsync_custom`,
so the archive must contain the integration files **at its root** — no
`custom_components/` and no `poolsync_custom/` wrapper — which otherwise nests
them one level too deep and breaks the install.

Release steps:

```bash
# 1. Bump the version in custom_components/poolsync_custom/manifest.json
#    (and pyproject.toml, which is kept in sync).

# 2. Land it on main, then tag and push.
git tag 2.1.0
git push origin 2.1.0
```

Pushing the tag runs `.github/workflows/release.yml`, which:

1. fails if the tag does not match `manifest.json`'s `version`,
2. builds `poolsync_custom.zip` from the contents of
   `custom_components/poolsync_custom/` (excluding `__pycache__`),
3. fails if `manifest.json` is not at the archive root or a wrapper directory is
   present,
4. creates the GitHub release and attaches the asset.

To republish an existing tag, run the **Release** workflow from the Actions tab
and give it the tag name. To do it by hand instead, build the archive from inside
the integration directory so the paths are flat, then attach it to the release
with the exact filename HACS expects:

```bash
cd custom_components/poolsync_custom
zip -r -9 ../../../poolsync_custom.zip . -x '*/__pycache__/*' '__pycache__/*' '*.pyc'
```

Note that enabling `zip_release` means releases published before the asset
existed cannot be installed through HACS any more; users should be on the current
release.

---

## Disclaimers & Development Model

🤖 **AI-Assisted Engineering:** In today's landscape, leveraging AI tooling is one of the only ways a solo maintainer can build, test, and support a complex multi-device integration at this scale. However, this code is not "vibe coded." Human oversight dictates the architecture, every commit is manually audited, and code is validated against Home Assistant Gold standards with continuous integration test coverage.

This integration is an independent open-source project and is not affiliated with or endorsed by AutoPilot Pool Systems or AquaCal.

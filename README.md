# PoolSync Custom Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![Quality Scale](https://img.shields.io/badge/Quality%20Scale-Gold%20Ready-FFD700)](https://github.com/ccpk1/AP_PoolSync/blob/main/quality_scale.yaml)
[![Quality Gates](https://github.com/ccpk1/AP_PoolSync/actions/workflows/lint-validation.yaml/badge.svg)](https://github.com/ccpk1/AP_PoolSync/actions/workflows/lint-validation.yaml)
[![License](https://img.shields.io/github/license/ccpk1/AP_PoolSync)](https://github.com/ccpk1/AP_PoolSync/blob/main/LICENSE)
[![Version](https://img.shields.io/github/v/release/ccpk1/AP_PoolSync?include_prereleases&label=Version)](https://github.com/ccpk1/AP_PoolSync/releases)
[![Stars](https://img.shields.io/github/stars/ccpk1/AP_PoolSync?label=Stars)](https://github.com/ccpk1/AP_PoolSync/stargazers)

> This repository continues the original [socbrian/AP_PoolSync](https://github.com/socbrian/AP_PoolSync) integration and is now the active home for development, bug fixes, and feature work.
>
> Since the fork, the integration has been substantially reworked and modernized toward Home Assistant Silver/Gold quality-scale standards.
>
> Special thanks to @socbrian for the reverse-engineering work that made the original linking procedure possible.

### Full local monitoring and control of your AutoPilot PoolSync equipment — no cloud dependency.

PoolSync Custom brings your entire AutoPilot PoolSync ecosystem into Home Assistant. Whether your PoolSync controller is a standalone unit or integrated directly into your heat pump, this integration monitors and controls the full breadth of equipment the controller manages — chlorination, water chemistry, heating, circulation, valves, and group scenes — all over your local network.

## What it does

- Guides you through local push-button linking to obtain the device access password.
- Polls PoolSync locally for status, configuration, and diagnostics.
- Creates devices and entities for the controller and every detected attached device.
- **Supports multiple devices of the same type** — e.g. two ChlorSync chlorinators, multiple heat pumps, or multiple ChemSync controllers — each with its own device and entity set.
- **Controls** chlorination output, water chemistry (pH/ORP), heat-pump climate, circulation pump speed and mode, valves, and group scenes.
- Decodes device fault codes into human-readable labels.
- Exposes optional diagnostic entities such as firmware, board temperatures, and Wi-Fi signal details.
- Updates write controls **immediately** (optimistic UI) and confirms against the device on the next poll.

<img width="759" height="359" alt="image" src="https://github.com/user-attachments/assets/24feff71-7bdd-430e-97a1-5a9a72f85b6a" />
<img width="523" height="535" alt="image" src="https://github.com/user-attachments/assets/6b4429bf-370b-4867-97d8-95f2423b19c4" />
<img width="286" height="545" alt="image" src="https://github.com/user-attachments/assets/5c492cf2-63cb-412c-9333-0a0b0a51b4d8" />


## Requirements

Before setup, make sure:

1. Your PoolSync device is powered on and connected to your local Wi-Fi network.
2. Home Assistant can reach the device on your local network.
3. You know the device IP address.
4. You are running Home Assistant 2025.1.0 or newer.
5. HACS is installed if you plan to install this as a custom repository.

## Compatibility at a glance

- Home Assistant Core 2025.1.0 or newer
- Local network access to the PoolSync device is required
- Works with a **standalone PoolSync controller** or a **PoolSync controller integrated into a heat pump**
- Supports the full AutoPilot PoolSync ecosystem: PoolSync controller, ChlorSync chlorinator, ChemSync chemical controller, heat pumps, circulation pumps, valves, and group scenes
- **Multiple devices of the same type are supported** — each detected ChlorSync, ChemSync, or heat pump gets its own device and entity set
- If you validate additional equipment or firmware combinations, please share results in the community thread or GitHub Discussions so the support list can be tightened over time

## Installation with HACS

### One-click install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ccpk1&repository=AP_PoolSync&category=integration)

### Manual HACS setup

1. Open HACS in Home Assistant.
2. Go to Integrations.
3. Open the menu in the top-right corner and select Custom repositories.
4. Add `https://github.com/ccpk1/AP_PoolSync` as an Integration repository.
5. Search for PoolSync Custom in HACS and install it.
6. Restart Home Assistant.

Manual code edits should not be required for normal installation.

## Initial setup

1. In Home Assistant, go to Settings > Devices & Services.
2. Select Add Integration.
3. Search for PoolSync Custom.
4. Enter the local IP address of the PoolSync device.
5. When prompted, press the Auth or Service button on the physical PoolSync device.

<table>
     <tr>
       <td align="center" valign="top">
         <strong>Prompt:</strong><br />
         <img width="460" alt="link device" src="https://github.com/user-attachments/assets/86c394cd-9d7c-4675-9bcc-9500b157da5f" />
       </td>
       <td align="center" valign="top">
         <strong>Auth Button:</strong><br />
         <img width="487" alt="press auth" src="https://github.com/user-attachments/assets/b957b170-7b41-475a-a700-7836676b4801" />
       </td>
     </tr>
   </table>

6. Wait for Home Assistant to complete local linking and create the config entry.

If linking fails, the flow offers a retry path. If repeated attempts fail, restart the PoolSync device and try again.
<table>
     <tr>
       <td align="center" valign="top">
         <strong>Retry:</strong><br />
         <img width="456" height="270" alt="image" src="https://github.com/user-attachments/assets/7abc8ce0-0421-45ce-8d95-deaff0efaf06" />
       </td>
     </tr>
   </table>



## Supported equipment

This integration supports the full AutoPilot PoolSync ecosystem, whether the controller is standalone or integrated into a heat pump:

- **PoolSync controller** — status, configuration, diagnostics, Wi-Fi, group scenes, and schedules
- **ChlorSync chlorinator** — water temperature, salt level, flow, output control, clear-cell-life action, and diagnostics
- **ChemSync chemical controller** — pH, ORP, acid consumption, setpoints, system mode, prime/boost actions, and diagnostics
- **Heat pumps** — climate control, mode/preset/temperature, sensors, and fault decoding
- **Circulation pumps & valves** — pump speed and mode control, valve position
- **Group scenes** (POOL, WATERFALL, FILTRATION, AMBIANCE, CLEANER) — on/off, duration, and schedules

Support depends on what your specific firmware and attached equipment report through the local API.

## What gets created

The exact entity set depends on the device data exposed by your PoolSync installation, but the integration typically creates the following. When multiple devices of the same type are present (e.g. two ChlorSync units or two heat pumps), each gets its own device and a full set of entities.

### Controller sensors

- Wi-Fi signal strength and Wi-Fi signal status
- Controller board temperature
- Controller date and time
- Firmware and hardware version

### Chlorinator entities

- Water temperature
- Salt level
- Flow rate
- Output setting
- Boost time remaining
- Optional diagnostic sensors such as cell current, voltage, serial number, and firmware details
- A number entity to set chlorinator output percentage
- A button to clear the cell life

### ChemSync (water chemistry) entities

- pH and ORP sensors
- Acid consumption and tank alert threshold
- pH setpoint, ORP setpoint, and max daily feed controls
- A system mode select
- Prime pump and boost action buttons
- Optional diagnostic sensors such as firmware, hardware, and model details

### Heat-pump entities

- A climate entity for the water thermostat
- Active target temperature control
- Mode selection for supported operating modes
- Water and air temperature sensors
- Pool and spa setpoint sensors when reported by the device
- Binary sensors for heat-pump flow, fan, compressor, online state, and fault state

### Pump and valve equipment

When the PoolSync device reports a variable-speed circulation pump and/or motorized valves, the integration creates:

- **Pump mode select** (`select.pump_mode`) — Auto / Manual / Off. In Manual mode the pump runs at the RPM you set; in Auto it follows the active group(s); Off stops it.
- **Pump RPM control** (`number.pump_rpm_control`) — sets the manual RPM. When the pump is running, this reflects the actual current speed.
- **Pump RPM sensor** (`sensor.pump_rpm`) — the current pump speed.
- **Valve position sensor** (`sensor.valve_position`) — the current valve position (e.g. POOL, FOUNTAIN).
- **Pump priming binary sensor** — indicates when the pump is priming.

### Group scenes and schedules

When the PoolSync device reports groups (scenes such as POOL, WATERFALL, FILTRATION, AMBIANCE, CLEANER), the integration creates:

- **Group switches** (`switch.group_*`) — one per group. Turning a group on uses the group's stored default duration (e.g. Waterfall defaults to 6 hours); turning it off stops it immediately.
- **Group schedule switches** (`switch.group_*_schedule`) — one per group. Toggles whether the group's schedule is enabled (its `schedMode`). Turning this on enables the schedule; it does **not** turn the group itself on. Each switch exposes the group's up to 4 schedule slots as a `schedules` attribute (decoded days and times).
- **Group duration** (`number.group_*_duration`) — holds your **preferred** run time for the group. When the group is off, changing the number stores your preference (persisted across restarts) for the next time you turn the group on; when the group is already running, changing it applies the new duration immediately. The controller's actual configured duration is shown as a read-only `controller_duration` reference attribute on the number and group switch so you can always see the device's value. To start a group with a custom one-off duration, use the `set_group_state` service with a `duration`.
- **Group info sensor** (`sensor.group_info`) — shows which groups are active, with per-group duration and end-time attributes.

All write controls (group switches, schedule switches, pump mode, pump RPM, group duration, heat-pump mode/preset/temperature, chlorinator output, ChemSync setpoints) update **immediately** when you change them, then confirm against the device on the next poll. This keeps the controls feeling responsive even when the device is slow to report the change back.

**Services** for more customized control (available in Developer Tools → Services):

- `poolsync_custom.set_group_state(group, state, duration?)` — turn a group on or off with an optional duration. `state` accepts `on`/`off`, `true`/`false`, or `1`/`0`. `duration` accepts minutes (e.g. `90`) or a human-readable value (e.g. `1d 10h 22m`). When omitted, the group's stored default is used.
- `poolsync_custom.set_pump_mode(mode, rpm?)` — set the pump to `auto`, `manual`, or `off`. `rpm` is required for `manual`.

Example — turn the Waterfall group on for 90 minutes:
```yaml
service: poolsync_custom.set_group_state
data:
  group: "WATERFALL"
  state: "on"
  duration: "1h 30m"
```

Example — set the pump to manual at 2000 RPM:
```yaml
service: poolsync_custom.set_pump_mode
data:
  mode: "manual"
  rpm: 2000
```

## Common use cases

### Run a group for a specific duration
Turn the Waterfall on for 90 minutes, then let it stop automatically:
```yaml
service: poolsync_custom.set_group_state
data:
  group: "WATERFALL"
  state: "on"
  duration: "1h 30m"
```

### Set a group's default run time
Change how long a group runs by default when you turn it on. Set the group's
duration number (`number.group_*_duration`) to your preferred minutes. The value
is persisted across restarts and used the next time you turn the group on.

### Run the pump at a fixed speed
Set the pump to manual at a specific RPM:
```yaml
service: poolsync_custom.set_pump_mode
data:
  mode: "manual"
  rpm: 2000
```
Return the pump to automatic (following the active group) with:
```yaml
service: poolsync_custom.set_pump_mode
data:
  mode: "auto"
```

### Enable a group's schedule
Turn on the group's schedule switch (`switch.group_*_schedule`) to let the group
follow its programmed schedule. This does **not** turn the group on immediately —
it only enables the schedule.

### Automate the heat pump
The heat-pump climate entity supports normal Home Assistant climate automations
(turn on/off, set target temperature, set preset mode). For example, heat the
pool to 84°F when the outdoor temperature drops:
```yaml
automation:
  - alias: "Heat pool when cool"
    trigger:
      - platform: numeric_state
        entity_id: sensor.outdoor_temperature
        below: 60
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.poolsync_water_thermostat
        data:
          temperature: 84
```

Some diagnostic entities are disabled by default to keep the default dashboard cleaner.

## See it in action

> Screenshots coming soon.

<!--
### Controller & Devices
![Controller overview](docs/assets/screenshot-controller.png)

### Group Scenes & Schedules
![Group scenes](docs/assets/screenshot-groups.png)

### Heat Pump Climate
![Heat pump climate](docs/assets/screenshot-climate.png)

### Water Chemistry (ChemSync)
![Water chemistry](docs/assets/screenshot-chemsync.png)
-->

## Options

After setup, you can adjust the polling interval:

1. Go to Settings > Devices & Services.
2. Open the PoolSync integration card.
3. Select Configure.
4. Set Update interval in seconds and submit.

The minimum supported interval is 10 seconds.

## Removal

To remove the integration:

1. Go to Settings > Devices & Services.
2. Open the PoolSync integration.
3. Select the menu for the config entry.
4. Choose Delete.

This removes the Home Assistant config entry and its entities. It does not change configuration on the physical PoolSync device.

## Troubleshooting

- Confirm the PoolSync device and Home Assistant are on the same local network and that the configured IP address is correct.
- If the device does not finish linking, restart the PoolSync device and retry the setup flow.
- If the integration becomes unavailable or reports connection reset errors, check Wi-Fi quality at the controller. Weak signal is a common cause of intermittent failures.
- Download diagnostics from the device page in Home Assistant when reporting issues.
- Check Home Assistant logs for `custom_components.poolsync_custom` entries if setup or updates fail.

## ❤️ Support the Project

Building and maintaining a local-first integration like this takes countless hours of development, testing, and covering hardware and tool costs. If PoolSync Custom is making your pool easier to manage, here is how you can help keep the project alive:

⭐ **Star this repository!** If you install this integration and get value out of it, clicking the Star button at the top of the page is the easiest — and free — way to say thanks. It takes two seconds, helps others discover the project, and shows me that the community is actively using it.

☕ **Sponsor or Tip** While stars let me know the integration is alive, a sponsorship or tip is the absolute best way to affirm that the time and money spent building this tool is providing real value. Financial support is never required, but it is the strongest motivation for me to keep fixing bugs, adding features, and maintaining this project long-term.

[Sponsor](https://github.com/sponsors/ccpk1) [Buy Me A Coffee](https://buymeacoffee.com/ccpk1)

## Get help or report issues

- Community thread: [PoolSync Pool / Heat Pump Integration](https://community.home-assistant.io/t/poolsync-pool-heat-pump-integration/682888)
- GitHub issues: [ccpk1/AP_PoolSync/issues](https://github.com/ccpk1/AP_PoolSync/issues)
- GitHub discussions: [ccpk1/AP_PoolSync/discussions](https://github.com/ccpk1/AP_PoolSync/discussions)

When reporting a problem, include diagnostics, relevant logs, the PoolSync firmware or hardware details if known, and what equipment is attached.

## Contributing

Bug reports, testing feedback, and pull requests are welcome. When reporting problems, include the device model if known, what equipment is attached, and diagnostics or log details when possible.

## Disclaimers

🤖 AI-Assisted Development: In today’s age, leveraging AI is one of the few ways a maintainer can realistically build, thoroughly test, and actively support a truly complex, high-quality open-source project. But to be clear, this integration isn't just blindly "vibe coded." While AI acts as a significant force multiplier for the workflow, human oversight dictates the architecture. Every commit is strictly audited, backed by extensive tests, and measured against rigorous Home Assistant development standards to ensure long-term stability.

This integration is not affiliated with or endorsed by AutoPilot Pool Systems. Use it at your own risk.

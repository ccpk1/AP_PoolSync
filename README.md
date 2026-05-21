# 🚨Project moved

Active development for this integration has moved.

As I no longer have the hardware to maintain and test this project, ongoing development, fixes, and updates are now happening here:

[ccpk1/AP_PoolSync](https://github.com/ccpk1/AP_PoolSync)

### Thanks to everyone who used and contributed to this project. Please use the new repository for issues, discussions, and future releases.

---
<br><br><br><br>

# PoolSync Custom Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)


This is a custom integration for Home Assistant to monitor and control AutoPilot PoolSync pool chlorinators and heat pumps over the local network. It does not rely on any cloud services.

## Features

* Local push-button linking to obtain an access password from the PoolSync device.
* Retrieves comprehensive status and configuration data.
* Creates sensors in Home Assistant for key metrics (e.g., water temperature, salt PPM, flow rate, device status).
* Creates binary sensors for online status and other states like faults or service mode.
* **Control Chlorinator Output:** Allows setting the chlorine output percentage via a number entity.
* **Control Heatpump Output:** Allows setting the temperature and mode via a number entity.
* Configurable update interval via an options flow.

## Prerequisites

1.  Your PoolSync device must be connected to your local Wi-Fi network.
2.  You need to know the local IP address of your PoolSync device.
3.  Home Assistant instance (version 2023.1.0 or newer recommended) with HACS (Home Assistant Community Store) installed.

## Installation via HACS

1.  **Ensure HACS is installed.** If not, follow the [HACS installation guide](https://hacs.xyz/docs/setup/download).
2.  **Add Custom Repository:**
    * Open HACS in your Home Assistant.
    * Go to "Integrations".
    * Click the three dots in the top right corner and select "Custom repositories".
    * In the "Repository" field, paste the URL of this GitHub repository (e.g., `https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY_NAME`).
    * In the "Category" field, select "Integration".
    * Click "Add".
3.  **Edit Code:** (Should no loger be needed!!)
    * If the code does not find your Heatpump/Chloronator, you must edit const.py to help
    * You will see `CHLORINATOR_ID = "-1"` and `HEATPUMP_ID = "0"`
    * Above settings will work if you only have a HeatPump
    * If you do not have a chlorinator or heatpump, set the corresponding id to "-1"
    * If you only have one, the one you have will be "0"
    * If you have both, try clorinator "0" and heatpump "1", or try clorinator "1" and heatpump "0"
    * After editing code, you must restart home assistant
    * This should no longer be needed, but I leave it just in case.
5.  **Install Integration:**
    * Search for "PoolSync Custom" in HACS (it might take a moment to appear after adding the custom repository).
    * Click "Install".
    * Restart Home Assistant when prompted.
    * If you already done the push-button linking, you can edit the IDs and restart home assistant and do not need to redo the linking procedure

## Configuration

1.  **Go to Settings > Devices & Services.**
2.  Click the **+ ADD INTEGRATION** button in the bottom right.
3.  Search for "PoolSync Custom" and click on it.
4.  **Enter IP Address:**
    * You will be prompted to enter the local IP address of your PoolSync device. Click "Submit".
5.  **Push-Button Linking:**
    * The integration will attempt to initiate the linking process by sending a command to your PoolSync device.
    * You will be prompted to **press the "Auth" button on your PoolSync device**. (Sometimes this does not show, and only shows a submit button)
    * The configuration flow will show the approximate time remaining to press the button.
    * Once the button is pressed and the device responds, the integration will retrieve an access password and the device's MAC address.
6.  **Setup Complete:**
    * If successful, the integration will be added, and entities for your PoolSync device will be created.
    * If there's an error (e.g., device not found, button not pressed in time), you'll see an error message, and you can try again. You may need to restart your PoolSync device if linking repeatedly fails.

## Entities

This integration will create several entities, including (but not limited to):

* **Sensors (ChlorSync):**
    * Water Temperature
    * Salt Level (PPM)
    * Flow Rate
    * Chlorinator Output Setting (current setting read from device)
    * Boost Time Remaining
    * Various diagnostic sensors (Wi-Fi RSSI, board temperature, cell currents/voltages, firmware versions - some may be disabled by default).
* **Sensors (HeatPump):** Thanks to @ccpk1 and others on home assistant forum
    * Water Temperature
    * Setpoint Temperature
    * Output Temperature
    * Air Temperature
    * Mode (0-off, 1-heat, 2-cool)
* **Binary Sensors:**
    * PoolSync Online Status
    * ChlorSync Module Online Status
    * System Fault Status
    * ChlorSync Fault Status
    * Service Mode Active
    * HeatPump Module Online Status
    * Heat Pump Fan
    * Heat Pump Compressor
    * Heat Pump Flow
* **Number Controls:**
    * Chlorinator Output (allows setting the output percentage, typically 0-100%)
    * HeatPump Temperature Set Point (allows setting the output percentage, typically 40-104 F)
    * HeatPump Mode (0-off, 1-on, 2-cool)

The exact entities will depend on the data reported by your specific PoolSync model and firmware. Some diagnostic entities may be disabled by default and can be enabled via the entity settings in Home Assistant.
## Templates
If you want a simple switch to turn heater on/off:
   * Make a switch template (Settings->Devices & Servies-> Helpers Tab). type template, then select switch template
   * Set value template to `{{is_state('sensor.poolsync_XXXXX_mode', '1')}}` where XXXX is the MAC of your poolsync (should come up if type poolsync)
   * Change `on action` to number, entity number.poolsync_heat_mode to 1
   * Change `off action` to number, entity number.poolsync_heat_mode to 0
   * Associate with the poolsync device under Device (optional: this will make it show in the integration's list of entities)
   * You can make another swtich with on action to 2 if you want cool mode

If you want a sensor that shows if set to Off/Heat/Cool
   * Make a switch template (Settings->Devices & Servies-> Helpers Tab). type template, then select sensor template
   * Set value template to below where XXXX is the MAC of your poolsync (should come up if type poolsync)
   ```
      {% set t = states('sensor.poolsync_XXX_mode') | int(0) %}
          {% if t == 0 %} Off
          {% elif t == 1 %} Heat
          {% elif t == 2 %} Cool
          {% else %} Unknown
          {% endif %}
   ```
   * Associate with the poolsync device under Device (optional: this will make it show in the integration's list of entities)

## Options

After setting up the integration, you can adjust the polling interval:
1. Go to **Settings > Devices & Services**.
2. Find the PoolSync integration card and click **Configure**.
3. Adjust the "Update interval (seconds)" (e.g., 30, 60, 120; minimum 10 seconds) and click **Submit**. The integration will reload with the new interval.

## MQTT Integration (Optional)

If you wish to publish the state of these entities to an MQTT broker, you can use Home Assistant's built-in MQTT features:

* **MQTT Statestream:** Publishes state changes of entities to an MQTT broker.
* **MQTT Eventstream:** Publishes all events (including state changes) to an MQTT broker.

Configure these in your `configuration.yaml` as per the Home Assistant documentation. This custom integration creates the entities within Home Assistant; you can then decide how to share their states.

## Troubleshooting

* Ensure your PoolSync device is powered on and connected to the same network as your Home Assistant instance.
* Double-check the IP address of the PoolSync device.
* If linking fails, try restarting the PoolSync device and then attempt the configuration again.
* Check Home Assistant logs (Settings > System > Logs) for any error messages related to `poolsync_custom`. Enable debug logging for `custom_components.poolsync_custom` if needed (see Home Assistant documentation on how to set logger levels).
* Use the Diagnostics feature (on the device page in HA, click the three dots, then "Download diagnostics") to download raw data from the integration, which can be helpful for debugging.
* If your connection drops out (connection reset by peer error), a stronger WiFi signal is needed. Get an extender/mesh network. Ensure it is connected to the closest node in your mesh.  Hitting the reboot button on the PoolSync will fix it temporarily until you can get a better signal.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request if you have ideas for improvements or bug fixes. Remember to replace placeholder GitHub usernames/repository names in the documentation if you fork this project.

## Disclaimer

This integration is not affiliated with or endorsed by AutoPilot Pool Systems. Use at your own risk.

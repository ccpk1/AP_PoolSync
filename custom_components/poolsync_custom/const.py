"""Constants for the PoolSync Custom integration."""

# Domain for the integration (must match folder name and manifest.json)
DOMAIN = "poolsync_custom"

CHLORINATOR_ID = "-1"
HEATPUMP_ID = "0"

# Configuration keys used in config_flow and config_entry
CONF_IP_ADDRESS = "ip_address"
CONF_PASSWORD = "password"  # Stored in config entry after successful linking

# API Endpoints
API_PATH_PUSHLINK_START = "/api/poolsync?cmd=pushLink&start"
API_PATH_PUSHLINK_STATUS = "/api/poolsync?cmd=pushLink&status"
API_PATH_ALL_DATA = "/api/poolsync?cmd=poolSync&all"

# API response keys
API_RESPONSE_TIME_REMAINING = "timeRemaining"
API_RESPONSE_PASSWORD = "password"
API_RESPONSE_MAC_ADDRESS = "macAddress"  # Used as unique ID

# Default values
DEFAULT_NAME = "PoolSync"  # Default name for the device
DEFAULT_SCAN_INTERVAL = 120  # Default polling interval in seconds

# Headers required for API communication
HEADER_AUTHORIZATION = "authorization"
HEADER_USER = "user"
# Static User header value from your curl example
USER_HEADER_VALUE = "b167ecc8-87ce-47da-9b7d-cab632a2eeba"

# Device Info (used for Home Assistant device registry)
MANUFACTURER = "AutoPilot"
MODEL = "PoolSync"  # This can be refined by data from device in coordinator.py

# Pushlink process constants
PUSHLINK_CHECK_INTERVAL_S = 5  # How often to poll for pushlink status (seconds)
PUSHLINK_TIMEOUT_S = 120  # How long to wait for the user to press the button (seconds)

# Other constants
HTTP_TIMEOUT = 30  # <<< Increased timeout for HTTP requests (seconds)

# Wi-Fi RSSI grading thresholds from the manufacturer guidance.
# The device's separate "excellent" range is intentionally folded into "good"
# for the simplified Home Assistant status sensor.
WIFI_RSSI_GOOD_MIN = -75
WIFI_RSSI_FAIR_MIN = -80

# Platform
PLATFORMS = ["sensor", "binary_sensor", "number", "select", "button", "climate"]

# Option keys
OPTION_SCAN_INTERVAL = "scan_interval"

# Equipment type constants (from equip[N][0], APK VIRTUAL_EQUIPMENT_TYPE)
# Status display functions per type: getPumpStatus, getValveStatus, getRelayStatus,
# getHpStatus, getChlorStatus, getLightStatus
EQUIP_TYPE_VS_PUMP = 0  # VS pump or single-speed pump
EQUIP_TYPE_VALVE = 1  # Motorized valve actuator
EQUIP_TYPE_RELAY = 2  # Generic relay
EQUIP_TYPE_HEAT_PUMP = 3  # Heat pump (temperature-based)
EQUIP_TYPE_CHLORINATOR = 4  # ChlorSync cell
EQUIP_TYPE_LIGHT = 5  # Pool/spa light

# Pump RPM multiplier (internal units × 50 = real RPM)
PUMP_RPM_FACTOR = 50

# Best-guess write key for pump RPM control.
# Unknown until API traffic is captured; trial-and-error with beta users.
EQUIP_PUMP_RPM_WRITE_KEY = "rpm"

# Equipment array indices (from APK VIRTUAL_EQUIPMENT_* constants)
EQUIP_IDX_TYPE = 0
EQUIP_IDX_NAME = 1
EQUIP_IDX_NAME_ID = 2
EQUIP_IDX_SUB_TYPE = 3
EQUIP_IDX_PORT = 4
EQUIP_IDX_TIME_START = 5
EQUIP_IDX_TIME_LEFT = 6
EQUIP_IDX_STATE = 7
EQUIP_IDX_PARAM_8 = 8
EQUIP_IDX_PARAM_9 = 9
EQUIP_IDX_PARAM_10 = 10
EQUIP_IDX_PARAM_11 = 11
EQUIP_IDX_PARAM_12 = 12
EQUIP_IDX_PARAM_13 = 13
EQUIP_IDX_PARAM_14 = 14

# Pump-specific aliases
PUMP_IDX_CURRENT_SPEED = EQUIP_IDX_STATE  # state × 50 = RPM
PUMP_IDX_PRIMING_FLAG = EQUIP_IDX_PARAM_14  # Confirmed by APK pump display logic

# Valve-specific aliases
VALVE_IDX_MOVE_TIME = EQUIP_IDX_TIME_START  # Timer duration for valve movement
VALVE_IDX_POSITIONS_START = EQUIP_IDX_PARAM_8  # Pairs of (name, value) from here onward

# Group config array indices
GROUP_IDX_STATE = 3

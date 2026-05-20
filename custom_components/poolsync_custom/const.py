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

# Platform
PLATFORMS = ["sensor", "binary_sensor", "number"]

# Option keys
OPTION_SCAN_INTERVAL = "scan_interval"

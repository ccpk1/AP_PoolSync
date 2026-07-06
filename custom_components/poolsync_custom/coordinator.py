"""DataUpdateCoordinator for the PoolSync Custom integration."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any, Literal

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    PoolSyncApiAuthError,
    PoolSyncApiClient,
    PoolSyncApiCommunicationError,
    PoolSyncApiError,
)
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .runtime import (
    HEAT_PUMP_CONFIG_MODE_AUTO,
    HEAT_PUMP_CONFIG_MODE_COOL,
    HEAT_PUMP_CONFIG_MODE_HEAT,
    HEAT_PUMP_MODE_AUTO_POOL,
    HEAT_PUMP_MODE_COOL_POOL,
    HEAT_PUMP_MODE_HEAT_POOL,
    HEAT_PUMP_MODE_HEAT_SPA,
    HEAT_PUMP_MODE_OFF,
    HEAT_PUMP_POOL_SPA_MODE_SPA,
    HEAT_PUMP_PRESET_POOL,
    HEAT_PUMP_PRESET_SPA,
    PoolSyncDeviceRole,
    PoolSyncHeatPumpClimateHvacMode,
    PoolSyncHeatPumpClimatePresetMode,
    PoolSyncHeatPumpModeContext,
    PoolSyncParsedData,
    ensure_parsed_data,
    get_heat_pump_climate_preset_mode,
    get_heat_pump_runtime,
    get_role_data,
    parse_poolsync_runtime_data,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_CONTROLLER_NAME_PATTERN = re.compile(
    r"^PoolSync(?:\s*(?:™|®|tm))?$",
    re.IGNORECASE,
)
_DEFAULT_CHLORINATOR_NAME_PATTERN = re.compile(
    r"^ChlorSync(?:\s*(?:™|®|tm))?$",
    re.IGNORECASE,
)
_MAX_STALE_TRANSPORT_FAILURES = 3

type PoolSyncDeviceInfoRole = Literal["controller", "chlorinator", "heat_pump"]
type PoolSyncFailureClass = Literal[
    "auth_error",
    "transport_error",
    "malformed_response",
    "api_error",
    "unexpected_error",
]
type PoolSyncFailureContext = dict[str, Any]


class PoolSyncDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching PoolSync data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: PoolSyncApiClient,
        password: str,  # Password needed for API calls
        update_interval_seconds: int,
        config_entry_id: str,  # For logging/context
        mac_address: str,  # For unique device identification
    ) -> None:
        """Initialize the data update coordinator."""
        self.api_client = api_client
        self._password = (
            password  # Store password for use by entities/services via coordinator
        )
        self.config_entry_id = config_entry_id
        self.mac_address = mac_address
        self._ip_address = api_client.ip_address
        self._unavailable_logged = False
        self.parsed_data: PoolSyncParsedData | None = None
        self.last_failure_class: PoolSyncFailureClass | None = None
        self.last_failure_detail: str | None = None
        self.last_failure_context: PoolSyncFailureContext | None = None
        self._consecutive_transport_failures = 0

        logger_name = f"{DOMAIN}({self.mac_address or self._ip_address})"

        super().__init__(
            hass,
            _LOGGER,
            name=logger_name,
            update_interval=timedelta(seconds=update_interval_seconds),
            update_method=self._async_update_data,
        )
        _LOGGER.info(
            "PoolSync coordinator initialized for %s (MAC: %s, IP: %s) with update interval %d seconds",
            self.name,
            self.mac_address,
            self._ip_address,
            update_interval_seconds,
        )

    def _log_unavailable_once(self, detail: str) -> None:
        """Log a one-time transition to unavailable."""
        if self._unavailable_logged:
            return

        _LOGGER.info("PoolSync device %s is unavailable: %s", self.name, detail)
        self._unavailable_logged = True

    def _log_recovered_if_needed(self) -> None:
        """Log when the device comes back online after an outage."""
        if not self._unavailable_logged:
            return

        _LOGGER.info("PoolSync device %s is back online", self.name)
        self._unavailable_logged = False

    def _set_last_failure(
        self,
        failure_class: PoolSyncFailureClass,
        detail: str,
        context: PoolSyncFailureContext | None = None,
    ) -> None:
        """Record the most recent classified refresh failure."""
        self.last_failure_class = failure_class
        self.last_failure_detail = detail
        self.last_failure_context = context

    def _clear_last_failure(self) -> None:
        """Clear any previously recorded refresh failure."""
        self.last_failure_class = None
        self.last_failure_detail = None
        self.last_failure_context = None

    @property
    def password(self) -> str:
        """Return the stored PoolSync API password."""
        return self._password

    def get_parsed_data(self, *, refresh: bool = False) -> PoolSyncParsedData:
        """Return parsed runtime data, deriving it from raw data if needed."""
        return ensure_parsed_data(self, refresh=refresh)

    async def async_manual_refresh(self) -> None:
        """Run an immediate refresh using the normal coordinator update path."""
        await self.async_refresh()

        if not self.last_update_success:
            raise HomeAssistantError("PoolSync refresh failed")

    def _get_write_role_device_id(
        self,
        *,
        role: PoolSyncDeviceRole,
        description: str,
    ) -> str:
        """Resolve the device ID for a write target role."""
        if not self.password:
            raise HomeAssistantError("API password not available to set value")

        role_data = get_role_data(self.get_parsed_data(), role)
        if role_data.device_id is None or not role_data.is_present:
            raise HomeAssistantError(f"PoolSync {description} target is not available")

        return role_data.device_id

    def _raise_write_error(self, description: str, err: Exception) -> None:
        """Translate write-time API failures into user-facing Home Assistant errors."""
        if isinstance(err, HomeAssistantError):
            raise err

        if isinstance(err, PoolSyncApiAuthError):
            raise HomeAssistantError(
                f"Authentication failed while setting {description}"
            ) from err

        if isinstance(err, PoolSyncApiCommunicationError):
            raise HomeAssistantError(
                f"Communication failed while setting {description}: {err}"
            ) from err

        if isinstance(err, PoolSyncApiError):
            raise HomeAssistantError(
                f"API error while setting {description}: {err}"
            ) from err

        raise HomeAssistantError(f"Failed to set {description}: {err}") from err

    async def _async_write_role_config(
        self,
        *,
        role: PoolSyncDeviceRole,
        key_id: str,
        value: int,
        description: str,
    ) -> None:
        """Write a config value for a resolved device role and refresh state."""
        await self._async_write_role_configs(
            role=role,
            updates={key_id: value},
            description=description,
        )

    async def _async_write_role_configs(
        self,
        *,
        role: PoolSyncDeviceRole,
        updates: dict[str, int],
        description: str,
    ) -> None:
        """Write multiple config values for a resolved device role and refresh once."""
        device_id = self._get_write_role_device_id(role=role, description=description)

        try:
            for key_id, value in updates.items():
                await self.api_client.async_set_device_config_value(
                    device_id=device_id,
                    key_id=key_id,
                    value=value,
                    password=self.password,
                )
            await self.async_request_refresh()
        except Exception as err:
            self._raise_write_error(description, err)

    async def async_set_chlorinator_output(self, value: int) -> None:
        """Set the chlorinator output level."""
        await self._async_write_role_config(
            role="chlorinator",
            key_id="chlorOutput",
            value=value,
            description="chlorinator output",
        )

    async def async_set_heat_pump_setpoint(self, value: int) -> None:
        """Set the heat pump setpoint."""
        await self.async_set_heat_pump_pool_setpoint(value)

    async def async_set_heat_pump_pool_setpoint(self, value: int) -> None:
        """Set the heat pump pool setpoint."""
        await self._async_write_role_config(
            role="heat_pump",
            key_id="setpoint",
            value=value,
            description="heat pump pool setpoint",
        )

    async def async_set_heat_pump_spa_setpoint(self, value: int) -> None:
        """Set the heat pump spa setpoint."""
        await self._async_write_role_config(
            role="heat_pump",
            key_id="spaSetpoint",
            value=value,
            description="heat pump spa setpoint",
        )

    async def async_set_heat_pump_active_target(
        self,
        value: int,
        preset_mode: PoolSyncHeatPumpClimatePresetMode | None = None,
    ) -> None:
        """Set the active target temperature for the current heat-pump context."""
        runtime = get_heat_pump_runtime(self.get_parsed_data())
        if runtime is None:
            raise HomeAssistantError("PoolSync heat pump target is not available")

        if (
            preset_mode == HEAT_PUMP_PRESET_SPA
            and runtime.capabilities.supports_separate_spa_setpoint
        ):
            await self.async_set_heat_pump_spa_setpoint(value)
            return

        if (
            runtime.mode_context == HEAT_PUMP_MODE_HEAT_SPA
            and runtime.capabilities.supports_separate_spa_setpoint
        ):
            await self.async_set_heat_pump_spa_setpoint(value)
            return

        await self.async_set_heat_pump_pool_setpoint(value)

    async def async_set_heat_pump_mode(self, value: int) -> None:
        """Set the heat pump mode."""
        await self._async_write_role_config(
            role="heat_pump",
            key_id="mode",
            value=value,
            description="heat pump mode",
        )

    async def async_set_heat_pump_mode_context(
        self, mode_context: PoolSyncHeatPumpModeContext
    ) -> None:
        """Set the heat-pump mode using the contextual runtime model."""
        if mode_context == HEAT_PUMP_MODE_OFF:
            updates = {"mode": 0, "poolSpaMode": 0}
        elif mode_context == HEAT_PUMP_MODE_HEAT_POOL:
            updates = {"mode": HEAT_PUMP_CONFIG_MODE_HEAT, "poolSpaMode": 0}
        elif mode_context == HEAT_PUMP_MODE_COOL_POOL:
            updates = {"mode": HEAT_PUMP_CONFIG_MODE_COOL, "poolSpaMode": 0}
        elif mode_context == HEAT_PUMP_MODE_AUTO_POOL:
            updates = {"mode": HEAT_PUMP_CONFIG_MODE_AUTO, "poolSpaMode": 0}
        elif mode_context == HEAT_PUMP_MODE_HEAT_SPA:
            updates = {
                "mode": HEAT_PUMP_CONFIG_MODE_HEAT,
                "poolSpaMode": HEAT_PUMP_POOL_SPA_MODE_SPA,
            }
        else:
            raise HomeAssistantError(f"Unsupported heat pump mode: {mode_context}")

        await self._async_write_role_configs(
            role="heat_pump",
            updates=updates,
            description="heat pump mode",
        )

    async def async_set_heat_pump_climate_mode(
        self,
        *,
        hvac_mode: PoolSyncHeatPumpClimateHvacMode,
        preset_mode: PoolSyncHeatPumpClimatePresetMode | None = None,
    ) -> None:
        """Set heat-pump climate state using HVAC and preset semantics."""
        runtime = get_heat_pump_runtime(self.get_parsed_data())
        if runtime is None:
            raise HomeAssistantError("PoolSync heat pump mode is not available")

        if hvac_mode == "off":
            await self.async_set_heat_pump_mode_context(HEAT_PUMP_MODE_OFF)
            return

        resolved_preset = (
            preset_mode
            or get_heat_pump_climate_preset_mode(self.get_parsed_data())
            or HEAT_PUMP_PRESET_POOL
        )

        if hvac_mode == "heat":
            if not runtime.capabilities.supports_heating:
                raise HomeAssistantError("Heating mode is not supported")
            await self.async_set_heat_pump_mode_context(
                HEAT_PUMP_MODE_HEAT_SPA
                if (
                    resolved_preset == HEAT_PUMP_PRESET_SPA
                    and runtime.capabilities.supports_pool_spa_mode
                )
                else HEAT_PUMP_MODE_HEAT_POOL
            )
            return

        if hvac_mode == "cool":
            if not runtime.capabilities.supports_cooling:
                raise HomeAssistantError("Cooling mode is not supported")
            await self.async_set_heat_pump_mode_context(HEAT_PUMP_MODE_COOL_POOL)
            return

        if hvac_mode == "auto":
            if not (
                runtime.capabilities.supports_heating
                and runtime.capabilities.supports_cooling
            ):
                raise HomeAssistantError("Auto mode is not supported")
            await self.async_set_heat_pump_mode_context(HEAT_PUMP_MODE_AUTO_POOL)
            return

        raise HomeAssistantError(f"Unsupported climate HVAC mode: {hvac_mode}")

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch data from the PoolSync device API.
        This method is called by the DataUpdateCoordinator base class.
        """
        _LOGGER.debug("Coordinator %s: Attempting to fetch data.", self.name)
        try:
            data = await self.api_client.get_all_data(self._password)
            _LOGGER.debug(
                "Coordinator %s: Successfully fetched data. Keys: %s",
                self.name,
                data.keys() if isinstance(data, dict) else "N/A",
            )
            if not isinstance(data, dict) or not all(
                k in data for k in ["poolSync", "devices"]
            ):
                self._set_last_failure(
                    "malformed_response",
                    "malformed data received",
                    {
                        "status_code": None,
                        "has_response_body": False,
                        "retryable": True,
                    },
                )
                self._log_unavailable_once("malformed data received")
                _LOGGER.error(
                    "Coordinator %s: Fetched data is not a dict or essential keys ('poolSync', 'devices') are missing. Data: %s",
                    self.name,
                    data,
                )
                raise UpdateFailed(
                    f"Malformed data received from {self.name}: essential keys missing or data not a dict."
                )

            self.parsed_data = parse_poolsync_runtime_data(data)
            self._consecutive_transport_failures = 0
            self._clear_last_failure()
            self._log_recovered_if_needed()
            return data

        except UpdateFailed:
            raise

        except PoolSyncApiAuthError as err:
            self._set_last_failure(
                "auth_error",
                str(err),
                {
                    "status_code": err.status_code,
                    "has_response_body": bool(err.body),
                    "retryable": False,
                },
            )
            _LOGGER.error(
                "Coordinator %s: Authentication error fetching data: %s (Status: %s)",
                self.name,
                err,
                getattr(err, "status_code", "N/A"),
            )
            raise ConfigEntryAuthFailed(
                f"Authentication failed for {self.name}. Password may be invalid."
            ) from err

        except PoolSyncApiCommunicationError as err:
            self._consecutive_transport_failures += 1
            self._set_last_failure(
                "transport_error",
                str(err),
                {
                    "status_code": err.status_code,
                    "has_response_body": bool(err.body),
                    "retryable": True,
                },
            )
            self._log_unavailable_once(str(err))
            _LOGGER.warning(
                "Coordinator %s: Communication error fetching data: %s. Will retry.",
                self.name,
                err,
            )
            if (
                isinstance(self.data, dict)
                and self._consecutive_transport_failures
                <= _MAX_STALE_TRANSPORT_FAILURES
            ):
                _LOGGER.warning(
                    "Coordinator %s: Keeping last known PoolSync data after transient communication failure %d/%d.",
                    self.name,
                    self._consecutive_transport_failures,
                    _MAX_STALE_TRANSPORT_FAILURES,
                )
                return self.data

            raise UpdateFailed(
                f"Error communicating with PoolSync device {self.name}: {err}"
            ) from err

        except PoolSyncApiError as err:
            failure_class: PoolSyncFailureClass = (
                "malformed_response"
                if "Invalid JSON response" in str(err)
                else "api_error"
            )
            self._set_last_failure(
                failure_class,
                str(err),
                {
                    "status_code": err.status_code,
                    "has_response_body": bool(err.body),
                    "retryable": failure_class != "malformed_response",
                },
            )
            self._log_unavailable_once(str(err))
            _LOGGER.error(
                "Coordinator %s: API error fetching data: %s (Status: %s, Body: %s)",
                self.name,
                err,
                getattr(err, "status_code", "N/A"),
                getattr(err, "body", "N/A"),
            )
            raise UpdateFailed(f"API error for {self.name}: {err}") from err

        except Exception as err:
            self._set_last_failure(
                "unexpected_error",
                str(err),
                {
                    "status_code": None,
                    "has_response_body": False,
                    "retryable": False,
                },
            )
            self._log_unavailable_once(type(err).__name__)
            _LOGGER.exception(
                "Coordinator %s: Unexpected error fetching data: %s", self.name, err
            )
            raise UpdateFailed(f"Unexpected error updating {self.name}: {err}") from err

    @property
    def device_info(self) -> DeviceInfo:
        """Return controller device information for backward compatibility."""
        return self.get_device_info("controller")

    def get_device_info(self, role: PoolSyncDeviceInfoRole) -> DeviceInfo:
        """Return device information for a specific PoolSync device boundary."""
        parsed_data = (
            ensure_parsed_data(self)
            if self.parsed_data is None and isinstance(self.data, dict)
            else self.parsed_data
        )

        if role == "controller":
            return self._get_controller_device_info(parsed_data)

        return self._get_attached_device_info(role, parsed_data)

    def _get_controller_identifier(self) -> tuple[str, str]:
        """Return the stable device registry identifier for the controller."""
        return (DOMAIN, self.mac_address)

    def _get_attached_identifier(self, role: PoolSyncDeviceInfoRole) -> tuple[str, str]:
        """Return the stable device registry identifier for an attached device."""
        return (DOMAIN, f"{self.mac_address}_{role}")

    def _get_controller_name(self, parsed_data: PoolSyncParsedData | None) -> str:
        """Return the best available controller device name."""
        config_name_from_api: str | None = None

        if (
            parsed_data is not None
            and (system_config := parsed_data.system.config) is not None
        ):
            config_name_from_api = system_config.get("name")

        if (
            isinstance(config_name_from_api, str)
            and config_name_from_api.strip()
            and not _DEFAULT_CONTROLLER_NAME_PATTERN.fullmatch(
                config_name_from_api.strip()
            )
        ):
            return config_name_from_api

        if isinstance(config_name_from_api, str) and config_name_from_api.strip():
            return DEFAULT_NAME

        if self.mac_address and len(self.mac_address) >= 6:
            return f"{DEFAULT_NAME} {self.mac_address[-6:]}"

        return DEFAULT_NAME

    def _get_controller_device_info(
        self, parsed_data: PoolSyncParsedData | None
    ) -> DeviceInfo:
        """Build device info for the PoolSync controller."""
        sw_version = None
        hw_version = None

        if (
            parsed_data is not None
            and (system_info := parsed_data.system.system) is not None
        ):
            sw_version = system_info.get("fwVersion")
            hw_version = system_info.get("hwVersion")

        return DeviceInfo(
            identifiers={self._get_controller_identifier()},
            name=self._get_controller_name(parsed_data),
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=str(sw_version) if sw_version is not None else None,
            hw_version=str(hw_version) if hw_version is not None else None,
            configuration_url=f"http://{self._ip_address}",
        )

    def _get_attached_device_info(
        self,
        role: Literal["chlorinator", "heat_pump"],
        parsed_data: PoolSyncParsedData | None,
    ) -> DeviceInfo:
        """Build device info for an attached device role."""
        role_data = (
            get_role_data(parsed_data, role) if parsed_data is not None else None
        )
        node_attr = role_data.node_attr if role_data is not None else None
        system_info = role_data.system if role_data is not None else None

        default_name = "Chlorinator" if role == "chlorinator" else "Heat Pump"
        default_model = "ChlorSync" if role == "chlorinator" else "Heat Pump"
        device_name = default_name
        model_name = default_model
        sw_version = None
        hw_version = None

        def _normalize_attached_name(name: str) -> str:
            """Normalize known vendor default attached-device names."""
            if role == "chlorinator" and _DEFAULT_CHLORINATOR_NAME_PATTERN.fullmatch(
                name.strip()
            ):
                return "ChlorSync"

            return name

        if (
            node_attr is not None
            and isinstance(node_attr.get("name"), str)
            and node_attr.get("name")
        ):
            device_name = _normalize_attached_name(node_attr["name"])
            model_name = _normalize_attached_name(node_attr["name"])

        if system_info is not None:
            if isinstance(system_info.get("modelNum"), str) and system_info.get(
                "modelNum"
            ):
                model_name = system_info["modelNum"]

            if role == "heat_pump":
                sw_version = system_info.get("appFwVersion")
                hw_version = system_info.get("hwVersion")
            else:
                sw_version = system_info.get("fwVersion") or system_info.get(
                    "drvFwVersion"
                )
                hw_version = system_info.get("hwVersion") or system_info.get(
                    "drvHwVersion"
                )

        return DeviceInfo(
            identifiers={self._get_attached_identifier(role)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=str(model_name) if model_name else default_model,
            sw_version=str(sw_version) if sw_version is not None else None,
            hw_version=str(hw_version) if hw_version is not None else None,
            via_device=self._get_controller_identifier(),
        )

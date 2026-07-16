"""DataUpdateCoordinator for the PoolSync Custom integration."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any, Literal

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    PoolSyncApiAuthError,
    PoolSyncApiClient,
    PoolSyncApiCommunicationError,
    PoolSyncApiError,
)
from .const import (
    DEFAULT_NAME,
    DOMAIN,
    EQUIP_PUMP_RPM_WRITE_KEY,
    GROUP_IDX_STATE,
    MANUFACTURER,
    MODEL,
    PUMP_RPM_FACTOR,
)
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
    ROLE_KEY_REGISTRY,
    PoolSyncDeviceRole,
    PoolSyncEquipmentData,
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

_DEFAULT_CHLORINATOR_NAME_PATTERN = re.compile(
    r"^ChlorSync(?:\s*(?:™|®|tm))?$",
    re.IGNORECASE,
)
_DEFAULT_HEATPUMP_NAME_PATTERN = re.compile(
    r"^Heat\s*Pump(?:\s*(?:™|®|tm))?$",
    re.IGNORECASE,
)
_MAX_STALE_TRANSPORT_FAILURES = 3

type PoolSyncDeviceInfoRole = str
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
        index: int = 0,
    ) -> str:
        """Resolve the device ID for a write target role."""
        if not self.password:
            raise HomeAssistantError("API password not available to set value")

        role_data = get_role_data(self.get_parsed_data(), role, index=index)
        if role_data is None or role_data.device_id is None or not role_data.is_present:
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
        index: int = 0,
    ) -> None:
        """Write a config value for a resolved device role and refresh state."""
        await self._async_write_role_configs(
            role=role,
            updates={key_id: value},
            description=description,
            index=index,
        )

    async def _async_write_role_configs(
        self,
        *,
        role: PoolSyncDeviceRole,
        updates: dict[str, int],
        description: str,
        index: int = 0,
    ) -> None:
        """Write multiple config values for a resolved device role and refresh once."""
        device_id = self._get_write_role_device_id(
            role=role, description=description, index=index
        )

        try:
            for key_id, value in updates.items():
                await self.api_client.async_set_device_config_value(
                    device_id=device_id,
                    key_id=key_id,
                    value=value,
                    password=self.password,
                )
            await self.async_request_refresh()
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self._raise_write_error(description, err)

    async def async_set_chlorinator_output(self, value: int, index: int = 0) -> None:
        """Set the chlorinator output level."""
        await self._async_write_role_config(
            role="chlorinator",
            key_id="chlorOutput",
            value=value,
            description="chlorinator output",
            index=index,
        )

    async def async_set_heat_pump_setpoint(self, value: int, index: int = 0) -> None:
        """Set the heat pump setpoint."""
        await self.async_set_heat_pump_pool_setpoint(value, index=index)

    async def async_set_heat_pump_pool_setpoint(
        self, value: int, index: int = 0
    ) -> None:
        """Set the heat pump pool setpoint."""
        await self._async_write_role_config(
            role="heat_pump",
            key_id="setpoint",
            value=value,
            description="heat pump pool setpoint",
            index=index,
        )

    async def async_set_heat_pump_spa_setpoint(
        self, value: int, index: int = 0
    ) -> None:
        """Set the heat pump spa setpoint."""
        await self._async_write_role_config(
            role="heat_pump",
            key_id="spaSetpoint",
            value=value,
            description="heat pump spa setpoint",
            index=index,
        )

    async def async_set_heat_pump_active_target(
        self,
        value: int,
        preset_mode: PoolSyncHeatPumpClimatePresetMode | None = None,
        index: int = 0,
    ) -> None:
        """Set the active target temperature for the current heat-pump context."""
        runtime = get_heat_pump_runtime(self.get_parsed_data())
        if runtime is None:
            raise HomeAssistantError("PoolSync heat pump target is not available")

        if (
            preset_mode == HEAT_PUMP_PRESET_SPA
            and runtime.capabilities.supports_separate_spa_setpoint
        ):
            await self.async_set_heat_pump_spa_setpoint(value, index=index)
            return

        if (
            runtime.mode_context == HEAT_PUMP_MODE_HEAT_SPA
            and runtime.capabilities.supports_separate_spa_setpoint
        ):
            await self.async_set_heat_pump_spa_setpoint(value, index=index)
            return

        await self.async_set_heat_pump_pool_setpoint(value, index=index)

    async def async_set_heat_pump_mode(self, value: int, index: int = 0) -> None:
        """Set the heat pump mode."""
        await self._async_write_role_config(
            role="heat_pump",
            key_id="mode",
            value=value,
            description="heat pump mode",
            index=index,
        )

    async def async_set_heat_pump_mode_context(
        self, mode_context: PoolSyncHeatPumpModeContext, index: int = 0
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
            index=index,
        )

    async def async_set_heat_pump_climate_mode(
        self,
        *,
        hvac_mode: PoolSyncHeatPumpClimateHvacMode,
        preset_mode: PoolSyncHeatPumpClimatePresetMode | None = None,
        index: int = 0,
    ) -> None:
        """Set heat-pump climate state using HVAC and preset semantics."""
        runtime = get_heat_pump_runtime(self.get_parsed_data())
        if runtime is None:
            raise HomeAssistantError("PoolSync heat pump mode is not available")

        if hvac_mode == "off":
            await self.async_set_heat_pump_mode_context(HEAT_PUMP_MODE_OFF, index=index)
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
                else HEAT_PUMP_MODE_HEAT_POOL,
                index=index,
            )
            return

        if hvac_mode == "cool":
            if not runtime.capabilities.supports_cooling:
                raise HomeAssistantError("Cooling mode is not supported")
            await self.async_set_heat_pump_mode_context(
                HEAT_PUMP_MODE_COOL_POOL, index=index
            )
            return

        if hvac_mode == "auto":
            if not (
                runtime.capabilities.supports_heating
                and runtime.capabilities.supports_cooling
            ):
                raise HomeAssistantError("Auto mode is not supported")
            await self.async_set_heat_pump_mode_context(
                HEAT_PUMP_MODE_AUTO_POOL, index=index
            )
            return

        raise HomeAssistantError(f"Unsupported climate HVAC mode: {hvac_mode}")

    async def async_set_chem_config(self, key: str, value: int, index: int = 0) -> None:
        """Set a ChemSync configuration value by entity key.

        Maps entity keys to API config field names.
        """
        _key_map: dict[str, str] = {
            "chem_ph_setpoint": "phSetpoint",
            "chem_orp_setpoint": "orpSetpoint",
            "chem_feed_rate": "feedRate",
            "chem_max_daily_feed": "maxDailyFeed",
        }
        key_id = _key_map.get(key)
        if key_id is None:
            raise HomeAssistantError(f"Unsupported ChemSync config key: {key}")
        await self._async_write_role_config(
            role="chem_sync",
            key_id=key_id,
            value=value,
            description=f"ChemSync {key_id}",
            index=index,
        )

    async def async_chem_prime_pump(self, index: int = 0) -> None:
        """Trigger ChemSync prime pump action."""
        device_id = self._get_write_role_device_id(
            role="chem_sync", description="ChemSync prime pump", index=index
        )
        try:
            await self.api_client.async_set_device_config_value(
                device_id=device_id,
                key_id="primePump",
                value=1,
                password=self.password,
            )
            await self.async_request_refresh()
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self._raise_write_error("ChemSync prime pump", err)

    async def async_chem_boost(self, index: int = 0) -> None:
        """Trigger ChemSync boost action."""
        device_id = self._get_write_role_device_id(
            role="chem_sync", description="ChemSync boost", index=index
        )
        try:
            await self.api_client.async_set_device_config_value(
                device_id=device_id,
                key_id="boost",
                value=1,
                password=self.password,
            )
            await self.async_request_refresh()
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self._raise_write_error("ChemSync boost", err)

    async def async_chlor_clear_cell_life(self, index: int = 0) -> None:
        """Trigger ChlorSync clear cell life action."""
        device_id = self._get_write_role_device_id(
            role="chlorinator",
            description="ChlorSync clear cell life",
            index=index,
        )
        try:
            await self.api_client.async_set_device_config_value(
                device_id=device_id,
                key_id="clearCellLife",
                value=1,
                password=self.password,
            )
            await self.async_request_refresh()
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self._raise_write_error("ChlorSync clear cell life", err)

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

        except Exception as err:  # pylint: disable=broad-exception-caught
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

    def get_device_info(self, role: str, index: int = 0) -> DeviceInfo:
        """Return device information for a specific PoolSync device boundary."""
        parsed_data = (
            ensure_parsed_data(self)
            if self.parsed_data is None and isinstance(self.data, dict)
            else self.parsed_data
        )

        if role == "controller":
            return self._get_controller_device_info(parsed_data)

        return self._get_attached_device_info(role, parsed_data, index=index)

    def _get_controller_identifier(self) -> tuple[str, str]:
        """Return the stable device registry identifier for the controller."""
        return (DOMAIN, self.mac_address)

    def _get_device_identifier(
        self,
        role_key: str,
        node_addr: int | None = None,
        index: int = 0,
    ) -> tuple[str, str]:
        """Return a stable device registry identifier.

        Preserves backward compatibility for the first instance of each
        legacy role_key by not appending a suffix. Subsequent instances
        use nodeAddr when available, falling back to the numeric index.
        """
        domain = DOMAIN
        if role_key == "chlorinator" and index == 0:
            return (domain, f"{self.mac_address}_chlorinator")
        if role_key == "heat_pump" and index == 0:
            return (domain, f"{self.mac_address}_heat_pump")
        if node_addr is not None:
            return (domain, f"{self.mac_address}_{role_key}_{node_addr}")
        return (domain, f"{self.mac_address}_{role_key}_{index}")

    def _get_controller_name(self, parsed_data: PoolSyncParsedData | None) -> str:
        """Return the best available controller device name.

        Always normalizes to DEFAULT_NAME when the API reports any name.
        Returning arbitrary API names (e.g. "Pool PoolSync", "PoolSync™")
        causes entity ID drift when HA generates entity IDs from the device
        name. The device registry name can still be customized by the user
        via Home Assistant settings.
        """
        config_name_from_api: str | None = None

        if (
            parsed_data is not None
            and (system_config := parsed_data.system.config) is not None
        ):
            config_name_from_api = system_config.get("name")

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

        identifier = self._get_controller_identifier()
        device_registry = dr.async_get(self.hass)
        existing = device_registry.async_get_device(identifiers={identifier})

        info: dict[str, Any] = {
            "identifiers": {identifier},
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "configuration_url": f"http://{self._ip_address}",
        }
        if existing is None:
            info["name"] = self._get_controller_name(parsed_data)
        if sw_version is not None:
            info["sw_version"] = str(sw_version)
        if hw_version is not None:
            info["hw_version"] = str(hw_version)

        return DeviceInfo(**info)

    def _normalize_attached_name(self, name: str, role_key: str) -> str:
        """Normalize known vendor default attached-device names."""
        if role_key == "chlorinator" and _DEFAULT_CHLORINATOR_NAME_PATTERN.fullmatch(
            name.strip()
        ):
            return "ChlorSync"
        if role_key == "heat_pump" and _DEFAULT_HEATPUMP_NAME_PATTERN.fullmatch(
            name.strip()
        ):
            return "Heat Pump"
        return name

    def _dedup_device_name(
        self,
        base_name: str,
        role_key: str,
        index: int,
        all_names: list[str],
    ) -> str:
        """Return a unique friendly name, appending a suffix for duplicates.

        Using role_key for potential future type-specific dedup logic.
        """
        _ = role_key  # Reserved for future type-specific dedup
        if index == 0:
            return base_name
        count = sum(1 for name in all_names[: index + 1] if name == base_name)
        if count > 1:
            return f"{base_name} {count}"
        return base_name

    def _get_attached_device_info(
        self,
        role_key: str,
        parsed_data: PoolSyncParsedData | None,
        index: int = 0,
    ) -> DeviceInfo:
        """Build device info for an attached device role."""
        device_info = ROLE_KEY_REGISTRY.get(role_key)
        default_name = device_info.default_name if device_info else role_key
        default_model = device_info.default_model if device_info else role_key

        role_data = (
            get_role_data(parsed_data, role_key, index=index)
            if parsed_data is not None
            else None
        )
        node_attr = role_data.node_attr if role_data is not None else None
        system_info = role_data.system if role_data is not None else None
        node_addr = role_data.node_addr if role_data is not None else None

        device_name = default_name
        model_name = default_model
        sw_version = None
        hw_version = None

        # Collect all normalized names for this role for dedup
        all_raw_names: list[str] = []
        if parsed_data is not None:
            for dev in parsed_data.devices.get(role_key, []):
                raw = (
                    dev.node_attr.get("name")
                    if dev.node_attr and isinstance(dev.node_attr.get("name"), str)
                    else default_name
                )
                all_raw_names.append(self._normalize_attached_name(raw, role_key))  # type: ignore[arg-type]

        if (
            node_attr is not None
            and isinstance(node_attr.get("name"), str)
            and node_attr.get("name")
        ):
            device_name = self._normalize_attached_name(node_attr["name"], role_key)
            model_name = self._normalize_attached_name(node_attr["name"], role_key)

        # Deduplicate the friendly name
        device_name = self._dedup_device_name(
            device_name, role_key, index, all_raw_names
        )

        if system_info is not None:
            if isinstance(system_info.get("modelNum"), str) and system_info.get(
                "modelNum"
            ):
                model_name = system_info["modelNum"]

            if role_key == "heat_pump":
                sw_version = system_info.get("appFwVersion")
                hw_version = system_info.get("hwVersion")
            else:
                sw_version = system_info.get("fwVersion") or system_info.get(
                    "drvFwVersion"
                )
                hw_version = system_info.get("hwVersion") or system_info.get(
                    "drvHwVersion"
                )

        identifier = self._get_device_identifier(
            role_key, node_addr=node_addr, index=index
        )
        device_registry = dr.async_get(self.hass)
        existing = device_registry.async_get_device(identifiers={identifier})

        info: dict[str, Any] = {
            "identifiers": {identifier},
            "manufacturer": MANUFACTURER,
            "model": str(model_name) if model_name else default_model,
            "via_device": self._get_controller_identifier(),
        }
        if existing is None:
            info["name"] = device_name
        if sw_version is not None:
            info["sw_version"] = str(sw_version)
        if hw_version is not None:
            info["hw_version"] = str(hw_version)

        return DeviceInfo(**info)

    def get_equipment_device_info(self, equip: PoolSyncEquipmentData) -> DeviceInfo:
        """Build device info for an equipment entry."""
        identifier = (DOMAIN, f"{self.mac_address}_equip_{equip.slot_key}")
        device_registry = dr.async_get(self.hass)
        existing = device_registry.async_get_device(identifiers={identifier})
        return DeviceInfo(
            identifiers={identifier},
            name=equip.name if existing is None else None,
            manufacturer=MANUFACTURER,
            via_device=(DOMAIN, f"{self.mac_address}_heat_pump"),
        )

    def get_equipment_identifier(self, equip: PoolSyncEquipmentData) -> tuple[str, str]:
        """Return the stable device registry identifier for equipment."""
        return (DOMAIN, f"{self.mac_address}_equip_{equip.slot_key}")

    async def async_set_pump_rpm(self, value: int) -> None:
        """Set the circulation pump RPM via the heat pump device config."""
        if not self.password:
            raise HomeAssistantError("API password not available")

        parsed_data = self.get_parsed_data()
        hp_devices = parsed_data.devices.get("heat_pump", [])
        if not hp_devices or hp_devices[0].device_id is None:
            raise HomeAssistantError("Pump write target is not available")

        internal_value = value // PUMP_RPM_FACTOR
        try:
            await self.api_client.async_set_device_config_value(
                device_id=hp_devices[0].device_id,
                key_id=EQUIP_PUMP_RPM_WRITE_KEY,
                value=internal_value,
                password=self.password,
            )
            await self.async_request_refresh()
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self._raise_write_error("pump RPM", err)

    async def async_set_group_state(
        self, group_id: str, state: bool, index: int = 0
    ) -> None:
        """Turn a group on or off by setting its state in config[3]."""
        role_data = get_role_data(self.get_parsed_data(), "heat_pump", index=index)
        if role_data is None or role_data.device_id is None:
            raise HomeAssistantError("PoolSync heat pump target is not available")

        try:
            await self.api_client.async_set_device_config_value(
                device_id=role_data.device_id,
                key_id="group_state",
                value=1 if state else 0,
                password=self.password,
                json_data_override={
                    "groups": {
                        group_id: {"config": {str(GROUP_IDX_STATE): 1 if state else 0}}
                    }
                },
            )
            await self.async_request_refresh()
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self._raise_write_error(f"group {group_id} state", err)

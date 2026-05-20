"""DataUpdateCoordinator for the PoolSync Custom integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

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
    PoolSyncDeviceRole,
    PoolSyncParsedData,
    ensure_parsed_data,
    get_role_data,
    parse_poolsync_runtime_data,
)

_LOGGER = logging.getLogger(__name__)


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

    @property
    def password(self) -> str:
        """Return the stored PoolSync API password."""
        return self._password

    def get_parsed_data(self, *, refresh: bool = False) -> PoolSyncParsedData:
        """Return parsed runtime data, deriving it from raw data if needed."""
        return ensure_parsed_data(self, refresh=refresh)

    async def _async_write_role_config(
        self,
        *,
        role: PoolSyncDeviceRole,
        key_id: str,
        value: int,
        description: str,
    ) -> None:
        """Write a config value for a resolved device role and refresh state."""
        if not self.password:
            raise HomeAssistantError("API password not available to set value")

        parsed_data = self.get_parsed_data()
        role_data = get_role_data(parsed_data, role)
        if role_data.device_id is None or not role_data.is_present:
            raise HomeAssistantError(f"PoolSync {description} target is not available")

        try:
            await self.api_client.async_set_device_config_value(
                device_id=role_data.device_id,
                key_id=key_id,
                value=value,
                password=self.password,
            )
            await self.async_request_refresh()
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Failed to set {description}: {err}") from err

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
        await self._async_write_role_config(
            role="heat_pump",
            key_id="setpoint",
            value=value,
            description="heat pump setpoint",
        )

    async def async_set_heat_pump_mode(self, value: int) -> None:
        """Set the heat pump mode."""
        await self._async_write_role_config(
            role="heat_pump",
            key_id="mode",
            value=value,
            description="heat pump mode",
        )

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
            self._log_recovered_if_needed()
            return data

        except PoolSyncApiAuthError as err:
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
            self._log_unavailable_once(str(err))
            _LOGGER.warning(
                "Coordinator %s: Communication error fetching data: %s. Will retry.",
                self.name,
                err,
            )
            raise UpdateFailed(
                f"Error communicating with PoolSync device {self.name}: {err}"
            ) from err

        except PoolSyncApiError as err:
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
            self._log_unavailable_once(type(err).__name__)
            _LOGGER.exception(
                "Coordinator %s: Unexpected error fetching data: %s", self.name, err
            )
            raise UpdateFailed(f"Unexpected error updating {self.name}: {err}") from err

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for entities to use."""
        device_name = DEFAULT_NAME
        model_name = MODEL
        sw_version = None
        hw_version = None
        config_name_from_api: str | None = None
        parsed_data = (
            ensure_parsed_data(self)
            if self.parsed_data is None and isinstance(self.data, dict)
            else self.parsed_data
        )

        if parsed_data is not None:
            if (system_config := parsed_data.system.config) is not None:
                config_name_from_api = system_config.get("name")

            if (system_info := parsed_data.system.system) is not None:
                sw_version = system_info.get("fwVersion")
                hw_version = system_info.get("hwVersion")

            if (chlorinator_node_attr := parsed_data.chlorinator.node_attr) is not None:
                api_model_name = chlorinator_node_attr.get("name")
                if api_model_name:
                    model_name = api_model_name

        if config_name_from_api and config_name_from_api != "PoolSync®":
            device_name = config_name_from_api
        else:
            device_name = (
                f"{DEFAULT_NAME} {self.mac_address[-6:]}"
                if self.mac_address and len(self.mac_address) >= 6
                else DEFAULT_NAME
            )

        return DeviceInfo(
            identifiers={(DOMAIN, self.mac_address)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=str(model_name) if model_name else MODEL,
            sw_version=str(sw_version) if sw_version is not None else None,
            hw_version=str(hw_version) if hw_version is not None else None,
            configuration_url=f"http://{self._ip_address}",
        )

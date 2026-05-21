"""Config flow for PoolSync Custom integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import callback

# Use the provided API client and constants
from .api import (
    PoolSyncApiClient,
    PoolSyncApiCommunicationError,
    PoolSyncApiError,
    async_create_poolsync_session,
)
from .const import (
    API_RESPONSE_MAC_ADDRESS,
    API_RESPONSE_PASSWORD,
    API_RESPONSE_TIME_REMAINING,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_SCAN_INTERVAL,
    PUSHLINK_CHECK_INTERVAL_S,
    PUSHLINK_TIMEOUT_S,
)
from .const import (
    CONF_IP_ADDRESS as POOLSYNC_CONF_IP_ADDRESS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(POOLSYNC_CONF_IP_ADDRESS): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PoolSync Custom."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._ip_address: str | None = None
        self._mac_address: str | None = None
        self._password: str | None = None
        self._api_client: PoolSyncApiClient | None = None
        self._link_task: asyncio.Task[None] | None = None
        self._link_error: str | None = None

    async def _async_create_client(self, ip_address: str) -> PoolSyncApiClient:
        """Create an API client instance."""
        session = async_create_poolsync_session(self.hass)
        return PoolSyncApiClient(ip_address, session)

    async def _async_begin_pushlink(self) -> str | None:
        """Start a new push-link attempt for the current device."""
        assert self._ip_address is not None

        if self._task_still_running(self._link_task):
            assert self._link_task is not None
            _LOGGER.info(
                "Restarting PoolSync onboarding for %s while a prior push-link task is still running",
                self._ip_address,
            )
            self._link_task.cancel()

        self._password = None
        self._mac_address = None
        self._link_task = None
        self._link_error = None

        if self._api_client is None:
            self._api_client = await self._async_create_client(self._ip_address)

        _LOGGER.info("Starting PoolSync push-link onboarding for %s", self._ip_address)

        try:
            await self._api_client.start_pushlink()
        except PoolSyncApiCommunicationError as err:
            _LOGGER.warning(
                "Could not start PoolSync push-link onboarding for %s: %s",
                self._ip_address,
                err,
            )
            return "cannot_connect"
        except PoolSyncApiError as err:
            _LOGGER.warning(
                "PoolSync push-link onboarding start failed for %s: %s",
                self._ip_address,
                err,
            )
            return "api_error"

        _LOGGER.info("PoolSync push-link onboarding started for %s", self._ip_address)

        return None

    @staticmethod
    def _validate_ip_address(ip_address: str) -> bool:
        """Validate an IPv4 or IPv6 address."""
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            return False

        return True

    @staticmethod
    def _task_still_running(task: asyncio.Task[None] | None) -> bool:
        """Return if the current link task is active."""
        return task is not None and not task.done()

    async def _async_finish_link(self) -> ConfigFlowResult:
        """Create the entry after a successful push-link."""
        assert self._ip_address is not None
        assert self._password is not None
        assert self._mac_address is not None

        await self.async_set_unique_id(self._mac_address)

        if self.source == config_entries.SOURCE_REAUTH:
            _LOGGER.info(
                "Completing PoolSync reauthentication for %s with device %s",
                self._ip_address,
                self._mac_address,
            )
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                unique_id=self._mac_address,
                data_updates={
                    CONF_IP_ADDRESS: self._ip_address,
                    CONF_PASSWORD: self._password,
                    API_RESPONSE_MAC_ADDRESS: self._mac_address,
                },
            )

        self._abort_if_unique_id_configured()
        _LOGGER.info(
            "Completing PoolSync onboarding for %s with device %s",
            self._ip_address,
            self._mac_address,
        )

        return self.async_create_entry(
            title=f"{DEFAULT_NAME} ({self._mac_address[-6:]})",
            data={
                CONF_IP_ADDRESS: self._ip_address,
                CONF_PASSWORD: self._password,
                API_RESPONSE_MAC_ADDRESS: self._mac_address,
            },
        )

    async def _async_handle_completed_link_task(self) -> ConfigFlowResult:
        """Handle the result of the background link task."""
        assert self._link_task is not None

        try:
            await self._link_task
        except asyncio.CancelledError:
            _LOGGER.warning(
                "PoolSync push-link polling task was cancelled for %s",
                self._ip_address,
            )
            self._link_error = "unknown"
        finally:
            self._link_task = None

        if self._password and self._mac_address:
            _LOGGER.info(
                "PoolSync onboarding collected credentials for %s and will finish setup",
                self._ip_address,
            )
            return self.async_show_progress_done(next_step_id="finish_link")

        _LOGGER.warning(
            "PoolSync onboarding failed for %s with reason %s",
            self._ip_address,
            self._link_error or "unknown",
        )
        return self.async_show_progress_done(next_step_id="link_failed")

    def is_matching(self, other_flow: config_entries.ConfigFlow) -> bool:
        """Return if this flow matches another discovery flow."""
        return False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step where the user provides the IP address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ip_address = user_input[POOLSYNC_CONF_IP_ADDRESS].strip()
            self._ip_address = ip_address
            if not self._validate_ip_address(ip_address):
                _LOGGER.warning(
                    "PoolSync onboarding rejected invalid IP address input: %s",
                    ip_address,
                )
                errors["base"] = "invalid_ip"
            else:
                if error := await self._async_begin_pushlink():
                    errors["base"] = error
                else:
                    errors = {}
                    return await self.async_step_link()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait for the PoolSync device to return its password."""
        del user_input

        if not self._ip_address or not self._api_client:
            _LOGGER.error(
                "PoolSync onboarding link step reached without initialized client state"
            )
            return self.async_abort(reason="internal_error")

        if not self._link_task:
            self._link_error = None
            _LOGGER.info(
                "Polling PoolSync push-link status for %s for up to %s seconds",
                self._ip_address,
                PUSHLINK_TIMEOUT_S,
            )
            self._link_task = self.hass.async_create_task(
                self._async_poll_for_password()
            )

        if not self._link_task.done():
            return self.async_show_progress(
                step_id="link",
                progress_action="link",
                progress_task=self._link_task,
                description_placeholders={
                    "ip_address": self._ip_address,
                    "time_remaining": str(PUSHLINK_TIMEOUT_S),
                },
            )

        return await self._async_handle_completed_link_task()

    async def async_step_link_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a retry screen after a failed push-link attempt."""
        if user_input is not None:
            _LOGGER.info(
                "Retrying PoolSync onboarding for %s after failure %s",
                self._ip_address,
                self._link_error or "unknown",
            )
            self._link_error = await self._async_begin_pushlink()
            if self._link_error is None:
                return await self.async_step_link()

            return self.async_show_form(
                step_id="link_failed",
                errors={"base": self._link_error},
                description_placeholders={
                    "ip_address": self._ip_address or "",
                    "time_remaining": str(PUSHLINK_TIMEOUT_S),
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="link_failed",
            errors={"base": self._link_error} if self._link_error else {},
            description_placeholders={
                "ip_address": self._ip_address or "",
                "time_remaining": str(PUSHLINK_TIMEOUT_S),
            },
        )

    async def async_step_finish_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the config entry after a successful push-link."""
        del user_input
        return await self._async_finish_link()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth on authentication failure."""
        self._ip_address = str(entry_data[CONF_IP_ADDRESS]).strip()
        _LOGGER.info("Starting PoolSync reauthentication for %s", self._ip_address)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a new local push-link for reauthentication."""
        reauth_entry = self._get_reauth_entry()
        self._ip_address = str(reauth_entry.data[CONF_IP_ADDRESS]).strip()

        if user_input is not None:
            _LOGGER.info(
                "Confirming PoolSync reauthentication for %s",
                self._ip_address,
            )
            self._link_error = await self._async_begin_pushlink()
            if self._link_error is None:
                return await self.async_step_link()

            self._set_confirm_only()
            return self.async_show_form(
                step_id="reauth_confirm",
                errors={"base": self._link_error},
                description_placeholders={"ip_address": self._ip_address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"ip_address": self._ip_address},
        )

    async def _async_poll_for_password(self) -> None:
        """Poll the device for pushlink status until password is received or timeout."""
        if not self._api_client or not self._ip_address:
            _LOGGER.error(
                "PoolSync onboarding polling started without initialized client state"
            )
            self._link_error = "internal_error_polling_setup"
            return

        time_elapsed = 0
        error_to_show: str | None = None

        while time_elapsed < PUSHLINK_TIMEOUT_S:
            try:
                status_response = await self._api_client.get_pushlink_status()

                if API_RESPONSE_PASSWORD in status_response and status_response.get(
                    API_RESPONSE_PASSWORD
                ):
                    self._password = status_response[API_RESPONSE_PASSWORD]
                    self._mac_address = status_response.get(API_RESPONSE_MAC_ADDRESS)
                    if not self._mac_address:
                        _LOGGER.warning(
                            "PoolSync onboarding received a password for %s without a MAC address",
                            self._ip_address,
                        )
                        error_to_show = "link_failed"
                        break

                    _LOGGER.info(
                        "PoolSync onboarding received credentials for %s and linked device %s",
                        self._ip_address,
                        self._mac_address,
                    )
                    return

                time_remaining = status_response.get(API_RESPONSE_TIME_REMAINING)
                time_remaining_for_ui = (
                    int(time_remaining)
                    if time_remaining is not None
                    else max(
                        0,
                        PUSHLINK_TIMEOUT_S - time_elapsed - PUSHLINK_CHECK_INTERVAL_S,
                    )
                )

                _LOGGER.debug(
                    "PoolSync onboarding still waiting for %s; about %s seconds remain",
                    self._ip_address,
                    time_remaining_for_ui,
                )

                if time_remaining_for_ui <= 0 and not self._password:
                    _LOGGER.warning(
                        "PoolSync onboarding timed out for %s while waiting for the device password",
                        self._ip_address,
                    )
                    error_to_show = "link_timeout"
                    break

            except PoolSyncApiCommunicationError as err:
                _LOGGER.warning(
                    "Communication error while polling PoolSync push-link status for %s: %s",
                    self._ip_address,
                    err,
                )
            except PoolSyncApiError as e:
                _LOGGER.warning(
                    "API error while polling PoolSync push-link status for %s: %s",
                    self._ip_address,
                    e,
                )
                error_to_show = "link_failed"
                break

            await asyncio.sleep(PUSHLINK_CHECK_INTERVAL_S)
            time_elapsed += PUSHLINK_CHECK_INTERVAL_S

        if not self._password and not error_to_show:
            _LOGGER.warning(
                "PoolSync onboarding timed out for %s before credentials were returned",
                self._ip_address,
            )
            error_to_show = "link_timeout"

        self._link_error = error_to_show

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return PoolSyncOptionsFlowHandler(config_entry)


class PoolSyncOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for PoolSync Custom."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.options = dict(config_entry.options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            new_scan_interval = user_input.get(
                OPTION_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            )
            if not isinstance(new_scan_interval, int) or new_scan_interval < 10:
                errors["base"] = "invalid_scan_interval"
            else:
                self.options[OPTION_SCAN_INTERVAL] = new_scan_interval
                return self.async_create_entry(title="", data=self.options)

        current_scan_interval = self.options.get(
            OPTION_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPTION_SCAN_INTERVAL,
                        default=current_scan_interval,
                    ): vol.Coerce(int),
                }
            ),
            errors=errors,
            description_placeholders={"current_interval": str(current_scan_interval)},
        )

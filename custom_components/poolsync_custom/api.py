"""API client for AutoPilot PoolSync devices."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
from aiohttp import DummyCookieJar
from aiohttp.client_exceptions import ClientConnectorError, ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    API_PATH_ALL_DATA,
    API_PATH_PUSHLINK_START,
    API_PATH_PUSHLINK_STATUS,
    HEADER_AUTHORIZATION,
    HEADER_USER,
    HTTP_TIMEOUT,
    USER_HEADER_VALUE,
)

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return request headers with any authorization values redacted."""
    return {
        key: (
            value[:10] + "..."
            if key == HEADER_AUTHORIZATION and value and len(value) > 10
            else value
        )
        for key, value in headers.items()
    }


def async_create_poolsync_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """Create a dedicated no-cookie client session for PoolSync traffic."""
    return async_create_clientsession(hass, cookie_jar=DummyCookieJar())


class PoolSyncApiError(Exception):
    """Generic PoolSync API exception."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PoolSyncApiAuthError(PoolSyncApiError):
    """PoolSync API authentication error (e.g., invalid password)."""


class PoolSyncApiCommunicationError(PoolSyncApiError):
    """PoolSync API communication error (e.g., network issue, device unavailable)."""


class PoolSyncApiClient:
    """API Client for PoolSync device."""

    def __init__(self, ip_address: str, session: aiohttp.ClientSession) -> None:
        """
        Initialize the PoolSync API client.

        Args:
            ip_address: The IP address of the PoolSync device.
            session: An aiohttp client session.
        """
        self._ip_address = ip_address.strip()  # Ensure no leading/trailing spaces
        self._session = session
        self._base_url = f"http://{self._ip_address}"
        _LOGGER.debug("PoolSyncApiClient initialized for IP: %s", self._ip_address)

    @property
    def ip_address(self) -> str:
        """Return the configured PoolSync device IP address."""
        return self._ip_address

    async def async_set_device_config_value(
        self,
        device_id: str,
        key_id: str,
        value: int,
        password: str,
        *,
        json_data_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch a config value for a specific PoolSync device."""
        if not password:
            raise PoolSyncApiAuthError(
                "Password is required to change PoolSync settings."
            )

        json_data = (
            json_data_override
            if json_data_override is not None
            else {"config": {key_id: int(value)}}
        )

        return await self._request(
            "PATCH",
            "/api/poolsync",
            password=password,
            params={"cmd": "devices", "device": device_id},
            json_data=json_data,
            allow_non_json_success=True,
        )

    async def _request(
        self,
        method: str,
        path: str,
        password: str | None = None,
        *,
        params: Mapping[str, str] | None = None,
        json_data: Any | None = None,
        allow_non_json_success: bool = False,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to the PoolSync device.

        Args:
            method: HTTP method (GET, PUT).
            path: API endpoint path.
            password: Optional password for authorization.

        Returns:
            A dictionary containing the JSON response from the API.

        Raises:
            PoolSyncApiCommunicationError: If there's a network or device communication issue.
            PoolSyncApiAuthError: If the server returns a 401 or 403 error.
            PoolSyncApiError: For other HTTP errors or invalid JSON response.
        """
        url = f"{self._base_url}{path}"
        headers = {
            HEADER_USER: USER_HEADER_VALUE,
        }
        if password:
            headers[HEADER_AUTHORIZATION] = password
        if json_data is not None:
            headers["Content-Type"] = "application/json"
            headers["Accept-Encoding"] = "gzip, deflate"

        _LOGGER.debug(
            "Requesting URL: %s, Method: %s, Params: %s, Headers: %s",
            url,
            method,
            dict(params or {}),
            _redact_headers(headers),
        )

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                headers=headers,
                json=json_data,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response_text = await response.text()
                _LOGGER.debug(
                    "Response from %s: Status: %s, Content-Type: %s, Body snippet: %s",
                    url,
                    response.status,
                    response.headers.get("Content-Type"),
                    response_text[:200],
                )

                if response.status == 200:
                    try:
                        json_response = await response.json(content_type=None)
                        _LOGGER.debug(
                            "Successfully parsed JSON response: %s", json_response
                        )
                        return json_response
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        if allow_non_json_success:
                            _LOGGER.debug(
                                "Treating non-JSON %s response as success for %s. Error: %s. Body: %s",
                                method,
                                url,
                                err,
                                response_text[:200],
                            )
                            return {}

                        _LOGGER.error(
                            "Failed to decode JSON response from %s despite 200 OK. Error: %s. Body: %s",
                            url,
                            err,
                            response_text,
                        )
                        raise PoolSyncApiError(
                            f"Invalid JSON response: {err}",
                            status_code=response.status,
                            body=response_text,
                        ) from err
                if response.status in (401, 403):
                    _LOGGER.error(
                        "Authentication error from %s: %s. Body: %s",
                        url,
                        response.status,
                        response_text,
                    )
                    raise PoolSyncApiAuthError(
                        f"Authentication failed: {response.status}",
                        status_code=response.status,
                        body=response_text,
                    )

                _LOGGER.error(
                    "HTTP error from %s: %s - %s. Body: %s",
                    url,
                    response.status,
                    response.reason,
                    response_text,
                )
                raise PoolSyncApiError(
                    f"HTTP error {response.status}: {response.reason}",
                    status_code=response.status,
                    body=response_text,
                )
        except ClientConnectorError as err:
            _LOGGER.warning(
                "Network connection error for %s: %s", self._ip_address, err
            )
            raise PoolSyncApiCommunicationError(
                f"Cannot connect to PoolSync device at {self._ip_address}: {err}"
            ) from err
        except TimeoutError as err:
            _LOGGER.error(
                "Request timed out for %s accessing %s", self._ip_address, url
            )
            raise PoolSyncApiCommunicationError(
                f"Request to {url} timed out after {HTTP_TIMEOUT}s"
            ) from err
        except ClientError as err:
            # Catches remaining aiohttp ClientError subclasses not covered above
            # (e.g. ServerDisconnectedError, ClientPayloadError).
            _LOGGER.warning(
                "HTTP client communication error for %s accessing %s: %s",
                self._ip_address,
                url,
                err,
            )
            raise PoolSyncApiCommunicationError(
                f"Communication error talking to PoolSync device at {self._ip_address}: {err}"
            ) from err
        except PoolSyncApiError:
            raise
        except Exception as err:
            _LOGGER.exception(
                "An unexpected error occurred during API request to %s for URL %s: %s",
                self._ip_address,
                url,
                err,
            )
            raise PoolSyncApiError(f"An unexpected error occurred: {err}") from err

    async def start_pushlink(self) -> dict[str, Any]:
        """
        Initiate the push-link process on the PoolSync device.
        Corresponds to: HTTP PUT "http://$localIP/api/poolsync?cmd=pushLink&start"
        """
        _LOGGER.info("Attempting to start push-link process for %s.", self._ip_address)
        response = await self._request("PUT", API_PATH_PUSHLINK_START)
        _LOGGER.debug("Push-link start response for %s: %s", self._ip_address, response)
        return (
            response  # Expecting JSON response, e.g., {"timeRemaining":120} or similar
        )

    async def get_pushlink_status(self) -> dict[str, Any]:
        """
        Query the status of the push-link process.
        Corresponds to: HTTP GET "/api/poolsync?cmd=pushLink&status"
        """
        _LOGGER.debug("Querying push-link status for %s.", self._ip_address)
        response = await self._request("GET", API_PATH_PUSHLINK_STATUS)
        _LOGGER.debug(
            "Received push-link status for %s with keys: %s",
            self._ip_address,
            sorted(response),
        )
        # Expected keys: "timeRemaining" or "password" and "macAddress"
        return response

    async def get_all_data(self, password: str) -> dict[str, Any]:
        """
        Fetch all data from the PoolSync device using the obtained password.
        Corresponds to: HTTP GET "/api/poolsync?cmd=poolSync&all" with auth header.
        """
        if not password:
            _LOGGER.error(
                "Attempted to get all data for %s without a password.", self._ip_address
            )
            # This should ideally be caught before calling, but good to have a check.
            raise PoolSyncApiAuthError("Password is required to fetch all data.")

        _LOGGER.debug("Fetching all data for %s with password.", self._ip_address)
        response = await self._request("GET", API_PATH_ALL_DATA, password=password)

        # Basic validation of the expected top-level key
        if "poolSync" not in response or not isinstance(response.get("poolSync"), dict):
            _LOGGER.error(
                "Main 'poolSync' key missing or not a dictionary in data response for %s: %s",
                self._ip_address,
                response,
            )
            raise PoolSyncApiError(
                "Received malformed data from PoolSync device: 'poolSync' key missing or invalid."
            )
        return response

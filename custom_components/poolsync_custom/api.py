"""API client for AutoPilot PoolSync devices."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiohttp.client_exceptions import ClientConnectorError

# Assuming const.py is in the same directory
from .const import (
    API_PATH_ALL_DATA,
    API_PATH_PUSHLINK_START,
    API_PATH_PUSHLINK_STATUS,
    HEADER_AUTHORIZATION,
    HEADER_USER,
    HTTP_TIMEOUT,
    USER_HEADER_VALUE,
    # API_RESPONSE_PASSWORD, # Not directly used in this file for logic, but for context
    # API_RESPONSE_TIME_REMAINING, # Not directly used in this file for logic
    # API_RESPONSE_MAC_ADDRESS, # Not directly used in this file for logic
)

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)


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
    ) -> dict[str, Any]:
        """Patch a config value for a specific PoolSync device."""
        if not password:
            raise PoolSyncApiAuthError(
                "Password is required to change PoolSync settings."
            )

        path = "/api/poolsync"
        url = f"{self._base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            HEADER_USER: USER_HEADER_VALUE,
            "Accept-Encoding": "gzip, deflate",
            HEADER_AUTHORIZATION: password,
        }

        params = {
            "cmd": "devices",
            "device": device_id,
        }

        json_data = {
            "config": {
                key_id: int(value),
            }
        }

        try:
            async with self._session.patch(
                url,
                params=params,
                headers=headers,
                json=json_data,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response_text = await response.text()
                _LOGGER.debug(
                    "PATCH response from %s: Status: %s, Content-Type: %s, Body snippet: %s",
                    url,
                    response.status,
                    response.headers.get("Content-Type"),
                    response_text[:200],
                )

                if response.status == 200:
                    try:
                        return await response.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        if not response_text.strip():
                            return {}
                        raise PoolSyncApiError(
                            f"Invalid JSON response: {err}",
                            status_code=response.status,
                            body=response_text,
                        ) from err

                if response.status in (401, 403):
                    raise PoolSyncApiAuthError(
                        f"Authentication failed: {response.status}",
                        status_code=response.status,
                        body=response_text,
                    )

                raise PoolSyncApiError(
                    f"HTTP error {response.status}: {response.reason}",
                    status_code=response.status,
                    body=response_text,
                )

        except ClientConnectorError as err:
            _LOGGER.error("Network connection error for %s: %s", self._ip_address, err)
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

    async def _request(
        self,
        method: str,
        path: str,
        password: str | None = None,
        # data: Optional[Dict[str, Any]] = None, # PUT request for startLink doesn't seem to have a body
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
            # "User-Agent": "HomeAssistant-PoolSyncCustom/0.1.0", # Match version in manifest
            # "Accept": "application/json, text/plain, */*", # Broader accept based on some device behaviors
            HEADER_USER: USER_HEADER_VALUE,
            # "Connection": "keep-alive", # As per curl example
            # "Accept-Encoding": "gzip, deflate, br", # As per curl example
            # Host header is automatically set by aiohttp
        }
        if password:
            headers[HEADER_AUTHORIZATION] = password

        _LOGGER.debug(
            "Requesting URL: %s, Method: %s, Headers: %s",
            url,
            method,
            # Avoid logging full password if present
            {
                k: (
                    v[:10] + "..."
                    if k == HEADER_AUTHORIZATION and v and len(v) > 10
                    else v
                )
                for k, v in headers.items()
            },
        )

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,  # No json=data for these GET/PUTs
            ) as response:
                response_text = (
                    await response.text()
                )  # Read text first for logging/errors
                _LOGGER.debug(
                    "Response from %s: Status: %s, Content-Type: %s, Body snippet: %s",
                    url,
                    response.status,
                    response.headers.get("Content-Type"),
                    response_text[:200],  # Log a snippet of the response body
                )

                if response.status == 200:
                    # PoolSync devices sometimes return non-standard JSON content types like 'text/plain'
                    # but the body is still JSON. We'll try to parse JSON regardless of content-type if status is 200.
                    try:
                        json_response = await response.json(
                            content_type=None
                        )  # Try to parse JSON regardless of reported type
                        _LOGGER.debug(
                            "Successfully parsed JSON response: %s", json_response
                        )
                        return json_response
                    except (
                        ValueError,
                        aiohttp.ContentTypeError,
                    ) as e:  # Catches json.JSONDecodeError and content type issues
                        _LOGGER.error(
                            "Failed to decode JSON response from %s despite 200 OK. Error: %s. Body: %s",
                            url,
                            e,
                            response_text,
                        )
                        raise PoolSyncApiError(
                            f"Invalid JSON response: {e}",
                            status_code=response.status,
                            body=response_text,
                        ) from e
                elif response.status in (401, 403):
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
                else:
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
        except ClientConnectorError as e:
            _LOGGER.error("Network connection error for %s: %s", self._ip_address, e)
            raise PoolSyncApiCommunicationError(
                f"Cannot connect to PoolSync device at {self._ip_address}: {e}"
            ) from e
        except TimeoutError as e:  # This is for the overall request timeout
            _LOGGER.error(
                "Request timed out for %s accessing %s", self._ip_address, url
            )
            raise PoolSyncApiCommunicationError(
                f"Request to {url} timed out after {HTTP_TIMEOUT}s"
            ) from e
        # ClientResponseError is a base for many client-side errors, already caught by status checks.
        # Catching broader Exception for any other unexpected aiohttp or network issues.
        except Exception as e:
            _LOGGER.exception(
                "An unexpected error occurred during API request to %s for URL %s: %s",
                self._ip_address,
                url,
                e,
            )
            raise PoolSyncApiError(f"An unexpected error occurred: {e}") from e

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
        _LOGGER.info(response)
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

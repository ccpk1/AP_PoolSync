"""Tests for the PoolSync API client."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp.client_exceptions import ServerDisconnectedError

from custom_components.poolsync_custom.api import (
    PoolSyncApiAuthError,
    PoolSyncApiClient,
    PoolSyncApiCommunicationError,
    PoolSyncApiError,
)
from custom_components.poolsync_custom.const import CONF_PASSWORD, HEADER_AUTHORIZATION

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"


async def test_get_pushlink_status_does_not_log_password(caplog) -> None:
    """Test push-link status does not log the returned password."""
    client = PoolSyncApiClient(TEST_IP_ADDRESS, Mock())

    with (
        patch.object(
            client,
            "_request",
            new=AsyncMock(return_value={CONF_PASSWORD: TEST_PASSWORD}),
        ),
        caplog.at_level(logging.INFO, logger="custom_components.poolsync_custom.api"),
    ):
        response = await client.get_pushlink_status()

    assert response == {CONF_PASSWORD: TEST_PASSWORD}
    assert all(
        TEST_PASSWORD not in record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.INFO
    )


async def test_set_device_config_value_accepts_non_json_success_body() -> None:
    """Test config PATCH accepts a successful non-JSON response body."""
    session = Mock()
    response = Mock()
    response.status = 200
    response.headers = {"Content-Type": "text/plain"}
    response.text = AsyncMock(return_value="OK")
    response.json = AsyncMock(
        side_effect=ValueError("unexpected character: line 1 column 1 (char 0)")
    )

    request_context = AsyncMock()
    request_context.__aenter__.return_value = response
    request_context.__aexit__.return_value = False
    session.request.return_value = request_context

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    result = await client.async_set_device_config_value(
        device_id="7",
        key_id="setpoint",
        value=79,
        password=TEST_PASSWORD,
    )

    assert result == {}
    session.request.assert_called_once()


async def test_set_device_config_value_preserves_auth_failure_details() -> None:
    """Test config PATCH auth failures preserve response details."""
    session = Mock()
    response = Mock()
    response.status = 403
    response.reason = "Forbidden"
    response.headers = {"Content-Type": "text/plain"}
    response.text = AsyncMock(return_value="bad password")

    request_context = AsyncMock()
    request_context.__aenter__.return_value = response
    request_context.__aexit__.return_value = False
    session.request.return_value = request_context

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    with pytest.raises(PoolSyncApiAuthError, match="Authentication failed: 403") as err:
        await client.async_set_device_config_value(
            device_id="7",
            key_id="setpoint",
            value=79,
            password=TEST_PASSWORD,
        )

    assert err.value.status_code == 403
    assert err.value.body == "bad password"
    session.request.assert_called_once()


async def test_request_raises_timeout_as_communication_error() -> None:
    """Test request timeouts are surfaced as communication errors."""
    session = Mock()
    session.request.side_effect = TimeoutError

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    with pytest.raises(PoolSyncApiCommunicationError, match="timed out") as err:
        await client._request("GET", "/api/poolsync?cmd=test")

    assert f"http://{TEST_IP_ADDRESS}/api/poolsync?cmd=test" in str(err.value)


async def test_request_raises_client_disconnect_as_communication_error() -> None:
    """Test aiohttp disconnects are surfaced as communication errors."""
    session = Mock()
    session.request.side_effect = ServerDisconnectedError

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    with pytest.raises(PoolSyncApiCommunicationError, match="Communication error"):
        await client._request("GET", "/api/poolsync?cmd=test")


async def test_request_raises_non_auth_http_error_with_status_and_body() -> None:
    """Test non-auth HTTP failures are preserved as API errors."""
    session = Mock()
    response = Mock()
    response.status = 500
    response.reason = "Internal Server Error"
    response.headers = {"Content-Type": "text/plain"}
    response.text = AsyncMock(return_value="upstream exploded")

    request_context = AsyncMock()
    request_context.__aenter__.return_value = response
    request_context.__aexit__.return_value = False
    session.request.return_value = request_context

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    with pytest.raises(PoolSyncApiError, match="HTTP error 500") as err:
        await client._request("GET", "/api/poolsync?cmd=test")

    assert err.value.status_code == 500
    assert err.value.body == "upstream exploded"


async def test_request_returns_json_payload_on_success() -> None:
    """Test successful requests return parsed JSON payloads."""
    session = Mock()
    response = Mock()
    response.status = 200
    response.headers = {"Content-Type": "application/json"}
    response.text = AsyncMock(return_value='{"poolSync": {}}')
    response.json = AsyncMock(return_value={"poolSync": {}})

    request_context = AsyncMock()
    request_context.__aenter__.return_value = response
    request_context.__aexit__.return_value = False
    session.request.return_value = request_context

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    result = await client._request(
        "GET", "/api/poolsync?cmd=test", password=TEST_PASSWORD
    )

    assert result == {"poolSync": {}}
    _, kwargs = session.request.call_args
    assert kwargs["headers"][HEADER_AUTHORIZATION] == TEST_PASSWORD


async def test_request_raises_invalid_json_when_success_body_is_not_json() -> None:
    """Test a 200 response with invalid JSON raises a typed API error."""
    session = Mock()
    response = Mock()
    response.status = 200
    response.headers = {"Content-Type": "text/plain"}
    response.text = AsyncMock(return_value="not-json")
    response.json = AsyncMock(side_effect=ValueError("bad json"))

    request_context = AsyncMock()
    request_context.__aenter__.return_value = response
    request_context.__aexit__.return_value = False
    session.request.return_value = request_context

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    with pytest.raises(PoolSyncApiError, match="Invalid JSON response") as err:
        await client._request("GET", "/api/poolsync?cmd=test")

    assert err.value.body == "not-json"


async def test_start_pushlink_delegates_to_request() -> None:
    """Test push-link start delegates to the shared request path."""
    client = PoolSyncApiClient(TEST_IP_ADDRESS, Mock())

    with patch.object(
        client,
        "_request",
        new=AsyncMock(return_value={"timeRemaining": 120}),
    ) as mock_request:
        result = await client.start_pushlink()

    assert result == {"timeRemaining": 120}
    mock_request.assert_awaited_once_with("PUT", "/api/poolsync?cmd=pushLink&start")


async def test_get_all_data_requires_password() -> None:
    """Test all-data fetch rejects empty passwords."""
    client = PoolSyncApiClient(TEST_IP_ADDRESS, Mock())

    with pytest.raises(PoolSyncApiAuthError, match="Password is required"):
        await client.get_all_data("")


async def test_get_all_data_rejects_malformed_payload() -> None:
    """Test all-data fetch rejects payloads missing the poolSync object."""
    client = PoolSyncApiClient(TEST_IP_ADDRESS, Mock())

    with patch.object(
        client,
        "_request",
        new=AsyncMock(return_value={"devices": {}}),
    ):
        with pytest.raises(PoolSyncApiError, match="Received malformed data"):
            await client.get_all_data(TEST_PASSWORD)

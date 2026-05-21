"""Tests for the PoolSync API client."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.poolsync_custom.api import (
    PoolSyncApiClient,
    PoolSyncApiCommunicationError,
    PoolSyncApiError,
)
from custom_components.poolsync_custom.const import CONF_PASSWORD

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
    session.patch.return_value = request_context

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    result = await client.async_set_device_config_value(
        device_id="7",
        key_id="setpoint",
        value=79,
        password=TEST_PASSWORD,
    )

    assert result == {}


async def test_request_raises_timeout_as_communication_error() -> None:
    """Test request timeouts are surfaced as communication errors."""
    session = Mock()
    session.request.side_effect = TimeoutError

    client = PoolSyncApiClient(TEST_IP_ADDRESS, session)

    with pytest.raises(PoolSyncApiCommunicationError, match="timed out") as err:
        await client._request("GET", "/api/poolsync?cmd=test")

    assert f"http://{TEST_IP_ADDRESS}/api/poolsync?cmd=test" in str(err.value)


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

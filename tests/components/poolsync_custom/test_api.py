"""Tests for the PoolSync API client."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock, patch

from custom_components.poolsync_custom.api import PoolSyncApiClient
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

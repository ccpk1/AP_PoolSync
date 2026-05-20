"""Tests for the PoolSync config flow."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolsync_custom.api import (
    PoolSyncApiCommunicationError,
    PoolSyncApiError,
)
from custom_components.poolsync_custom.const import (
    API_RESPONSE_MAC_ADDRESS,
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_SCAN_INTERVAL,
)

TEST_IP_ADDRESS = "192.168.50.70"
TEST_PASSWORD = "test-password"
TEST_MAC_ADDRESS = "AABBCCDDEEFF"


@pytest.fixture
def mock_setup_entry():
    """Prevent config-entry setup from reaching the real runtime code."""
    with patch(
        "custom_components.poolsync_custom.async_setup_entry",
        new=AsyncMock(return_value=True),
    ) as mock_setup:
        yield mock_setup


async def _async_return(value):
    """Yield control once before returning a mocked async value."""
    await asyncio.sleep(0)
    return value


async def _async_raise(exception: Exception):
    """Yield control once before raising a mocked async exception."""
    await asyncio.sleep(0)
    raise exception


def _return_after_yield(value):
    """Build an async callable that yields once then returns a value."""

    async def _mock_call():
        return await _async_return(value)

    return _mock_call


def _raise_after_yield(exception: Exception):
    """Build an async callable that yields once then raises an exception."""

    async def _mock_call():
        await _async_raise(exception)

    return _mock_call


async def _start_user_flow(hass):
    """Start the PoolSync user flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )


async def _submit_user_flow(hass, flow_id: str, ip_address: str = TEST_IP_ADDRESS):
    """Submit the PoolSync user step."""
    return await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={CONF_IP_ADDRESS: ip_address},
    )


@pytest.mark.parametrize(
    ("status_response", "expected_error"),
    [
        ({"timeRemaining": 0}, "link_timeout"),
        ({CONF_PASSWORD: TEST_PASSWORD}, "link_failed"),
    ],
)
async def test_user_flow_link_failures(
    hass, status_response: dict[str, str | int], expected_error: str
) -> None:
    """Test user flow failures after push-link starts."""
    result = await _start_user_flow(hass)

    with (
        patch(
            "custom_components.poolsync_custom.config_flow.PoolSyncApiClient.start_pushlink",
            new=AsyncMock(return_value={"timeRemaining": 120}),
        ),
        patch(
            "custom_components.poolsync_custom.config_flow.PoolSyncApiClient.get_pushlink_status",
            new=AsyncMock(side_effect=_return_after_yield(status_response)),
        ),
    ):
        result = await _submit_user_flow(hass, result["flow_id"])
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        assert result["step_id"] == "link"

        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "link_failed"
    assert result["errors"] == {"base": expected_error}


async def test_user_flow_success(hass, mock_setup_entry) -> None:
    """Test the happy path for the PoolSync user flow."""
    result = await _start_user_flow(hass)

    with (
        patch(
            "custom_components.poolsync_custom.config_flow.PoolSyncApiClient.start_pushlink",
            new=AsyncMock(return_value={"timeRemaining": 120}),
        ),
        patch(
            "custom_components.poolsync_custom.config_flow.PoolSyncApiClient.get_pushlink_status",
            new=AsyncMock(
                side_effect=_return_after_yield(
                    {
                        CONF_PASSWORD: TEST_PASSWORD,
                        API_RESPONSE_MAC_ADDRESS: TEST_MAC_ADDRESS,
                    }
                )
            ),
        ),
    ):
        result = await _submit_user_flow(hass, result["flow_id"])
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        assert result["step_id"] == "link"

        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "PoolSync (DDEEFF)"
    assert result["data"] == {
        CONF_IP_ADDRESS: TEST_IP_ADDRESS,
        CONF_PASSWORD: TEST_PASSWORD,
        API_RESPONSE_MAC_ADDRESS: TEST_MAC_ADDRESS,
    }
    assert mock_setup_entry.await_count == 1


async def test_user_flow_invalid_ip(hass) -> None:
    """Test the user flow rejects invalid IP addresses."""
    result = await _start_user_flow(hass)
    result = await _submit_user_flow(hass, result["flow_id"], ip_address="not-an-ip")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_ip"}


async def test_user_flow_cannot_connect(hass) -> None:
    """Test the user flow surfaces cannot-connect errors."""
    result = await _start_user_flow(hass)

    with patch(
        "custom_components.poolsync_custom.config_flow.PoolSyncApiClient.start_pushlink",
        new=AsyncMock(side_effect=PoolSyncApiCommunicationError("cannot connect")),
    ):
        result = await _submit_user_flow(hass, result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_polling_api_error(hass) -> None:
    """Test the user flow surfaces polling API failures."""
    result = await _start_user_flow(hass)

    with (
        patch(
            "custom_components.poolsync_custom.config_flow.PoolSyncApiClient.start_pushlink",
            new=AsyncMock(return_value={"timeRemaining": 120}),
        ),
        patch(
            "custom_components.poolsync_custom.config_flow.PoolSyncApiClient.get_pushlink_status",
            new=AsyncMock(
                side_effect=_raise_after_yield(PoolSyncApiError("bad response"))
            ),
        ),
    ):
        result = await _submit_user_flow(hass, result["flow_id"])
        assert result["type"] is FlowResultType.SHOW_PROGRESS

        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "link_failed"
    assert result["errors"] == {"base": "link_failed"}


async def test_options_flow_success(hass) -> None:
    """Test the PoolSync options flow saves a valid polling interval."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="PoolSync",
        data={
            CONF_IP_ADDRESS: TEST_IP_ADDRESS,
            CONF_PASSWORD: TEST_PASSWORD,
            API_RESPONSE_MAC_ADDRESS: TEST_MAC_ADDRESS,
        },
        options={OPTION_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
        unique_id=TEST_MAC_ADDRESS,
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={OPTION_SCAN_INTERVAL: 30},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {OPTION_SCAN_INTERVAL: 30}
    assert config_entry.options == {OPTION_SCAN_INTERVAL: 30}


async def test_options_flow_invalid_interval(hass) -> None:
    """Test the PoolSync options flow rejects too-small intervals."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="PoolSync",
        data={
            CONF_IP_ADDRESS: TEST_IP_ADDRESS,
            CONF_PASSWORD: TEST_PASSWORD,
            API_RESPONSE_MAC_ADDRESS: TEST_MAC_ADDRESS,
        },
        options={OPTION_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
        unique_id=TEST_MAC_ADDRESS,
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={OPTION_SCAN_INTERVAL: 5},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {"base": "invalid_scan_interval"}

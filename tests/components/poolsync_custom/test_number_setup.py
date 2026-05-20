"""Tests for PoolSync number platform setup."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import Mock

from custom_components.poolsync_custom.number import (
    NUMBER_DESCRIPTIONS_CHLOR,
    NUMBER_DESCRIPTIONS_HEATPUMP_F,
    async_setup_entry,
)
from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data


def _build_entry(coordinator) -> Mock:
    """Build a config-entry-like object for setup tests."""
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


async def test_async_setup_entry_uses_detected_device_ids(hass) -> None:
    """Test setup creates number entities from detected PoolSync device IDs."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.device_info = {"identifiers": {("poolsync_custom", "AABBCCDDEEFF")}}
    coordinator.password = "test-password"
    coordinator.api_client = Mock()
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "5": {"config": {"chlorOutput": 55}},
            "7": {"config": {"setpoint": 82, "mode": 1}},
        },
        "deviceType": {
            "5": "chlorSync",
            "7": "heatPump",
        },
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    added_entities: list = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert len(added_entities) == 3
    assert {entity.native_value for entity in added_entities} == {55.0, 82.0, 1.0}
    assert NUMBER_DESCRIPTIONS_CHLOR[0][0].key == "chlor_output_control"
    assert NUMBER_DESCRIPTIONS_HEATPUMP_F[0][0].key == "temperature_output_control"

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
    coordinator.get_device_info = Mock(
        side_effect=lambda role: {
            "identifiers": {("poolsync_custom", f"AABBCCDDEEFF_{role}")}
        }
    )
    coordinator.password = "test-password"
    coordinator.api_client = Mock()
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "5": {"config": {"chlorOutput": 55}},
            "7": {
                "config": {
                    "setpoint": 82,
                    "spaSetpoint": 99,
                    "poolSpaMode": 1,
                    "mode": 1,
                }
            },
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

    assert len(added_entities) == 2
    assert (
        next(
            entity
            for entity in added_entities
            if entity.entity_description.key == "temperature_output_control"
        ).native_value
        == 99.0
    )
    assert (
        next(
            entity
            for entity in added_entities
            if entity.entity_description.key == "temperature_output_control"
        ).entity_description.translation_key
        == "active_target_temperature"
    )
    assert NUMBER_DESCRIPTIONS_CHLOR[0][0].key == "chlor_output_control"
    assert NUMBER_DESCRIPTIONS_HEATPUMP_F[0][0].key == "temperature_output_control"

"""Tests for PoolSync number platform setup."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import Mock

from homeassistant.const import EntityCategory

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
        side_effect=lambda role, index=0: {
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
    assert (
        next(
            entity
            for entity in added_entities
            if entity.entity_description.key == "temperature_output_control"
        ).entity_description.entity_category
        == EntityCategory.CONFIG
    )
    assert NUMBER_DESCRIPTIONS_CHLOR[0][0].key == "chlor_output_control"
    assert NUMBER_DESCRIPTIONS_HEATPUMP_F[0][0].key == "temperature_output_control"


async def test_group_duration_number_uses_translation_placeholders(hass) -> None:
    """Test group-duration numbers use translation placeholders, not _attr_name."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(
        return_value={"identifiers": {("poolsync_custom", "AABBCCDDEEFF_controller")}}
    )
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "7": {
                "equip": {
                    "0": [3, "HEAT PUMP"],
                    "1": [0, "CIRCULATION PUMP"],
                    "3": [1, "RETURN VALVE"],
                },
                "groups": {
                    "1": {
                        "config": ["WATERFALL", 22, 24, 1, 21600, 21586, 1, 1],
                        "equip": {"1": [60, 0], "3": [3, 0]},
                    },
                },
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    added_entities: list = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    group_duration = next(
        entity
        for entity in added_entities
        if entity.entity_description.key == "group_duration"
    )
    assert group_duration.translation_key == "group_duration"
    assert group_duration.translation_placeholders == {"group_name": "WATERFALL"}
    assert not hasattr(group_duration, "_attr_name")
    assert group_duration.has_entity_name is True
    assert group_duration.native_value == 360.0  # 21600 seconds → 360 minutes

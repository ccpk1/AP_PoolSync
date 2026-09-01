"""Tests for PoolSync switch platform (group switches)."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from unittest.mock import Mock

from homeassistant.components.switch import SwitchEntityDescription

from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data
from custom_components.poolsync_custom.switch import (
    PoolSyncGroupSwitch,
    async_setup_entry,
)


def _build_entry(coordinator) -> Mock:
    """Build a config-entry-like object for setup tests."""
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


def _build_coordinator() -> Mock:
    """Build a coordinator mock with group data present."""
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
                    "0": {
                        "config": ["POOL", 0, 192, 2, 172800, 0, 1, 1],
                        "equip": {"1": [35, 0], "3": [0, 0]},
                    },
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
    return coordinator


async def test_async_setup_entry_creates_one_switch_per_group(hass) -> None:
    """Test setup creates a group switch for each group."""
    coordinator = _build_coordinator()
    added_entities: list[PoolSyncGroupSwitch] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert len(added_entities) == 2
    assert {e.entity_description.key for e in added_entities} == {
        "group_0",
        "group_1",
    }


async def test_group_switch_uses_translation_placeholders_for_name(hass) -> None:
    """Test group switch names come from translation placeholders, not _attr_name."""
    coordinator = _build_coordinator()
    entity = PoolSyncGroupSwitch(
        coordinator,
        SwitchEntityDescription(key="group_1", translation_key="group"),
        group_key="1",
        group_name="WATERFALL",
    )

    assert entity.translation_key == "group"
    assert entity.translation_placeholders == {"group_name": "WATERFALL"}
    assert not hasattr(entity, "_attr_name")
    assert entity.has_entity_name is True


async def test_group_switch_placeholders_refresh_from_coordinator(hass) -> None:
    """Test placeholders refresh from the latest group config on coordinator update."""
    coordinator = _build_coordinator()
    entity = PoolSyncGroupSwitch(
        coordinator,
        SwitchEntityDescription(key="group_1", translation_key="group"),
        group_key="1",
        group_name="STALE NAME",
    )

    # The live group name wins immediately at construction
    assert entity.translation_placeholders == {"group_name": "WATERFALL"}

    # Refreshing placeholders keeps the live group name
    entity._update_translation_placeholders()
    assert entity.translation_placeholders == {"group_name": "WATERFALL"}


async def test_group_switch_unique_id_is_stable_and_name_independent(hass) -> None:
    """Test unique IDs are anchored to the group key, not the group name."""
    coordinator = _build_coordinator()
    entity = PoolSyncGroupSwitch(
        coordinator,
        SwitchEntityDescription(key="group_1", translation_key="group"),
        group_key="1",
        group_name="WATERFALL",
    )

    assert entity.unique_id == "AABBCCDDEEFF_group_1"
    assert entity.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_controller")
    }

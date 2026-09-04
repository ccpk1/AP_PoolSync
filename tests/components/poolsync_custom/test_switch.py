"""Tests for PoolSync switch platform (group switches)."""

# pylint: disable=import-error,no-name-in-module,protected-access

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from homeassistant.components.switch import SwitchEntityDescription

from custom_components.poolsync_custom.runtime import parse_poolsync_runtime_data
from custom_components.poolsync_custom.switch import (
    PoolSyncGroupScheduleSwitch,
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
                "schedules": {
                    "0": {
                        "0": [62, 8, 11],
                        "1": [62, 17, 0],
                        "2": [65, 0, 0],
                        "3": [0, 11527, 8],
                    },
                    "1": {
                        "0": [0, 8, 14],
                        "1": [0, 8, 14],
                        "2": [0, 8, 14],
                        "3": [0, 8, 14],
                    },
                },
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)
    coordinator._refresh_seq = 0
    coordinator.refresh_seq = 0
    coordinator.get_group_duration_pref = Mock(return_value=None)
    return coordinator


async def test_async_setup_entry_creates_one_switch_per_group(hass) -> None:
    """Test setup creates a group switch and schedule switch for each group."""
    coordinator = _build_coordinator()
    added_entities: list[PoolSyncGroupSwitch | PoolSyncGroupScheduleSwitch] = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert len(added_entities) == 4
    assert {e.entity_description.key for e in added_entities} == {
        "group_0",
        "group_1",
        "group_0_schedule",
        "group_1_schedule",
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


async def test_group_switch_duration_attribute_formatted(hass) -> None:
    """Test the duration features use the consistent Dd HH:MM format."""
    coordinator = _build_coordinator()
    # Set up the preference to match the device's timeSet (172800s = 2880 min)
    coordinator.get_group_duration_pref = Mock(return_value=2880)
    entity = PoolSyncGroupSwitch(
        coordinator,
        SwitchEntityDescription(key="group_0", translation_key="group"),
        group_key="0",
        group_name="POOL",
    )

    # duration = user preference (from group_duration_prefs)
    assert entity.extra_state_attributes["duration"] == "2d 00:00"
    # controller_duration = device timeSet (from the controller)
    assert entity.extra_state_attributes["controller_duration"] == "2d 00:00"


async def test_group_switch_duration_shows_preference_over_device(hass) -> None:
    """Test that duration attr shows preference, controller_duration shows device."""
    coordinator = _build_coordinator()
    # Preference is 30 minutes (1800 seconds), but device timeSet is 172800s
    coordinator.get_group_duration_pref = Mock(return_value=30)
    entity = PoolSyncGroupSwitch(
        coordinator,
        SwitchEntityDescription(key="group_0", translation_key="group"),
        group_key="0",
        group_name="POOL",
    )

    # duration = user preference: 30 min → 0d 00:30
    assert entity.extra_state_attributes["duration"] == "0d 00:30"
    # controller_duration = device: 172800s → 2d 00:00
    assert entity.extra_state_attributes["controller_duration"] == "2d 00:00"


async def test_group_schedule_switch_uses_translation_placeholders(hass) -> None:
    """Test schedule switch names come from translation placeholders."""
    coordinator = _build_coordinator()
    entity = PoolSyncGroupScheduleSwitch(
        coordinator,
        SwitchEntityDescription(
            key="group_1_schedule", translation_key="group_schedule"
        ),
        group_key="1",
        group_name="WATERFALL",
    )

    assert entity.translation_key == "group_schedule"
    assert entity.translation_placeholders == {"group_name": "WATERFALL"}
    assert not hasattr(entity, "_attr_name")
    assert entity.has_entity_name is True


async def test_group_schedule_switch_reflects_sched_mode(hass) -> None:
    """Test the schedule switch reflects the group's schedMode (config[7])."""
    coordinator = _build_coordinator()
    entity = PoolSyncGroupScheduleSwitch(
        coordinator,
        SwitchEntityDescription(
            key="group_1_schedule", translation_key="group_schedule"
        ),
        group_key="1",
        group_name="WATERFALL",
    )

    # WATERFALL config[7] = 1 → schedule enabled
    assert entity.is_on is True


async def test_group_schedule_switch_exposes_decoded_slots(hass) -> None:
    """Test the schedule switch exposes decoded schedule slots as attributes."""
    coordinator = _build_coordinator()
    entity = PoolSyncGroupScheduleSwitch(
        coordinator,
        SwitchEntityDescription(
            key="group_0_schedule", translation_key="group_schedule"
        ),
        group_key="0",
        group_name="POOL",
    )

    schedules = entity.extra_state_attributes["schedules"]
    # POOL slots: [62,8,11] Mon-Fri 08:00-11:00, [62,17,0] Mon-Fri 17:00-00:00,
    # [65,0,0] Sat-Sun 00:00-00:00, [0,11527,8] disabled (11527 = 7:45am)
    assert schedules == [
        {"days": "Mon-Fri", "start": "08:00", "end": "11:00"},
        {"days": "Mon-Fri", "start": "17:00", "end": "00:00"},
        {"days": "Sat-Sun", "start": "00:00", "end": "00:00"},
        {"days": "disabled", "start": "07:45", "end": "08:00"},
    ]


async def test_group_schedule_switch_unique_id_is_stable(hass) -> None:
    """Test schedule switch unique IDs are anchored to the group key."""
    coordinator = _build_coordinator()
    entity = PoolSyncGroupScheduleSwitch(
        coordinator,
        SwitchEntityDescription(
            key="group_1_schedule", translation_key="group_schedule"
        ),
        group_key="1",
        group_name="WATERFALL",
    )

    assert entity.unique_id == "AABBCCDDEEFF_group_1_schedule"
    assert entity.device_info["identifiers"] == {
        ("poolsync_custom", "AABBCCDDEEFF_controller")
    }


async def test_group_switch_turn_on_is_optimistic(hass) -> None:
    """Test turn_on reflects state optimistically and keeps it until post-write data."""
    coordinator = _build_coordinator()
    coordinator.async_set_group_state = AsyncMock()
    entity = PoolSyncGroupSwitch(
        coordinator,
        SwitchEntityDescription(key="group_1", translation_key="group"),
        group_key="1",
        group_name="WATERFALL",
    )
    assert entity.is_on is True  # WATERFALL config[3] = 1

    await entity.async_turn_off()
    assert entity.is_on is False
    assert entity._optimistic is True

    # A pre-write refresh (seq unchanged) must not overwrite the optimistic state
    entity._update_attrs()
    assert entity.is_on is False
    assert entity._optimistic is True

    # Post-write data arrives (seq bumps) → clear optimistic and trust read-back.
    coordinator.refresh_seq += 1
    entity._update_attrs()
    assert entity._optimistic is False
    assert entity.is_on is True


async def test_group_schedule_switch_turn_off_is_optimistic(hass) -> None:
    """Test schedule switch keeps requested state until post-write data arrives."""
    coordinator = _build_coordinator()
    coordinator.async_set_group_schedule_mode = AsyncMock()
    entity = PoolSyncGroupScheduleSwitch(
        coordinator,
        SwitchEntityDescription(
            key="group_1_schedule", translation_key="group_schedule"
        ),
        group_key="1",
        group_name="WATERFALL",
    )
    assert entity.is_on is True  # WATERFALL config[7] = 1

    await entity.async_turn_off()
    assert entity.is_on is False
    assert entity._optimistic is True

    # Pre-write refresh must not overwrite.
    entity._update_attrs()
    assert entity.is_on is False

    # Post-write data arrives → trust read-back.
    coordinator.refresh_seq += 1
    entity._update_attrs()
    assert entity._optimistic is False
    assert entity.is_on is True

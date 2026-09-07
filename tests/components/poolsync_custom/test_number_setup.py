"""Tests for PoolSync number platform setup."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false
# pyright: reportMissingModuleSource=false

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, call

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
    # Seeded from the device's timeSet (21600s → 360 min) the first time.
    assert group_duration.native_value == 360.0
    # Read-only reference attribute shows the controller's configured duration.
    assert group_duration.extra_state_attributes["controller_duration"] == "0d 06:00"

    # The preference is never overwritten by the device value: once set, a
    # coordinator update leaves the number untouched (only the read-only
    # reference attribute tracks the controller).
    group_duration._attr_native_value = 45.0
    group_duration._update_attrs()
    assert group_duration.native_value == 45.0
    assert group_duration.extra_state_attributes["controller_duration"] == "0d 06:00"


# ===================================================================
# Group duration number entity — restore & write path
# ===================================================================


def _build_group_duration_entity(coordinator) -> None:
    """Build a group-duration number entity attached to a coordinator."""
    from custom_components.poolsync_custom.number import PoolSyncChlorOutputNumberEntity
    from homeassistant.components.number import NumberEntityDescription

    return PoolSyncChlorOutputNumberEntity(
        coordinator,
        "controller",
        NumberEntityDescription(
            key="group_duration",
            name="Group Duration",
            native_min_value=0,
            native_max_value=1440,
            native_step=1,
        ),
        _group_key="1",
        _group_name="WATERFALL",
    )


async def test_group_duration_restore_skips_non_group(hass) -> None:
    """Test restore is skipped for non-group number entities."""
    from custom_components.poolsync_custom.number import PoolSyncChlorOutputNumberEntity
    from homeassistant.components.number import NumberEntityDescription

    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(return_value={})
    coordinator.refresh_seq = 0
    coordinator.set_group_duration_pref = Mock()
    coordinator.data = {
        "poolSync": {},
        "devices": {"1": {"config": {"chlorOutput": 50}}},
        "deviceType": {"1": "chlorSync"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncChlorOutputNumberEntity(
        coordinator,
        "chlorinator",
        NumberEntityDescription(
            key="chlor_output_control",
            name="Chlorinator Output",
            native_min_value=0,
            native_max_value=100,
            native_step=1,
        ),
    )
    entity.async_get_last_state = AsyncMock(return_value=None)
    await entity.async_added_to_hass()
    coordinator.set_group_duration_pref.assert_not_called()


async def test_group_duration_restore_restores_preference(hass) -> None:
    """Test restore repopulates the group duration preference."""
    from custom_components.poolsync_custom.number import PoolSyncChlorOutputNumberEntity
    from homeassistant.components.number import NumberEntityDescription

    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(return_value={})
    coordinator.refresh_seq = 0
    coordinator.set_group_duration_pref = Mock()
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "7": {
                "equip": {"0": [3, "HEAT PUMP"], "1": [0, "CIRCULATION PUMP"]},
                "groups": {
                    "1": {"config": ["WATERFALL", 22, 24, 1, 21600, 21586, 1, 1]}
                },
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncChlorOutputNumberEntity(
        coordinator,
        "controller",
        NumberEntityDescription(
            key="group_duration",
            name="Group Duration",
            native_min_value=0,
            native_max_value=1440,
            native_step=1,
        ),
        _group_key="1",
        _group_name="WATERFALL",
    )
    entity.async_get_last_state = AsyncMock(return_value=Mock(state="45.0"))
    await entity.async_added_to_hass()
    # The restore overwrites the init-seeded preference (360) with the restored value (45).
    assert coordinator.set_group_duration_pref.call_args_list[-1] == call("1", 45)
    assert entity.native_value == 45.0


async def test_group_duration_restore_skips_unavailable(hass) -> None:
    """Test restore skips unavailable/unknown last states."""
    from custom_components.poolsync_custom.number import PoolSyncChlorOutputNumberEntity
    from homeassistant.components.number import NumberEntityDescription
    from homeassistant.const import STATE_UNAVAILABLE

    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(return_value={})
    coordinator.refresh_seq = 0
    coordinator.set_group_duration_pref = Mock()
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "7": {
                "equip": {"0": [3, "HEAT PUMP"], "1": [0, "CIRCULATION PUMP"]},
                "groups": {
                    "1": {"config": ["WATERFALL", 22, 24, 1, 21600, 21586, 1, 1]}
                },
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncChlorOutputNumberEntity(
        coordinator,
        "controller",
        NumberEntityDescription(
            key="group_duration",
            name="Group Duration",
            native_min_value=0,
            native_max_value=1440,
            native_step=1,
        ),
        _group_key="1",
        _group_name="WATERFALL",
    )
    entity.async_get_last_state = AsyncMock(return_value=Mock(state=STATE_UNAVAILABLE))
    await entity.async_added_to_hass()
    # Only the init-seeded preference (360) is set; restore is skipped.
    assert coordinator.set_group_duration_pref.call_args_list == [call("1", 360)]


async def test_group_duration_restore_skips_invalid_value(hass) -> None:
    """Test restore skips non-numeric last states."""
    from custom_components.poolsync_custom.number import PoolSyncChlorOutputNumberEntity
    from homeassistant.components.number import NumberEntityDescription

    coordinator = Mock()
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.get_device_info = Mock(return_value={})
    coordinator.refresh_seq = 0
    coordinator.set_group_duration_pref = Mock()
    coordinator.data = {
        "poolSync": {},
        "devices": {
            "7": {
                "equip": {"0": [3, "HEAT PUMP"], "1": [0, "CIRCULATION PUMP"]},
                "groups": {
                    "1": {"config": ["WATERFALL", 22, 24, 1, 21600, 21586, 1, 1]}
                },
            }
        },
        "deviceType": {"7": "heatPump"},
    }
    coordinator.parsed_data = parse_poolsync_runtime_data(coordinator.data)

    entity = PoolSyncChlorOutputNumberEntity(
        coordinator,
        "controller",
        NumberEntityDescription(
            key="group_duration",
            name="Group Duration",
            native_min_value=0,
            native_max_value=1440,
            native_step=1,
        ),
        _group_key="1",
        _group_name="WATERFALL",
    )
    entity.async_get_last_state = AsyncMock(return_value=Mock(state="not-a-number"))
    await entity.async_added_to_hass()
    # Only the init-seeded preference (360) is set; restore is skipped.
    assert coordinator.set_group_duration_pref.call_args_list == [call("1", 360)]


# ===================================================================
# Number setup early returns
# ===================================================================


async def test_async_setup_entry_skips_when_no_data(hass) -> None:
    """Test number setup skips creation when the coordinator has no data."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.data = None

    added_entities: list = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert added_entities == []


async def test_async_setup_entry_skips_when_no_devices(hass) -> None:
    """Test number setup skips creation when the devices key is missing."""
    coordinator = Mock()
    coordinator.name = "PoolSync"
    coordinator.mac_address = "AABBCCDDEEFF"
    coordinator.data = {"poolSync": {}}

    added_entities: list = []

    def _async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, _build_entry(coordinator), _async_add_entities)

    assert added_entities == []

"""The PoolSync Custom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from . import binary_sensor as poolsync_binary_sensor
from . import button as poolsync_button
from . import number as poolsync_number
from . import select as poolsync_select
from . import sensor as poolsync_sensor
from . import switch as poolsync_switch
from .api import PoolSyncApiClient, async_create_poolsync_session
from .const import (
    API_RESPONSE_MAC_ADDRESS,
    DEFAULT_SCAN_INTERVAL,
    OPTION_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import PoolSyncDataUpdateCoordinator
from .runtime import PoolSyncParsedData, ensure_parsed_data, get_equipment_runtime

_LOGGER = logging.getLogger(__name__)

type PoolSyncConfigEntry = ConfigEntry[PoolSyncDataUpdateCoordinator]


def _build_entity_key_whitelist() -> dict[str, set[str]]:
    """Merge all platform entity key whitelists into a single role→keys mapping.

    This is the single source of truth for which entity keys are valid
    for each device role. The whitelist is derived directly from the
    platform-level description tuples, so it stays in sync automatically.
    """
    merged: dict[str, set[str]] = {}
    for module in (
        poolsync_binary_sensor,
        poolsync_button,
        poolsync_number,
        poolsync_select,
        poolsync_sensor,
        poolsync_switch,
    ):
        fn = getattr(module, "get_valid_entity_keys", None)
        if fn is None:
            continue
        for role, keys in fn().items():
            merged.setdefault(role, set()).update(keys)
    return merged


_ENTITY_KEY_WHITELIST = _build_entity_key_whitelist()


def _resolve_migration_target(
    entity_suffix: str,
    parsed_data: PoolSyncParsedData,
) -> str | None:
    """Map an entity unique ID suffix to a {role}_{index} target.

    Suffix formats:
      "water_temp"          → first chlorinator (index 0)
      "chlorinator_19_water_temp" → chlorinator whose nodeAddr == 19
      "hp_water_temp"       → first heat pump (index 0)
      "heat_pump_42_water_temp" → heat pump whose nodeAddr == 42
    """
    for role_key, device_list in parsed_data.devices.items():
        role_keys = _ENTITY_KEY_WHITELIST.get(role_key, set())
        # Check first-instance format (BC): simple key match
        if entity_suffix in role_keys:
            return f"{role_key}_0"
        # Check second-instance format: {role_key}_{nodeAddr}_{key}
        for index, device in enumerate(device_list):
            if device.node_addr is not None:
                prefix = f"{role_key}_{device.node_addr}_"
                stripped = entity_suffix.removeprefix(prefix)
                if stripped != entity_suffix and stripped in role_keys:
                    return f"{role_key}_{index}"
    return None


def _async_migrate_entity_device_assignments(
    hass: HomeAssistant,
    entry: PoolSyncConfigEntry,
    coordinator: PoolSyncDataUpdateCoordinator,
) -> None:
    """Move existing entities to their role-specific devices."""
    parsed_data = coordinator.parsed_data
    if parsed_data is None:
        if not isinstance(coordinator.data, dict):
            return
        parsed_data = ensure_parsed_data(coordinator)

    if not parsed_data.devices:
        return

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    unique_id_prefix = f"{coordinator.mac_address}_"

    role_device_ids: dict[str, str] = {}
    for role_key, device_list in parsed_data.devices.items():
        if role_key not in ("chlorinator", "heat_pump", "chem_sync"):
            continue
        for index, device in enumerate(device_list):
            if device.device_id is None:
                continue
            role_device = device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **coordinator.get_device_info(role_key, index=index),
            )
            role_device_ids[f"{role_key}_{index}"] = role_device.id

    if not role_device_ids:
        return

    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.unique_id is None or not entity_entry.unique_id.startswith(
            unique_id_prefix
        ):
            continue

        entity_suffix = entity_entry.unique_id.removeprefix(unique_id_prefix)
        target_key = _resolve_migration_target(entity_suffix, parsed_data)
        if target_key is None:
            continue

        target_device_id = role_device_ids.get(target_key)
        if target_device_id is None or entity_entry.device_id == target_device_id:
            continue

        entity_registry.async_update_entity(
            entity_entry.entity_id,
            device_id=target_device_id,
        )


def _async_cleanup_orphan_entities(
    hass: HomeAssistant,
    entry: PoolSyncConfigEntry,
    coordinator: PoolSyncDataUpdateCoordinator,
) -> None:
    """Remove entities from the registry that are no longer valid.

    Each entity's unique_id suffix is validated against the whitelist
    derived from the platform description tuples. Entities whose key
    is not in the whitelist for their device role are removed.

    This handles three patterns:
      - {mac}_{key}              → role-based entity (validated via whitelist)
      - {mac}_equip_{slot}_{key} → equipment entity (validated via equipment whitelist)
      - {mac}_heat_pump_group_X  → dynamic group switch (validated via parsed groups)
    """
    entity_registry = er.async_get(hass)
    unique_id_prefix = f"{coordinator.mac_address}_"

    # Try to get parsed data; if unavailable, skip dynamic group validation
    try:
        parsed_data = coordinator.get_parsed_data()
    except (HomeAssistantError, AttributeError):
        parsed_data = None

    # Collect dynamic group keys from parsed data
    group_keys: set[str] = set()
    if parsed_data is not None:
        equip_runtime = get_equipment_runtime(parsed_data)
        if equip_runtime is not None and isinstance(equip_runtime.raw_groups, dict):
            for group_key in equip_runtime.raw_groups:
                if isinstance(group_key, str):
                    group_keys.add(f"group_{group_key}")

    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.unique_id is None or not entity_entry.unique_id.startswith(
            unique_id_prefix
        ):
            continue

        entity_suffix = entity_entry.unique_id.removeprefix(unique_id_prefix)

        # Pattern 1: Controller-level entity — {mac}_{key} (no role prefix)
        if entity_suffix in _ENTITY_KEY_WHITELIST.get("controller", set()):
            continue  # Valid controller entity

        # Pattern 2: Equipment entity — {mac}_equip_{slot}_{key}
        if entity_suffix.startswith("equip_"):
            parts = entity_suffix.split("_", 2)
            if len(parts) == 3 and parts[2] in _ENTITY_KEY_WHITELIST.get(
                "equipment", set()
            ):
                continue  # Valid equipment entity

        # Pattern 3: Role-based entity — {mac}_{key} or {mac}_{role}_{nodeAddr}_{key}
        elif parsed_data is not None and _resolve_migration_target(
            entity_suffix, parsed_data
        ) is not None:
            continue  # Valid role entity

        # Pattern 4: Group switch — {mac}_heat_pump_group_{key}
        elif entity_suffix in group_keys:
            continue  # Valid group switch

        # Not in any whitelist — remove
        entity_registry.async_remove(entity_entry.entity_id)
        _LOGGER.info(
            "Removed orphan entity %s (unique_id: %s)",
            entity_entry.entity_id,
            entity_entry.unique_id,
        )


async def async_setup_entry(hass: HomeAssistant, entry: PoolSyncConfigEntry) -> bool:
    """Set up PoolSync Custom from a config entry."""
    _LOGGER.info(
        "Setting up PoolSync integration for entry %s (IP: %s, Title: %s)",
        entry.entry_id,
        entry.data.get(CONF_IP_ADDRESS),
        entry.title,
    )

    ip_address = entry.data[CONF_IP_ADDRESS]
    password = entry.data[CONF_PASSWORD]
    mac_address = entry.data.get(API_RESPONSE_MAC_ADDRESS)
    if not mac_address:
        raise ConfigEntryError(
            f"Missing PoolSync MAC address in config entry for {ip_address}"
        )

    session = async_create_poolsync_session(hass)
    api_client = PoolSyncApiClient(ip_address=ip_address, session=session)

    scan_interval = entry.options.get(OPTION_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    _LOGGER.debug("Using scan interval of %d seconds for %s", scan_interval, ip_address)

    coordinator = PoolSyncDataUpdateCoordinator(
        hass=hass,
        api_client=api_client,
        password=password,
        update_interval_seconds=scan_interval,
        config_entry_id=entry.entry_id,
        mac_address=mac_address,
    )

    try:
        _LOGGER.debug("Attempting initial data refresh for %s", ip_address)
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug("Initial data refresh successful for %s.", ip_address)
    except ConfigEntryAuthFailed as err:
        _LOGGER.error(
            "Authentication failed for %s during initial refresh: %s", ip_address, err
        )
        raise
    except UpdateFailed as err:
        _LOGGER.error("Initial data update failed for %s: %s", ip_address, err)
        raise ConfigEntryNotReady(
            f"Could not connect or fetch data from {ip_address}: {err}"
        ) from err
    except Exception as err:
        _LOGGER.exception(
            "Unexpected error during initial refresh for %s: %s", ip_address, err
        )
        raise ConfigEntryNotReady(
            f"Unexpected error setting up PoolSync for {ip_address}: {err}"
        ) from err

    entry.runtime_data = coordinator
    _async_migrate_entity_device_assignments(hass, entry, coordinator)

    # Create equipment devices when equip data is present
    if isinstance(coordinator.data, dict):
        parsed_data = coordinator.get_parsed_data()
        equip_runtime = get_equipment_runtime(parsed_data)
        if equip_runtime is not None and equip_runtime.has_equipment:
            for equip in equip_runtime.equipment.values():
                dr.async_get(hass).async_get_or_create(
                    config_entry_id=entry.entry_id,
                    **coordinator.get_equipment_device_info(equip),
                )

    entry.async_on_unload(entry.add_update_listener(async_update_options_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Clean up orphan entities after platforms are set up
    _async_cleanup_orphan_entities(hass, entry, coordinator)

    _LOGGER.info("PoolSync integration setup complete for %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PoolSyncConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(
        "Unloading PoolSync integration for entry %s (IP: %s, Title: %s)",
        entry.entry_id,
        entry.data.get(CONF_IP_ADDRESS),
        entry.title,
    )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        if hasattr(entry, "runtime_data"):
            del entry.runtime_data
        _LOGGER.info("PoolSync integration successfully unloaded for %s", entry.title)
    else:
        _LOGGER.error("Failed to unload PoolSync platforms for %s", entry.title)

    return unload_ok


async def async_update_options_listener(
    hass: HomeAssistant, entry: PoolSyncConfigEntry
) -> None:
    """Handle options update."""
    _LOGGER.info(
        "Options updated for %s (new interval: %s s), reloading integration.",
        entry.title,
        entry.options.get(OPTION_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await hass.config_entries.async_reload(entry.entry_id)

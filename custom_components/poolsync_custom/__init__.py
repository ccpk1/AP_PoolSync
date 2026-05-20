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
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import PoolSyncApiClient
from .const import (
    API_RESPONSE_MAC_ADDRESS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import PoolSyncDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

type PoolSyncConfigEntry = ConfigEntry[PoolSyncDataUpdateCoordinator]


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

    session = async_get_clientsession(hass)
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

    entry.async_on_unload(entry.add_update_listener(async_update_options_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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

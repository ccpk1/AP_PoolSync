"""Pytest configuration for PoolSync custom integration tests.

``pytest-homeassistant-custom-component`` pins the exact Home Assistant release
it was built against, so it only imports cleanly in a virtual environment where
that pin is satisfied.  A Home Assistant *core* development environment (an
editable ``/workspaces/core`` checkout on a ``.dev`` build) never satisfies it,
and a hard plugin import there aborts collection for every test -- including
the pure parsing tests that do not need Home Assistant at all.

The plugin is therefore loaded when importable; when it is not, collection is
limited to the parsing-only modules, which need nothing from it.
``utils/setup_test_env.sh`` creates an isolated environment that always
resolves a matching plugin/Home Assistant pair, and ``utils/run_tests.sh`` runs
the suite through it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _probe_ha_plugin() -> str | None:
    """Return None when the Home Assistant test plugin imports cleanly.

    The probe runs in a subprocess on purpose. Importing the plugin in this
    process when its pinned Home Assistant is unavailable raises, but only
    after pulling in ``httpx``; Home Assistant's own ``__init__`` then fails
    with ``httpx2`` alias errors, which would break every later import in this
    process -- including the parsing tests that never touch the plugin.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest_homeassistant_custom_component.plugins"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode == 0:
        return None
    lines = [line for line in probe.stderr.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "plugin import failed"


_HA_PLUGIN_IMPORT_ERROR = _probe_ha_plugin()

if _HA_PLUGIN_IMPORT_ERROR is None:
    pytest_plugins = ["pytest_homeassistant_custom_component"]
else:
    pytest_plugins = []

# Modules that exercise parsing/derived state only and therefore run in any
# interpreter. Everything else needs the plugin's ``hass`` fixture and an
# isolated environment (utils/setup_test_env.sh).
_PLUGIN_FREE_TEST_MODULES = frozenset(
    {
        "test_equipment.py",
        "test_fault_codes.py",
        "test_runtime.py",
    }
)

if _HA_PLUGIN_IMPORT_ERROR is None:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
        """Enable custom integrations for all tests."""
        del enable_custom_integrations


def pytest_report_header() -> str:
    """Report whether the Home Assistant test plugin is usable."""
    if _HA_PLUGIN_IMPORT_ERROR is None:
        return "poolsync: pytest-homeassistant-custom-component loaded"
    return (
        "poolsync: pytest-homeassistant-custom-component UNAVAILABLE "
        f"({_HA_PLUGIN_IMPORT_ERROR}); only the plugin-free parsing tests run. "
        "Run utils/setup_test_env.sh for the full suite."
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Limit collection to plugin-free modules when the plugin is unusable.

    Without the plugin, Home Assistant entity tests fail for reasons unrelated
    to the integration, and modules that import the plugin raise while being
    imported. Ignoring them keeps the parsing tests runnable anywhere.
    """
    if _HA_PLUGIN_IMPORT_ERROR is None or collection_path.suffix != ".py":
        return None
    if collection_path.name in _PLUGIN_FREE_TEST_MODULES:
        return None
    return True

#!/usr/bin/env bash
#
# Run the PoolSync test suite in the environment created by
# utils/setup_test_env.sh, so the interpreter can never be the shared Home
# Assistant core development environment (whose Home Assistant build is
# incompatible with the pinned test plugin).
#
# Usage:
#   ./utils/run_tests.sh                     # whole suite
#   ./utils/run_tests.sh -k heat_pump        # any pytest arguments
#
# Falls back to the active interpreter with a warning when .venv is missing,
# in which case Home Assistant dependent tests are skipped rather than failing.

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

venv="${VENV_PATH:-$repo_root/.venv}"

# The plugin is registered as a pytest entry point, so pytest imports
# pytest_homeassistant_custom_component.plugins at startup and it fails hard
# before conftest can guard it. Probe that exact module: an incompatible Home
# Assistant build fails on import even though the bare package imports fine.
ha_plugin_usable() {
    "$1" -c "import pytest_homeassistant_custom_component.plugins" >/dev/null 2>&1
}

if [[ -x "$venv/bin/python" ]]; then
    python="$venv/bin/python"
elif ha_plugin_usable "$(command -v python3)"; then
    python="$(command -v python3)"
else
    python="$(command -v python3)"
    # Disable entry point autoloading so the parsing tests still run;
    # tests/conftest.py then loads the plugin explicitly if it imports cleanly.
    export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
    echo "warning: no usable pytest-homeassistant-custom-component in $python" >&2
    echo "warning: Home Assistant tests will be skipped; run ./utils/setup_test_env.sh" >&2
fi

# Never inherit a PYTHONPATH that could point at another Home Assistant tree.
unset PYTHONPATH

exec "$python" -m pytest "$@"

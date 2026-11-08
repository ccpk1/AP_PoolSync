#!/usr/bin/env bash
#
# Create an isolated virtual environment for the integration's test suite.
#
# Why this exists: "pytest-homeassistant-custom-component" pins the exact Home
# Assistant release it was built against. The shared dev-container environment
# installs Home Assistant *core* in editable mode from a source checkout, which
# can never satisfy that pin, so the plugin fails to import and every test
# aborts at collection. Nothing in this script pins a version: the plugin is the
# thing that decides which Home Assistant release is used, so installing the
# newest plugin always yields a matching pair and no monthly edits are needed.
#
#   ./utils/setup_test_env.sh          # create/reuse .venv, install .[dev]
#   ./utils/setup_test_env.sh --fresh  # recreate .venv from scratch

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

venv="${VENV_PATH:-$repo_root/.venv}"
fresh=0

case "${1-}" in
    "") ;;
    --fresh) fresh=1 ;;
    -h | --help)
        sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    *)
        echo "Unknown argument: ${1}" >&2
        exit 2
        ;;
esac

if [[ "$fresh" -eq 1 && -d "$venv" ]]; then
    echo "Removing $venv"
    rm -rf "$venv"
fi

if command -v uv >/dev/null 2>&1; then
    echo "Using uv to build $venv"
    uv venv "$venv" --quiet --allow-existing
    VIRTUAL_ENV="$venv" uv pip install --quiet --upgrade pip
    VIRTUAL_ENV="$venv" uv pip install --quiet -e ".[dev]"
else
    echo "Using python venv to build $venv"
    python3 -m venv "$venv"
    "$venv/bin/python" -m pip install --quiet --upgrade pip
    "$venv/bin/python" -m pip install --quiet -e ".[dev]"
fi

echo
echo "Installed:"
"$venv/bin/python" -m pip show homeassistant \
    | grep -E '^(Name|Version|Editable project location):' || true
"$venv/bin/python" -m pip show pytest-homeassistant-custom-component \
    | grep -E '^(Name|Version):' || true
echo
echo "Run the tests with:"
echo "  ./utils/run_tests.sh"

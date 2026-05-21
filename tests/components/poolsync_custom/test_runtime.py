"""Tests for PoolSync runtime parsing helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.poolsync_custom.runtime import (
    HEAT_PUMP_PRESET_POOL,
    HEAT_PUMP_PRESET_SPA,
    T75_MODEL_NUMBER,
    get_heat_pump_capabilities,
    get_heat_pump_climate_hvac_action,
    get_heat_pump_climate_hvac_mode,
    get_heat_pump_climate_hvac_modes,
    get_heat_pump_climate_preset_mode,
    get_heat_pump_climate_preset_modes,
    get_heat_pump_climate_target_temperature,
    get_heat_pump_runtime,
    get_wifi_signal_status,
    parse_poolsync_runtime_data,
)


def _load_parsed_data(sample_name: str):
    """Load parsed runtime data from a sample diagnostics export."""
    sample_path = (
        Path(__file__).resolve().parents[2] / "sample_diagnostics" / sample_name
    )
    with sample_path.open(encoding="utf-8") as sample_file:
        payload = json.load(sample_file)
    return parse_poolsync_runtime_data(payload["data"]["runtime_data"])


@pytest.mark.parametrize(
    (
        "sample_name",
        "expected_flow",
        "expected_fan",
        "expected_compressor",
        "expected_mode_context",
        "expected_active_target",
    ),
    [
        ("t75-heat-pool.json", True, True, True, "heat_pool", 78),
        ("t75-off-with-flow.json", True, False, False, "off", None),
        ("t75-off-no-flow.json", False, False, False, "off", None),
        ("t75-spa-startup-fan-nocompressor.json", True, True, False, "heat_spa", 88),
        ("t75-heat-spa.json", True, True, True, "heat_spa", 88),
    ],
)
def test_t75_heat_pump_runtime_states(
    sample_name: str,
    expected_flow: bool,
    expected_fan: bool,
    expected_compressor: bool,
    expected_mode_context: str,
    expected_active_target: int | None,
) -> None:
    """Test T75-derived runtime state across observed sample payloads."""
    runtime = get_heat_pump_runtime(_load_parsed_data(sample_name))

    assert runtime is not None
    assert runtime.has_flow is expected_flow
    assert runtime.fan_running is expected_fan
    assert runtime.compressor_running is expected_compressor
    assert runtime.mode_context == expected_mode_context
    assert runtime.active_target_temperature == expected_active_target
    assert runtime.pool_setpoint == 78
    assert runtime.spa_setpoint == 88


def test_t75_heat_pump_capabilities_use_model_number() -> None:
    """Test the known T75 capability profile is selected by actual model number."""
    capabilities = get_heat_pump_capabilities(_load_parsed_data("t75-heat-pool.json"))

    assert capabilities is not None
    assert capabilities.model_number == T75_MODEL_NUMBER
    assert capabilities.profile == "t75_base_heat_pump"
    assert capabilities.supports_pool_spa_mode is True
    assert capabilities.supports_separate_spa_setpoint is True
    assert capabilities.supports_cooling is False


def test_t75_heat_pump_climate_helpers_use_contextual_runtime_state() -> None:
    """Test climate-facing runtime helpers for the known T75 profile."""
    parsed_data = _load_parsed_data("t75-heat-pool.json")

    assert get_heat_pump_climate_hvac_modes(parsed_data) == ["off", "heat"]
    assert get_heat_pump_climate_hvac_mode(parsed_data) == "heat"
    assert get_heat_pump_climate_hvac_action(parsed_data) == "heating"
    assert get_heat_pump_climate_preset_modes(parsed_data) == [
        HEAT_PUMP_PRESET_POOL,
        HEAT_PUMP_PRESET_SPA,
    ]
    assert get_heat_pump_climate_preset_mode(parsed_data) == HEAT_PUMP_PRESET_POOL
    assert get_heat_pump_climate_target_temperature(parsed_data) == 78


def test_heat_pump_climate_target_temperature_uses_selected_preset_while_off() -> None:
    """Test climate target falls back to stored pool/spa targets when off."""
    parsed_data = _load_parsed_data("t75-off-no-flow.json")

    assert (
        get_heat_pump_climate_target_temperature(parsed_data, HEAT_PUMP_PRESET_POOL)
        == 78
    )
    assert (
        get_heat_pump_climate_target_temperature(parsed_data, HEAT_PUMP_PRESET_SPA)
        == 88
    )


@pytest.mark.parametrize(
    ("mode_value", "pool_spa_mode", "expected_mode_context", "expected_active_target"),
    [
        (2, 0, "cool_pool", 78),
        (3, 0, "auto_pool", 78),
        (2, 1, "off", None),
        (3, 1, "off", None),
    ],
)
def test_heat_pump_runtime_supports_forum_reported_modes(
    mode_value: int,
    pool_spa_mode: int,
    expected_mode_context: str,
    expected_active_target: int | None,
) -> None:
    """Test additional forum-reported heat-pump modes map to contextual states."""
    parsed_data = parse_poolsync_runtime_data(
        {
            "poolSync": {},
            "devices": {
                "0": {
                    "system": {"modelNum": "UNKNOWN"},
                    "config": {
                        "mode": mode_value,
                        "poolSpaMode": pool_spa_mode,
                        "setpoint": 78,
                        "spaSetpoint": 88,
                    },
                    "status": {"ctrlFlags": 13, "stateFlags": 8},
                }
            },
            "deviceType": {"0": "heatPump"},
        }
    )

    runtime = get_heat_pump_runtime(parsed_data)

    assert runtime is not None
    assert runtime.mode_context == expected_mode_context
    assert runtime.active_target_temperature == expected_active_target


@pytest.mark.parametrize(
    ("rssi", "expected_status"),
    [
        (-60, "good"),
        (-67, "good"),
        (-70, "fair"),
        (-75, "fair"),
        (-76, "poor"),
        (None, None),
    ],
)
def test_wifi_signal_status_uses_conservative_rssi_bands(
    rssi: int | None,
    expected_status: str | None,
) -> None:
    """Test Wi-Fi signal status maps from controller RSSI values."""
    parsed_data = parse_poolsync_runtime_data(
        {
            "poolSync": {"status": ({"rssi": rssi} if rssi is not None else {})},
            "devices": {},
        }
    )

    assert get_wifi_signal_status(parsed_data) == expected_status

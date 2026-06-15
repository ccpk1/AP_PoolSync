"""Tests for PoolSync runtime parsing helpers."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from custom_components.poolsync_custom.runtime import (
    HEAT_PUMP_PRESET_POOL,
    HEAT_PUMP_PRESET_SPA,
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


def _load_diagnostics_json(sample_name: str) -> dict:
    """Load a diagnostics JSON file, tolerant of trailing commas.

    Home Assistant diagnostic downloads sometimes include trailing commas
    in the wrapper sections. This helper strips them before parsing so
    the files can be stored exactly as exported.
    """
    sample_path = (
        Path(__file__).resolve().parents[2] / "sample_diagnostics" / sample_name
    )
    raw = sample_path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        return json.loads(cleaned)


def _load_parsed_data(sample_name: str):
    """Load parsed runtime data from a sample diagnostics export."""
    payload = _load_diagnostics_json(sample_name)
    return parse_poolsync_runtime_data(payload["data"]["runtime_data"])


@pytest.mark.parametrize(
    (
        "sample_name",
        "expected_flow",
        "expected_fan",
        "expected_compressor",
        "expected_mode_context",
        "expected_active_target",
        "expected_spa_setpoint",
    ),
    [
        ("t75-heat-pool.json", True, True, True, "heat_pool", 78, 88),
        ("t75-off-with-flow.json", True, False, False, "off", None, 88),
        ("t75-off-no-flow.json", False, False, False, "off", None, 88),
        ("t75-heatpump-fault.json", True, False, False, "heat_pool", 78, 90),
        (
            "t75-spa-startup-fan-nocompressor.json",
            True,
            True,
            False,
            "heat_spa",
            88,
            88,
        ),
        ("t75-heat-spa.json", True, True, True, "heat_spa", 88, 88),
    ],
)
def test_t75_heat_pump_runtime_states(
    sample_name: str,
    expected_flow: bool,
    expected_fan: bool,
    expected_compressor: bool,
    expected_mode_context: str,
    expected_active_target: int | None,
    expected_spa_setpoint: int,
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
    assert runtime.spa_setpoint == expected_spa_setpoint


@pytest.mark.parametrize(
    (
        "sample_name",
        "expected_flow",
        "expected_fan",
        "expected_compressor",
        "expected_mode_context",
        "expected_active_target",
        "expected_pool_setpoint",
        "expected_spa_setpoint",
    ),
    [
        ("sq160r-heating.json", True, True, True, "heat_pool", 83, 83, 0),
        ("sq160r-idle.json", True, False, False, "heat_pool", 83, 83, 0),
        ("sq160r-off.json", False, False, False, "heat_pool", 83, 83, 0),
    ],
)
def test_sq160r_heat_pump_runtime_states(
    sample_name: str,
    expected_flow: bool,
    expected_fan: bool,
    expected_compressor: bool,
    expected_mode_context: str,
    expected_active_target: int | None,
    expected_pool_setpoint: int,
    expected_spa_setpoint: int,
) -> None:
    """Test SQ160R-derived runtime state across observed sample payloads."""
    runtime = get_heat_pump_runtime(_load_parsed_data(sample_name))

    assert runtime is not None
    assert runtime.has_flow is expected_flow
    assert runtime.fan_running is expected_fan
    assert runtime.compressor_running is expected_compressor
    assert runtime.mode_context == expected_mode_context
    assert runtime.active_target_temperature == expected_active_target
    assert runtime.pool_setpoint == expected_pool_setpoint
    assert runtime.spa_setpoint == expected_spa_setpoint


def test_t75_heat_pump_capabilities_use_model_number() -> None:
    """Test the AquaCal capability profile is decoded from the model number."""
    capabilities = get_heat_pump_capabilities(_load_parsed_data("t75-heat-pool.json"))

    assert capabilities is not None
    assert capabilities.model_number == "075AHDSBLH"
    assert capabilities.profile == "aquacal_heat_only_digital"
    assert capabilities.supports_pool_spa_mode is True
    assert capabilities.supports_separate_spa_setpoint is True
    assert capabilities.supports_heating is True
    assert capabilities.supports_cooling is False


@pytest.mark.parametrize(
    (
        "model_number",
        "expected_profile",
        "expected_supports_pool_spa_mode",
        "expected_supports_separate_spa_setpoint",
        "expected_supports_heating",
        "expected_supports_cooling",
    ),
    [
        ("075AHDSBLH", "aquacal_heat_only_digital", True, True, True, False),
        ("LT0800AHDSBND", "aquacal_heat_only_digital", True, True, True, False),
        (
            "SQ225ARVSBNN",
            "aquacal_heat_cool_variable_speed",
            True,
            True,
            True,
            True,
        ),
        ("SQ225ACDSBNN", "aquacal_cool_only_digital", True, True, False, True),
        ("SQ225AHASBNN", "aquacal_heat_only_analog", False, False, True, False),
    ],
)
def test_heat_pump_capabilities_decode_aquacal_model_nomenclature(
    model_number: str,
    expected_profile: str,
    expected_supports_pool_spa_mode: bool,
    expected_supports_separate_spa_setpoint: bool,
    expected_supports_heating: bool,
    expected_supports_cooling: bool,
) -> None:
    """Test AquaCal nomenclature decoding for capability profile selection."""
    parsed_data = parse_poolsync_runtime_data(
        {
            "poolSync": {},
            "devices": {
                "0": {
                    "system": {"modelNum": model_number},
                    "config": {},
                    "status": {},
                }
            },
            "deviceType": {"0": "heatPump"},
        }
    )

    capabilities = get_heat_pump_capabilities(parsed_data)

    assert capabilities is not None
    assert capabilities.profile == expected_profile
    assert capabilities.supports_pool_spa_mode is expected_supports_pool_spa_mode
    assert (
        capabilities.supports_separate_spa_setpoint
        is expected_supports_separate_spa_setpoint
    )
    assert capabilities.supports_heating is expected_supports_heating
    assert capabilities.supports_cooling is expected_supports_cooling


def test_unknown_model_falls_back_to_payload_pool_spa_capabilities() -> None:
    """Test unknown models still infer pool/spa capability from payload fields."""
    parsed_data = parse_poolsync_runtime_data(
        {
            "poolSync": {},
            "devices": {
                "0": {
                    "system": {"modelNum": "UNKNOWN"},
                    "config": {"poolSpaMode": 1, "spaSetpoint": 88},
                    "status": {},
                }
            },
            "deviceType": {"0": "heatPump"},
        }
    )

    capabilities = get_heat_pump_capabilities(parsed_data)

    assert capabilities is not None
    assert capabilities.profile == "unknown_heat_pump"
    assert capabilities.supports_pool_spa_mode is True
    assert capabilities.supports_separate_spa_setpoint is True


def test_cool_only_heat_pump_hvac_modes_exclude_heat_and_auto() -> None:
    """Test cool-only AquaCal models only expose off and cool HVAC modes."""
    parsed_data = parse_poolsync_runtime_data(
        {
            "poolSync": {},
            "devices": {
                "0": {
                    "system": {"modelNum": "SQ225ACDSBNN"},
                    "config": {"mode": 2, "poolSpaMode": 0, "setpoint": 78},
                    "status": {"ctrlFlags": 13, "stateFlags": 8},
                }
            },
            "deviceType": {"0": "heatPump"},
        }
    )

    assert get_heat_pump_climate_hvac_modes(parsed_data) == ["off", "cool"]
    assert get_heat_pump_climate_hvac_mode(parsed_data) == "cool"
    assert get_heat_pump_climate_hvac_action(parsed_data) == "cooling"


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
        (-75, "good"),
        (-76, "fair"),
        (-80, "fair"),
        (-81, "poor"),
        (None, None),
    ],
)
def test_wifi_signal_status_uses_manufacturer_rssi_bands(
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


def test_wifi_signal_status_ignores_boolean_rssi_values() -> None:
    """Test Wi-Fi signal status ignores malformed boolean RSSI payloads."""
    parsed_data = parse_poolsync_runtime_data(
        {
            "poolSync": {"status": {"rssi": True}},
            "devices": {},
        }
    )

    assert get_wifi_signal_status(parsed_data) is None

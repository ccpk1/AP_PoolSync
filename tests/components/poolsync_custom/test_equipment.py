"""Tests for PoolSync equipment and group parsing from diagnostic data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.poolsync_custom.runtime import (
    _parse_raw_equipment,
    get_equipment_runtime,
    get_hp_in_group,
    get_pump_priming,
    get_pump_rpm,
    get_pump_rpm_max,
    get_pump_rpm_min,
    get_valve_position_name,
    get_valve_position_options,
    parse_poolsync_runtime_data,
)


def _load_diagnostics_json(sample_name: str) -> dict:
    """Load a diagnostics JSON file, tolerant of trailing commas."""
    sample_path = (
        Path(__file__).resolve().parents[2] / "sample_diagnostics" / sample_name
    )
    raw_text = sample_path.read_text(encoding="utf-8")

    # Strip trailing commas that HA diagnostics sometimes include
    cleaned = raw_text.replace(",\n}", "\n}").replace(",\n]", "\n]")
    cleaned = cleaned.replace(", }", " }").replace(", ]", " ]")

    data = json.loads(cleaned)
    return data["data"]["runtime_data"]


# ---------------------------------------------------------------------------
# Fixtures: 090 system (has equip, groups, schedules)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime_090_filtration() -> dict:
    """090 — compressor off, filtration group active, 1750 RPM."""
    return _load_diagnostics_json("090-compressor-off-filtration-group-1750rpm.json")


@pytest.fixture(scope="module")
def runtime_090_priming() -> dict:
    """090 — compressor off, priming, filtration group, 3450 RPM."""
    return _load_diagnostics_json(
        "090-compressor-off-priming-filtration-group-3450rpm.json"
    )


@pytest.fixture(scope="module")
def runtime_090_pool() -> dict:
    """090 — compressor on, pool group active, 2900 RPM."""
    return _load_diagnostics_json("090-compressor-on-2900rpm-pool-group.json")


@pytest.fixture(scope="module")
def parsed_090_filtration(runtime_090_filtration: dict):
    """Parsed data for 090 filtration snapshot."""
    return parse_poolsync_runtime_data(runtime_090_filtration)


@pytest.fixture(scope="module")
def parsed_090_priming(runtime_090_priming: dict):
    """Parsed data for 090 priming snapshot."""
    return parse_poolsync_runtime_data(runtime_090_priming)


@pytest.fixture(scope="module")
def parsed_090_pool(runtime_090_pool: dict):
    """Parsed data for 090 pool (compressor on) snapshot."""
    return parse_poolsync_runtime_data(runtime_090_pool)


# ---------------------------------------------------------------------------
# Fixtures: T75 system (no equip/groups — all null)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime_t75_heat_pool() -> dict:
    """T75 — heat pool, no equipment."""
    return _load_diagnostics_json("t75-heat-pool.json")


@pytest.fixture(scope="module")
def parsed_t75_heat_pool(runtime_t75_heat_pool: dict):
    """Parsed data for T75 heat pool snapshot."""
    return parse_poolsync_runtime_data(runtime_t75_heat_pool)


# ===================================================================
# Raw equipment parsing
# ===================================================================


class TestRawEquipmentParsing:
    """Tests for _parse_raw_equipment."""

    def test_parses_090_equipment(self, parsed_090_filtration) -> None:
        """090 equip dict should yield 3 equipment entries."""
        raw_equip = parsed_090_filtration.heat_pump.data.get("equip")
        equipment = _parse_raw_equipment(raw_equip)
        assert len(equipment) == 3
        assert "0" in equipment  # heat pump
        assert "1" in equipment  # circulation pump
        assert "3" in equipment  # return valve

    def test_equipment_slot_0_is_heat_pump(self, parsed_090_filtration) -> None:
        """Slot 0 should be heat pump type 3."""
        raw_equip = parsed_090_filtration.heat_pump.data.get("equip")
        equipment = _parse_raw_equipment(raw_equip)
        hp = equipment["0"]
        assert hp.equip_type == 3
        assert hp.name == "HEAT PUMP"
        assert hp.is_pump is False
        assert hp.is_valve is False

    def test_equipment_slot_1_is_vs_pump(self, parsed_090_filtration) -> None:
        """Slot 1 should be variable-speed pump type 0."""
        raw_equip = parsed_090_filtration.heat_pump.data.get("equip")
        equipment = _parse_raw_equipment(raw_equip)
        pump = equipment["1"]
        assert pump.equip_type == 0
        assert pump.name == "CIRCULATION PUMP"
        assert pump.is_pump is True
        assert pump.is_valve is False

    def test_equipment_slot_3_is_valve(self, parsed_090_filtration) -> None:
        """Slot 3 should be valve type 1."""
        raw_equip = parsed_090_filtration.heat_pump.data.get("equip")
        equipment = _parse_raw_equipment(raw_equip)
        valve = equipment["3"]
        assert valve.equip_type == 1
        assert valve.name == "RETURN VALVE"
        assert valve.is_pump is False
        assert valve.is_valve is True

    def test_t75_has_no_equipment(self, parsed_t75_heat_pool) -> None:
        """T75 equip should parse to empty dict."""
        raw_equip = parsed_t75_heat_pool.heat_pump.data.get("equip")
        equipment = _parse_raw_equipment(raw_equip)
        assert equipment == {}

    def test_none_equip_returns_empty(self) -> None:
        """None input returns empty dict."""
        assert _parse_raw_equipment(None) == {}


# ===================================================================
# Equipment runtime
# ===================================================================


class TestEquipmentRuntime:
    """Tests for get_equipment_runtime."""

    def test_090_has_equipment_runtime(self, parsed_090_filtration) -> None:
        """090 should have equipment runtime."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert er is not None
        assert er.has_equipment is True
        assert len(er.equipment) == 3

    def test_t75_has_no_equipment_runtime(self, parsed_t75_heat_pool) -> None:
        """T75 should return None for equipment runtime."""
        er = get_equipment_runtime(parsed_t75_heat_pool)
        assert er is None


# ===================================================================
# Pump RPM
# ===================================================================


class TestPumpRPM:
    """Tests for pump RPM extraction."""

    def test_filtration_1750_rpm(self, parsed_090_filtration) -> None:
        """Filtration group: pump at 1750 RPM."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert get_pump_rpm(er) == 1750

    def test_priming_3450_rpm(self, parsed_090_priming) -> None:
        """Priming: pump at 3450 RPM."""
        er = get_equipment_runtime(parsed_090_priming)
        assert get_pump_rpm(er) == 3450

    def test_pool_2900_rpm(self, parsed_090_pool) -> None:
        """Pool group: pump at 2900 RPM."""
        er = get_equipment_runtime(parsed_090_pool)
        assert get_pump_rpm(er) == 2900

    def test_t75_returns_none(self, parsed_t75_heat_pool) -> None:
        """T75 (no equipment) returns None."""
        er = get_equipment_runtime(parsed_t75_heat_pool)
        assert get_pump_rpm(er) is None

    def test_none_runtime_returns_none(self) -> None:
        """None runtime returns None."""
        assert get_pump_rpm(None) is None

    def test_pump_rpm_min(self, parsed_090_filtration) -> None:
        """Min RPM should be 600."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert get_pump_rpm_min(er) == 600

    def test_pump_rpm_max(self, parsed_090_filtration) -> None:
        """Max RPM should be 3450."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert get_pump_rpm_max(er) == 3450


# ===================================================================
# Pump priming
# ===================================================================


class TestPumpPriming:
    """Tests for pump priming flag."""

    def test_priming_active(self, parsed_090_priming) -> None:
        """Priming flag should be True during priming."""
        er = get_equipment_runtime(parsed_090_priming)
        assert get_pump_priming(er) is True

    def test_priming_inactive_filtration(self, parsed_090_filtration) -> None:
        """Priming flag should be False during normal filtration."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert get_pump_priming(er) is False

    def test_priming_inactive_pool(self, parsed_090_pool) -> None:
        """Priming flag should be False during pool group."""
        er = get_equipment_runtime(parsed_090_pool)
        assert get_pump_priming(er) is False

    def test_none_runtime_returns_none(self) -> None:
        """None runtime returns None for priming."""
        assert get_pump_priming(None) is None


# ===================================================================
# Valve position
# ===================================================================


class TestValvePosition:
    """Tests for valve position extraction."""

    def test_filtration_no_valve_setting(self, parsed_090_filtration) -> None:
        """Filtration group does not control the valve — position is unknown."""
        er = get_equipment_runtime(parsed_090_filtration)
        # FILTRATION group has no valve equip entry, so position is None
        assert get_valve_position_name(er) is None

    def test_priming_no_valve_setting(self, parsed_090_priming) -> None:
        """Priming (still filtration group) — valve not controlled."""
        er = get_equipment_runtime(parsed_090_priming)
        assert get_valve_position_name(er) is None

    def test_pool_group_pool_position(self, parsed_090_pool) -> None:
        """Pool group active: valve POOL (0)."""
        er = get_equipment_runtime(parsed_090_pool)
        assert get_valve_position_name(er) == "POOL"

    def test_valve_position_options(self, parsed_090_filtration) -> None:
        """Valve should have FOUNTAIN and POOL as options."""
        er = get_equipment_runtime(parsed_090_filtration)
        options = get_valve_position_options(er)
        assert options == ["FOUNTAIN", "POOL"]

    def test_t75_returns_none(self, parsed_t75_heat_pool) -> None:
        """T75 (no equipment) returns None for valve position."""
        er = get_equipment_runtime(parsed_t75_heat_pool)
        assert get_valve_position_name(er) is None


# ===================================================================
# Heat pump in group
# ===================================================================


class TestHPInGroup:
    """Tests for heat-pump-in-group flag."""

    def test_hp_not_in_filtration_group(self, parsed_090_filtration) -> None:
        """HP should not be in filtration group."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert get_hp_in_group(er) is False

    def test_hp_not_in_priming_group(self, parsed_090_priming) -> None:
        """HP should not be in priming/filtration group."""
        er = get_equipment_runtime(parsed_090_priming)
        assert get_hp_in_group(er) is False

    def test_hp_in_pool_group(self, parsed_090_pool) -> None:
        """HP should be in pool group (compressor on)."""
        er = get_equipment_runtime(parsed_090_pool)
        assert get_hp_in_group(er) is True


# ===================================================================
# Active group name
# ===================================================================


class TestActiveGroup:
    """Tests for active group detection."""

    def test_filtration_group_active(self, parsed_090_filtration) -> None:
        """Filtration snapshot: FILTRATION should be active."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert er is not None
        assert er.active_group_name == "FILTRATION"

    def test_pool_group_active(self, parsed_090_pool) -> None:
        """Pool snapshot: POOL should be active."""
        er = get_equipment_runtime(parsed_090_pool)
        assert er is not None
        assert er.active_group_name == "POOL"

    def test_group_attributes_present(self, parsed_090_filtration) -> None:
        """Group attributes should have entries for all non-null groups."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert er is not None
        attrs = er.active_group_attributes
        assert attrs is not None
        # 090 has 5 non-null groups: 0 (POOL), 1 (WATERFALL),
        # 2 (FILTRATION), 3 (AMBIANCE), 5 (CLEANER)
        assert len(attrs) == 5
        assert "0" in attrs
        assert "2" in attrs
        assert attrs["0"]["config"][0] == "POOL"
        assert attrs["2"]["config"][0] == "FILTRATION"


# ===================================================================
# Equipment data helper methods
# ===================================================================


class TestEquipmentDataHelpers:
    """Tests for PoolSyncEquipmentData helper methods."""

    def test_get_int_valid(self, parsed_090_filtration) -> None:
        """_get_int returns correct value for valid index."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert er is not None
        pump = er.equipment["1"]
        assert pump.get_int(7) == 35

    def test_get_int_oob_returns_default(self, parsed_090_filtration) -> None:
        """_get_int returns default for out-of-bounds index."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert er is not None
        pump = er.equipment["1"]
        assert pump.get_int(999) == 0
        assert pump.get_int(999, default=99) == 99

    def test_get_str_valid(self, parsed_090_filtration) -> None:
        """_get_str returns correct value for valid index."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert er is not None
        pump = er.equipment["1"]
        assert pump.get_str(1) == "CIRCULATION PUMP"

    def test_get_str_oob_returns_default(self, parsed_090_filtration) -> None:
        """_get_str returns default for out-of-bounds index."""
        er = get_equipment_runtime(parsed_090_filtration)
        assert er is not None
        valve = er.equipment["3"]
        assert valve.get_str(999) == ""

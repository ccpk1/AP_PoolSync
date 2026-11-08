"""Tests for PoolSync fault code decoding."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false

from __future__ import annotations

import pytest

from custom_components.poolsync_custom.fault_codes import (
    CHEM_FAULTS,
    CHLOR_FAULTS,
    HP10_FAULTS,
    HP_FAULTS,
    decode_faults,
    get_fault_table,
)


@pytest.mark.parametrize(
    ("role_key", "faults", "expected"),
    [
        ("chlorinator", [512], ["High Salt"]),
        ("chem_sync", [4], ["pH Above Max"]),
        ("chlorinator", [0], []),
        ("chem_sync", [0], []),
        ("chlorinator", [], []),
        ("chem_sync", [], []),
        ("chlorinator", [1], ["Cell Not Connected"]),
        ("chem_sync", [2], ["pH Below Min"]),
        ("chlorinator", [1 | 512], ["Cell Not Connected", "High Salt"]),
        # The 14-entry ChlorSync table lives entirely in faults[0].
        ("chlorinator", [1, 512], ["Cell Not Connected"]),
        ("heat_pump", [8], ["HP5 Lockout"]),
    ],
)
def test_decode_faults(role_key: str, faults: list[int], expected: list[str]) -> None:
    """Test decoding fault bitmasks into user-facing labels."""
    assert decode_faults(role_key, faults) == expected


@pytest.mark.parametrize(
    ("faults", "expected"),
    [
        (None, []),
        ("not-a-list", []),
        ([4, True], ["pH Above Max"]),
        ([1.5], []),
        ([0, 0], []),
    ],
)
def test_decode_faults_malformed(faults: object, expected: list[str]) -> None:
    """Test decode_faults handles malformed input without crashing."""
    assert decode_faults("chem_sync", faults) == expected


def test_decode_faults_unknown_role() -> None:
    """Test decode_faults returns empty for an unknown role."""
    assert decode_faults("unknown_role", [512]) == []


def test_get_fault_table() -> None:
    """Test fault table lookup by role."""
    assert get_fault_table("chlorinator") is CHLOR_FAULTS
    assert get_fault_table("chem_sync") is CHEM_FAULTS
    assert get_fault_table("heat_pump") is HP_FAULTS
    assert get_fault_table("unknown") is None


def test_get_fault_table_heat_pump_by_pid() -> None:
    """Test heat pump fault tables are selected by product ID."""
    assert get_fault_table("heat_pump", 9985) is HP10_FAULTS
    assert get_fault_table("heat_pump", 9984) is HP_FAULTS
    assert get_fault_table("heat_pump", 9986) is HP_FAULTS
    assert get_fault_table("heat_pump", None) is HP_FAULTS
    # PID only narrows heat pumps; other roles ignore it.
    assert get_fault_table("chlorinator", 9985) is CHLOR_FAULTS


@pytest.mark.parametrize(
    ("faults", "expected"),
    [
        ([1 << 0], ["Water Sensor 1"]),
        ([1 << 1], ["Water Sensor 2"]),
        ([1 << 2], ["Defrost Sensor 1"]),
        ([1 << 4], ["Compressor Fault"]),
        ([1 << 6], ["High/Low Pressure"]),
        ([1 << 7], ["HP5/LP5 Lockout"]),
        ([(1 << 0) | (1 << 4)], ["Water Sensor 1", "Compressor Fault"]),
        ([0], []),
        ([1 << 8], []),
    ],
)
def test_decode_hp10_faults(faults: list[int], expected: list[str]) -> None:
    """Test PID 9985 faults decode against the HP10 table."""
    assert decode_faults("heat_pump", faults, 9985) == expected


def test_hp10_fault_bits_differ_from_hp() -> None:
    """Test the same fault word means different things per heat pump family.

    Issue #30 shipped a 9985 unit decoded with the HP table, e.g. bit 4 became
    "Defrost Sensor 1 Open" instead of "Compressor Fault".
    """
    assert decode_faults("heat_pump", [1 << 4], 9985) == ["Compressor Fault"]
    assert decode_faults("heat_pump", [1 << 4], 9984) == ["Defrost Sensor 1 Open"]
    assert decode_faults("heat_pump", [8], 9985) == ["Defrost Sensor 2"]
    assert decode_faults("heat_pump", [8], 9986) == ["HP5 Lockout"]


@pytest.mark.parametrize(
    ("faults", "expected"),
    [
        ([1 << 31, 0], ["Internal Expansion Module"]),
        ([0, 1 << 0], ["Dual Temp Sensor"]),
        ([0, 1 << 1], ["Pump 1 Error"]),
        ([0, 1 << 3], ["Pump 3 Error"]),
        ([1 << 0, 0], ["Low Pressure"]),
        ([1 << 0, 1 << 8], ["Low Pressure", "Freeze Protect Sensor Open"]),
        # Index 44 is past the 44-entry table (indices 0-43).
        ([0, 1 << 12], []),
        ([0, 0], []),
    ],
)
def test_decode_multi_word_faults(faults: list[int], expected: list[str]) -> None:
    """Test later fault words continue the table instead of restarting at 0."""
    assert decode_faults("heat_pump", faults) == expected


def test_all_fault_tables_have_labels() -> None:
    """Test every bit in every table has a user-facing label."""
    for table in (CHLOR_FAULTS, CHEM_FAULTS, HP_FAULTS, HP10_FAULTS):
        for bit, (_internal, label) in table.items():
            assert bit >= 0
            assert label, f"Missing label for bit {bit}"


def test_chlor_fault_table_bit_positions() -> None:
    """Test the ChlorSync fault table bit positions match the app decode."""
    assert CHLOR_FAULTS[9][1] == "High Salt"
    assert CHLOR_FAULTS[11][1] == "No Flow"
    assert CHLOR_FAULTS[4][1] == "Open Cell"


def test_chem_fault_table_bit_positions() -> None:
    """Test the ChemSync fault table bit positions match the app decode."""
    assert CHEM_FAULTS[4][1] == "pH Probe"
    assert CHEM_FAULTS[5][1] == "ORP Probe"
    assert CHEM_FAULTS[2][1] == "pH Above Max"

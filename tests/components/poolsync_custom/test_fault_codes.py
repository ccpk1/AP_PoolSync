"""Tests for PoolSync fault code decoding."""

# pylint: disable=import-error,no-name-in-module

# pyright: reportMissingImports=false

from __future__ import annotations

import pytest

from custom_components.poolsync_custom.fault_codes import (
    CHEM_FAULTS,
    CHLOR_FAULTS,
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
        ("chlorinator", [1, 512], ["Cell Not Connected", "High Salt"]),
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
        ([True, 4], ["pH Above Max"]),
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


def test_all_fault_tables_have_labels() -> None:
    """Test every bit in every table has a user-facing label."""
    for table in (CHLOR_FAULTS, CHEM_FAULTS, HP_FAULTS):
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

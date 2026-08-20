"""Fault code decoding for PoolSync devices.

The fault tables below are recovered from the vendor's own app (v4.73) —
the ``faultParser`` dispatch logic and the ``CHLOR_FAULTS`` / ``CHEM_FAULTS`` /
``COMM_CHLOR_FAULTS`` / ``HP_FAULTS`` object definitions. Because this is the
vendor's shipped client, we treat it as authoritative for how faults are
surfaced to users. See ``docs/poolsync-reverse-engineering.md`` §0d.

The device ``faults[]`` array is a bitmask: each element is an integer whose
set bits map to fault names. The app converts the code to a binary string,
reverses it, and marks each fault whose bit is set as active.
"""

from __future__ import annotations

from typing import Any

# bit index -> (internal name, user-facing label)
CHLOR_FAULTS: dict[int, tuple[str, str]] = {
    0: ("cellNotConnectedError", "Cell Not Connected"),
    1: ("authFailedError", "Authentication Failed"),
    2: ("lowTemp", "Low Temperature"),
    3: ("CaBuildupError", "Calcium Buildup"),
    4: ("openCellError", "Open Cell"),
    5: ("overCurrentError", "Over Current"),
    6: ("sensorError", "Sensor Error"),
    7: ("powerFailError", "Power Failure"),
    8: ("underVoltageError", "Under Voltage"),
    9: ("highSaltWarning", "High Salt"),
    10: ("cleanCellWarning", "Clean Cell"),
    11: ("noFlow", "No Flow"),
    12: ("lowSaltWarning", "Low Salt"),
    13: ("minSaltError", "Min Salt"),
}

CHEM_FAULTS: dict[int, tuple[str, str]] = {
    0: ("PCBTemp", "PCB Temperature"),
    1: ("pHMin", "pH Below Min"),
    2: ("pHMax", "pH Above Max"),
    3: ("flowSensor", "Flow Sensor"),
    4: ("pHProbe", "pH Probe"),
    5: ("ORPProbe", "ORP Probe"),
}

# Heat pump faults. The numeric->name mapping is inferred from the app's
# HP_FAULTS object order (same bitmask scheme as ChlorSync/ChemSync).
HP_FAULTS: dict[int, tuple[str, str]] = {
    0: ("lowPressure", "Low Pressure"),
    1: ("highPressure", "High Pressure"),
    2: ("lp5Lockout", "LP5 Lockout"),
    3: ("hp5Lockout", "HP5 Lockout"),
    4: ("ds1Open", "Defrost Sensor 1 Open"),
    5: ("ds1Short", "Defrost Sensor 1 Short"),
    6: ("ds2Open", "Defrost Sensor 2 Open"),
    7: ("ds2Short", "Defrost Sensor 2 Short"),
    8: ("airTempOpen", "Air Temp Open"),
    9: ("airTempShort", "Air Temp Short"),
    10: ("highWaterTemp", "High Water Temp"),
    11: ("overTempAlarm", "Over Temp Alarm"),
    12: ("smartComms", "Smart Comms"),
    13: ("multiUnitComms", "Multi-Unit Comms"),
    14: ("poolSpaInletWaterTempOpen", "Pool-Spa Inlet Water Temp Open"),
    15: ("poolSpaInletWaterTempShort", "Pool-Spa Inlet Water Temp Short"),
    16: ("solarRoofTempOpen", "Solar Roof Temp Open"),
    17: ("solarRoofTempShort", "Solar Roof Temp Short"),
    18: ("lowClockBattery", "Low Clock Battery"),
    19: ("highHpcPcbTemp", "High Controller PCB Temp"),
    20: ("highDisplayTemp", "High Display Temp"),
    21: ("variableDrive", "Variable Drive"),
    22: ("sourceFlow", "Source Flow"),
    23: ("poolSpaOutletTempOpen", "Pool-Spa Outlet Temp Open"),
    24: ("poolSpaOutletTempShort", "Pool-Spa Outlet Temp Short"),
    25: ("sourceInletTempOpen", "Source Inlet Temp Open"),
    26: ("sourceInletTempShort", "Source Inlet Temp Short"),
    27: ("sourceOutletTempOpen", "Source Outlet Temp Open"),
    28: ("sourceOutletTempShort", "Source Outlet Temp Short"),
    29: ("sourceInletHighWaterTemp", "Source Inlet High Water Temp"),
    30: ("sourceInletLowWaterTemp", "Source Inlet Low Water Temp"),
    31: ("internalExpansionModule", "Internal Expansion Module"),
    32: ("dualTempSensor", "Dual Temp Sensor"),
    33: ("pump1Comms", "Pump 1 Error"),
    34: ("pump2Comms", "Pump 2 Error"),
    35: ("pump3Comms", "Pump 3 Error"),
    36: ("pump4Comms", "Pump 4 Error"),
    37: ("solarPoolSpaInletTempOpen", "Solar Pool-Spa Inlet Temp Open"),
    38: ("solarPoolSpaInletTempShort", "Solar Pool-Spa Inlet Temp Short"),
    39: ("freezeProtectSensorShort", "Freeze Protect Sensor Short"),
    40: ("freezeProtectSensorOpen", "Freeze Protect Sensor Open"),
    41: ("multiplePrimaryDetected", "Multiple Primary Detected"),
    42: ("compressorProtect", "Compressor Protect"),
    43: ("compressorProtectLockout", "Compressor Protect Lockout"),
}

# role_key -> fault table
_FAULT_TABLES: dict[str, dict[int, tuple[str, str]]] = {
    "chlorinator": CHLOR_FAULTS,
    "chem_sync": CHEM_FAULTS,
    "heat_pump": HP_FAULTS,
}


def get_fault_table(role_key: str) -> dict[int, tuple[str, str]] | None:
    """Return the fault table for a device role, or None if unknown."""
    return _FAULT_TABLES.get(role_key)


def decode_faults(role_key: str, faults: Any) -> list[str]:
    """Decode a device ``faults[]`` array into user-facing fault labels.

    Each element of ``faults`` is treated as a bitmask. Returns the list of
    user-facing labels for every set bit, in ascending bit order. Returns an
    empty list for unknown roles, malformed input, or no active faults.
    """
    table = get_fault_table(role_key)
    if table is None or not isinstance(faults, list):
        return []

    decoded: list[str] = []
    for fault_code in faults:
        if isinstance(fault_code, bool) or not isinstance(fault_code, int):
            continue
        if fault_code <= 0:
            continue
        for bit in range(fault_code.bit_length()):
            if fault_code & (1 << bit):
                if entry := table.get(bit):
                    decoded.append(entry[1])
    return decoded

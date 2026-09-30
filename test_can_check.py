"""Regression tests for the three checks.

Two kinds, and both are needed.

The tests over the sample log pin down what the tool reports on data with known
faults: three seeded faults, exactly three findings, and nothing at all over the
clean first four seconds. That is the end-to-end behaviour.

The tests on hand-built frames pin down the edges the sample log happens not to
contain — a counter wrapping 15 to 0, a car standing still with all four wheels
at zero. Those are the cases where a check would produce a false alarm, and a
false alarm is what makes an engineer stop trusting the tool.

    python -m pytest -v
"""

from pathlib import Path

import pandas as pd
import pytest

from can_check import (
    CYCLE_MS,
    TIMEOUT_FACTOR,
    analyse,
    check_counter,
    check_plausibility,
    check_timeout,
    load_log,
)

HERE = Path(__file__).parent
LOG = HERE / "run01_frenada_musplit.asc"
DBC = HERE / "chassis.dbc"


@pytest.fixture(scope="module")
def table():
    return load_log(LOG, DBC)


# --- End to end, over the sample log -----------------------------------------


def test_log_decodes_completely(table):
    assert len(table) == 3569
    assert table["t"].max() == pytest.approx(11.99, abs=0.01)


def test_finds_the_three_seeded_faults(table):
    """Three faults were seeded. The tool reports those three and no others."""
    findings = analyse(table)

    assert len(findings) == 3, [f["kind"] for f in findings]
    assert [f["kind"] for f in findings] == ["counter", "plausibility", "timeout"]
    assert [f["where"] for f in findings] == [
        "BRAKE_01.Brake_Alive_Counter",
        "Wheel_Speed_RL",
        "VEHICLE_DYN_01",
    ]


def test_each_fault_is_reported_where_it_was_seeded(table):
    windows = {f["kind"]: (f["start"], f["end"]) for f in analyse(table)}
    assert windows["counter"] == pytest.approx((4.20, 4.59), abs=0.01)
    assert windows["plausibility"] == pytest.approx((5.00, 5.34), abs=0.01)
    assert windows["timeout"] == pytest.approx((5.98, 6.62), abs=0.01)


def test_clean_window_is_quiet(table):
    """No false positives: the first four seconds carry none of the faults."""
    assert analyse(table[table["t"] <= 4.0]) == []


def test_findings_come_out_in_time_order(table):
    starts = [f["start"] for f in analyse(table)]
    assert starts == sorted(starts)


def test_the_reported_gap_really_exceeds_the_limit(table):
    """The timeout is not taken on trust: check it against its own threshold."""
    finding = check_timeout(table, "VEHICLE_DYN_01", CYCLE_MS["VEHICLE_DYN_01"])
    gap_ms = (finding["end"] - finding["start"]) * 1000
    assert gap_ms > CYCLE_MS["VEHICLE_DYN_01"] * TIMEOUT_FACTOR


# --- The edges, on hand-built frames -----------------------------------------


def frames(message, **columns):
    """A small table shaped like the decoded log."""
    length = len(next(iter(columns.values())))
    return pd.DataFrame({
        "t": [round(i * 0.01, 3) for i in range(length)],
        "message": [message] * length,
        **columns,
    })


def test_counter_wrapping_15_to_0_is_not_a_jump():
    """Modulo 16: after 15 comes 0, and that is the counter working."""
    table = frames("BRAKE_01", Brake_Alive_Counter=[13, 14, 15, 0, 1, 2])
    assert check_counter(table, "BRAKE_01", "Brake_Alive_Counter") is None


def test_counter_skipping_one_is_a_jump():
    table = frames("BRAKE_01", Brake_Alive_Counter=[1, 2, 4, 5])
    finding = check_counter(table, "BRAKE_01", "Brake_Alive_Counter")
    assert finding is not None
    assert "2 -> 4" in finding["detail"]


def test_counter_stuck_is_a_jump():
    """A counter that stops moving is the classic frozen-frame symptom."""
    table = frames("BRAKE_01", Brake_Alive_Counter=[7, 7, 7, 7])
    assert check_counter(table, "BRAKE_01", "Brake_Alive_Counter") is not None


def test_car_at_rest_is_not_a_plausibility_fault():
    """Four wheels at zero is a parked car, not a sensor failure."""
    table = frames(
        "WHEEL_SPEEDS_01",
        Wheel_Speed_FL=[0.0] * 5, Wheel_Speed_FR=[0.0] * 5,
        Wheel_Speed_RL=[0.0] * 5, Wheel_Speed_RR=[0.0] * 5,
    )
    assert check_plausibility(table) == []


def test_rolling_to_a_halt_is_not_a_plausibility_fault():
    """All four crossing zero together, which is what stopping looks like."""
    table = frames(
        "WHEEL_SPEEDS_01",
        Wheel_Speed_FL=[6.0, 4.0, 2.0, 0.5], Wheel_Speed_FR=[6.1, 4.1, 2.1, 0.6],
        Wheel_Speed_RL=[5.9, 3.9, 1.9, 0.4], Wheel_Speed_RR=[6.0, 4.0, 2.0, 0.5],
    )
    assert check_plausibility(table) == []


def test_one_wheel_at_zero_while_the_rest_turn_is_a_fault():
    table = frames(
        "WHEEL_SPEEDS_01",
        Wheel_Speed_FL=[80.0] * 4, Wheel_Speed_FR=[80.0] * 4,
        Wheel_Speed_RL=[0.0] * 4, Wheel_Speed_RR=[80.0] * 4,
    )
    findings = check_plausibility(table)
    assert len(findings) == 1
    assert findings[0]["where"] == "Wheel_Speed_RL"


def test_timeout_needs_a_gap_not_just_jitter():
    """Cycle jitter is normal. Only a real dropout counts."""
    table = frames("BRAKE_01", Brake_Alive_Counter=[1, 2, 3, 4])
    table["t"] = [0.000, 0.011, 0.019, 0.032]      # 10 ms nominal, wobbling
    assert check_timeout(table, "BRAKE_01", CYCLE_MS["BRAKE_01"]) is None

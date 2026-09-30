"""can-signal-checker: validate a CAN log against its DBC matrix.

Usage:
    python can_check.py <log.asc> <matrix.dbc> [max_seconds]

Three checks:
    1. Timeout       - a message stops being transmitted
    2. Counter       - the rolling counter does not increment by one
    3. Plausibility  - one wheel stopped while the vehicle is moving

Each of the three catches something the other two cannot. A frame can carry
values that are all in range and still be wrong, because it arrived late,
because the counter says frames were lost on the way, or because it contradicts
its neighbours.
"""

import sys

import can
import cantools
import numpy as np
import pandas as pd

# Nominal cycle time of each message, in milliseconds
CYCLE_MS = {
    "BRAKE_01":        10,
    "STEERING_01":     10,
    "WHEEL_SPEEDS_01": 20,
    "VEHICLE_DYN_01":  20,
}

# A gap longer than this many nominal cycles counts as a timeout
TIMEOUT_FACTOR = 5

# Rolling counters: message -> signal
COUNTERS = {
    "BRAKE_01":        "Brake_Alive_Counter",
    "WHEEL_SPEEDS_01": "Wheel_Alive_Counter",
    "STEERING_01":     "Steering_Alive_Counter",
}

WHEELS = ["Wheel_Speed_FL", "Wheel_Speed_FR", "Wheel_Speed_RL", "Wheel_Speed_RR"]

# A wheel reading below this is treated as stopped, and the others are treated
# as turning above the second. The gap between them is deliberate: it keeps the
# check quiet while the car is rolling to a halt and all four are near zero.
WHEEL_STOPPED_KPH = 1.0
WHEEL_TURNING_KPH = 5.0


def load_log(log_path, dbc_path):
    """Decode the whole log and return a table, one row per frame."""
    db = cantools.database.load_file(dbc_path)
    rows = []

    with can.ASCReader(log_path) as reader:
        for frame in reader:
            try:
                message = db.get_message_by_frame_id(frame.arbitration_id)
            except KeyError:
                continue                      # an ID the DBC does not describe

            row = {"t": frame.timestamp, "message": message.name}
            row.update({n: float(v) for n, v in message.decode(frame.data).items()})
            rows.append(row)

    return pd.DataFrame(rows)


def check_timeout(table, name, cycle_ms):
    """A message that stops arriving for more than TIMEOUT_FACTOR cycles."""
    frames = table[table["message"] == name]
    if len(frames) < 2:
        return None

    times = frames["t"].to_numpy()
    gaps = np.diff(times) * 1000
    limit = cycle_ms * TIMEOUT_FACTOR

    if gaps.max() <= limit:
        return None

    worst = int(np.argmax(gaps))
    return {
        "kind": "timeout",
        "where": name,
        "start": float(times[worst]),
        "end": float(times[worst + 1]),
        "detail": f"gap of {gaps.max():.0f} ms, nominal cycle {cycle_ms} ms",
    }


def check_counter(table, name, signal):
    """The rolling counter must increment by one every frame, modulo 16."""
    frames = table[table["message"] == name]
    if len(frames) < 2 or signal not in frames:
        return None

    times = frames["t"].to_numpy()
    values = frames[signal].to_numpy()

    jumps = [i for i in range(1, len(values))
             if (values[i] - values[i - 1]) % 16 != 1]

    if not jumps:
        return None

    first = jumps[0]
    return {
        "kind": "counter",
        "where": f"{name}.{signal}",
        "start": float(times[first]),
        "end": float(times[jumps[-1]]),
        "detail": f"{len(jumps)} jumps, the first {int(values[first - 1])} -> {int(values[first])}",
    }


def check_plausibility(table):
    """One wheel stopped while the other three turn is not physically possible."""
    wheels = table[table["message"] == "WHEEL_SPEEDS_01"]
    if wheels.empty:
        return []

    findings = []

    for stopped in WHEELS:
        others = [n for n in WHEELS if n != stopped]
        suspect = wheels[(wheels[stopped] < WHEEL_STOPPED_KPH)
                         & (wheels[others].min(axis=1) > WHEEL_TURNING_KPH)]

        if suspect.empty:
            continue

        findings.append({
            "kind": "plausibility",
            "where": stopped,
            "start": float(suspect["t"].iloc[0]),
            "end": float(suspect["t"].iloc[-1]),
            "detail": f"{len(suspect)} frames at 0 km/h with the other three turning",
        })

    return findings


def analyse(table):
    """Run the three checks and return the findings, earliest first."""
    findings = []

    for name, cycle in CYCLE_MS.items():
        finding = check_timeout(table, name, cycle)
        if finding:
            findings.append(finding)

    for name, signal in COUNTERS.items():
        finding = check_counter(table, name, signal)
        if finding:
            findings.append(finding)

    findings.extend(check_plausibility(table))

    findings.sort(key=lambda f: f["start"])
    return findings


def report(findings, table, log_path):
    """Print the findings the way an engineer would want to read them."""
    print(f"\n{log_path}")
    print(f"{len(table)} frames   {table['t'].max():.2f} s   "
          f"{len(findings)} findings\n")

    if not findings:
        print("  No findings. Communication is sound.")
        return

    for f in findings:
        print(f"  {f['kind']:15} {f['where']:28} "
              f"{f['start']:6.2f} - {f['end']:6.2f} s   {f['detail']}")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1

    log_path, dbc_path = argv[1], argv[2]
    table = load_log(log_path, dbc_path)

    if len(argv) > 3:
        limit = float(argv[3])
        table = table[table["t"] <= limit]
        print(f"Analysing up to t = {limit} s only")

    report(analyse(table), table, log_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

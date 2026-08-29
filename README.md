# can-signal-checker

CAN bus log validation against a DBC matrix. Built while learning Python for
vehicle test data analysis.

## What it checks

**Timeout** — a message stops being transmitted for longer than 5 nominal cycles.
The cycle time of each message is declared in `CICLOS_MS`.

**Rolling counter** — the alive counter must increment by one every frame,
modulo 16. A jump means frames were lost in transit or the transmitting ECU is
faulty, even when the frames that did arrive look perfectly valid.

**Plausibility** — one wheel reading 0 km/h while the other three are turning.
Each value is within range on its own; together they are not physically possible.

## Usage

    python can_check.py <log.asc> <matrix.dbc> [max_seconds]

The optional third argument limits the analysis to the first N seconds.

## Example output

    run01_frenada_musplit.asc
    3569 frames   11.99 s   3 findings

      contador        BRAKE_01.Brake_Alive_Counter   4.20 -  4.59 s
      plausibilidad   Wheel_Speed_RL                 5.00 -  5.34 s
      timeout         VEHICLE_DYN_01                 5.98 -  6.62 s

Running the same log limited to the first 4 seconds reports nothing, which shows
the checks do not fire on clean data.

## Sample data

`run01_frenada_musplit.asc` and `chassis.dbc` are **synthetic**. They were
generated for practice, with three faults deliberately seeded, and they are not
measurements from a real vehicle.

The log represents an emergency braking event from 100 to 0 km/h on a split-mu
surface: left wheels on ice, right wheels on dry asphalt.

## Requirements

    pip install cantools python-can pandas numpy

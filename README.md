# can-signal-checker

CAN bus log validation against a DBC matrix. Built while learning Python for
vehicle test data analysis.

## What it checks

Each of the three catches something the other two cannot. A frame can carry
values that are all in range and still be wrong.

**Timeout** — a message stops being transmitted for longer than 5 nominal cycles.
The cycle time of each message is declared in `CYCLE_MS`.

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

      counter         BRAKE_01.Brake_Alive_Counter   4.20 -  4.59 s   40 jumps, the first 4 -> 7
      plausibility    Wheel_Speed_RL                 5.00 -  5.34 s   18 frames at 0 km/h with the other three turning
      timeout         VEHICLE_DYN_01                 5.98 -  6.62 s   gap of 640 ms, nominal cycle 20 ms

Running the same log limited to the first 4 seconds reports nothing, which shows
the checks do not fire on clean data.

## Tests

    pip install -r requirements.txt
    python -m pytest -v

Thirteen of them, in two groups, and both groups are needed.

Six run over the sample log and pin down the end-to-end behaviour: three seeded
faults, exactly three findings, each in the window it was seeded in, and nothing
at all over the clean first four seconds.

Seven run on hand-built frames and cover the edges the sample log happens not to
contain. A counter wrapping 15 to 0 is the counter working, not a jump. Four
wheels at zero is a parked car. Four wheels crossing zero together is a car
coming to a halt. Cycle jitter is not a dropout. **Those are the cases where a
check would raise a false alarm, and a false alarm is what makes an engineer stop
trusting a tool.**

The suite was checked by breaking the code on purpose: removing the modulo 16
from the counter, raising the timeout threshold tenfold, dropping the margin
between "stopped" and "turning", and removing the sort. Each mutation was caught
by two to four tests. A suite that has never failed has not demonstrated
anything.

CI runs all of this on every push.

## Sample data

`run01_frenada_musplit.asc` and `chassis.dbc` are **synthetic**. They were
generated for practice, with three faults deliberately seeded, and they are not
measurements from a real vehicle.

The log represents an emergency braking event from 100 to 0 km/h on a split-mu
surface: left wheels on ice, right wheels on dry asphalt.

Because the faults were planted by me, the tool finding them proves the checks
work — not that anything was discovered. That distinction matters and it is why
this repository claims nothing beyond it.

## Requirements

    pip install -r requirements.txt

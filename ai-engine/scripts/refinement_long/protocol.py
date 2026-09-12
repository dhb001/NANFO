"""ADR016 namespace admission; unchanged V5 wire, raw evidence and measured features."""

from history import OLD

RANGES = {"train": [10000, 19999], "validation": [20000, 29999], "test": [30000, 39999]}
Request = OLD["evidence"].Request
Transport = OLD["evidence"].Transport
phase = OLD["evidence"].phase
validate = OLD["evidence"].validate
PROFILES = OLD["plan"].PROFILES


def validateSchedule(split, rows):
    if split not in RANGES or not rows or len(rows) % 8:
        raise ValueError("ADR016 requires balanced eight-profile blocks in explicit namespace")
    lo, hi = RANGES[split]
    seeds = []
    for index, row in enumerate(rows):
        if (
            set(row) != {"seed", "scenario"}
            or type(row["seed"]) is not int
            or not lo <= row["seed"] <= hi
            or row["scenario"] != PROFILES[index % 8]
        ):
            raise ValueError("ADR016 seed/profile namespace differs; no remapping")
        seeds.append(row["seed"])
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate seed")


def schedule(first, count):
    return [{"seed": first + i, "scenario": PROFILES[i % 8]} for i in range(count)]

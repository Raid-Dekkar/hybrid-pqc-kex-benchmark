"""Run one independent benchmark session and write per-trial raw data.

Design choices (README, "Measurement protocol"):
  * time.perf_counter_ns() monotonic clock, nanosecond resolution
  * W warm-up iterations per scheme, discarded
  * N measured trials per scheme; within each trial index the order of the
    seven schemes is shuffled (seeded) to spread drift/thermal effects evenly
  * Python's cyclic garbage collector disabled for the whole measured phase
    (no collection between trials: a forced collection releases memory
    arenas, and the next allocations then incur page faults that inflate the
    first operations of the following trial; README, "Validation")
  * correctness asserted on every trial (both sides derive the same key)
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench.env_info import collect  # noqa: E402
from bench.schemes import all_schemes  # noqa: E402

FIELDS = ["run_id", "trial", "order_in_trial", "scheme", "family", "mlkem_level",
          "nist_category", "keygen_ns", "encap_ns", "decap_ns", "total_ns",
          "pk_bytes", "ct_bytes", "total_bytes"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=1)
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--seed", type=int, default=None,
                    help="shuffle seed (default: 2026 + run_id)")
    ap.add_argument("--out", type=Path, default=Path("results/raw"))
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else 2026 + args.run_id
    rng = random.Random(seed)
    args.out.mkdir(parents=True, exist_ok=True)

    schemes = all_schemes()
    env = collect()
    env["run"] = {"run_id": args.run_id, "trials": args.trials,
                  "warmup": args.warmup, "shuffle_seed": seed,
                  "schemes": [s.name for s in schemes]}

    for _ in range(args.warmup):
        for s in schemes:
            s.run_trial()

    rows = []
    gc.collect()
    gc.disable()
    try:
        for t in range(args.trials):
            order = schemes[:]
            rng.shuffle(order)
            for pos, s in enumerate(order):
                r = s.run_trial()
                rows.append({
                    "run_id": args.run_id, "trial": t, "order_in_trial": pos,
                    "scheme": s.name, "family": s.family,
                    "mlkem_level": s.level or "", "nist_category": s.nist_category or "",
                    "keygen_ns": r.keygen_ns, "encap_ns": r.encap_ns,
                    "decap_ns": r.decap_ns, "total_ns": r.total_ns,
                    "pk_bytes": r.pk_bytes, "ct_bytes": r.ct_bytes,
                    "total_bytes": r.pk_bytes + r.ct_bytes,
                })
    finally:
        gc.enable()

    raw = args.out / f"run_{args.run_id:02d}_trials.csv"
    with raw.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (args.out / f"run_{args.run_id:02d}_environment.json").write_text(
        json.dumps(env, indent=2))
    print(f"run {args.run_id}: {len(rows)} trials -> {raw} (all keys matched)")


if __name__ == "__main__":
    main()

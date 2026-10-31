#!/usr/bin/env python3
"""Evaluate diagnosis against this repository's generator with isolated ground truth."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from netcoop.cli.main import _load_observations_from_target
from netcoop.supervisor.runtime import SupervisorRuntime
from reference.sample_generator import SCENARIO_PRESETS, generate_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="7,42,2026", help="Comma-separated deterministic seeds")
    parser.add_argument("--steps", type=int, default=15)
    args = parser.parse_args()
    seeds = [int(value.strip()) for value in args.seeds.split(",") if value.strip()]
    labels = {"healthy": "ABSTAIN", **{name: name.upper() for name in SCENARIO_PRESETS if name != "healthy"}}
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    target_correct = 0
    total = 0

    with tempfile.TemporaryDirectory(prefix="netcoop-eval-") as temp_dir:
        root = Path(temp_dir)
        for seed in seeds:
            for scenario_name in SCENARIO_PRESETS:
                scenario_dir = root / f"{scenario_name}-{seed}"
                generate_scenario(scenario_name, scenario_dir, seed=seed, num_steps=args.steps)
                incident_id, observations = _load_observations_from_target(scenario_dir)
                report = SupervisorRuntime().run_incident(incident_id, observations)

                # Ground truth is read only after diagnosis has completed.
                truth = json.loads((scenario_dir / "evaluation" / "ground_truth.json").read_text(encoding="utf-8"))
                actual = labels[truth["injected_fault_class"]]
                if report.status == "insufficient_evidence":
                    predicted = "ABSTAIN"
                else:
                    candidates = [report.suspected_root_cause, *report.concurrent_causes]
                    predicted = next(
                        (label for label in labels.values() if label != "ABSTAIN"
                         and any(label in item.upper() for item in candidates)),
                        "OTHER",
                    )
                confusion[actual][predicted] += 1
                total += 1
                target = truth.get("target_entity")
                if actual == "ABSTAIN" or (target and target in report.affected_devices):
                    target_correct += 1

    exact = sum(confusion[label][label] for label in labels.values())
    print(f"Cases: {total}; exact class accuracy: {exact}/{total} ({exact / total:.1%}); "
          f"target accuracy: {target_correct}/{total} ({target_correct / total:.1%})")
    print("Actual \\ Predicted | " + " | ".join(labels.values()) + " | OTHER")
    for actual in labels.values():
        row = [str(confusion[actual][predicted]) for predicted in labels.values()]
        print(f"{actual:18} | " + " | ".join(row) + f" | {confusion[actual]['OTHER']}")


if __name__ == "__main__":
    main()
